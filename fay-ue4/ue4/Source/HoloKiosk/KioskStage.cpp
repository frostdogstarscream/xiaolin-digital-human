#include "KioskStage.h"
#include "KioskCharacter.h"
#include "KioskPcmSynth.h"
#include "Camera/CameraComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/AudioComponent.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "Engine/GameViewportClient.h"
#include "GameFramework/GameUserSettings.h"
#include "GameFramework/PlayerController.h"
#include "HAL/PlatformProcess.h"
#include "HAL/IConsoleManager.h"
#include "GenericPlatform/GenericApplication.h"
#include "Misc/Base64.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "WebSocketsModule.h"
#include "IWebSocket.h"
#include "Async/Async.h"
#include "Widgets/SWindow.h"
#include "Kismet/GameplayStatics.h"
#include "Sound/SoundWave.h"
#include "Audio.h"
#include "HighResScreenshot.h"
#include "UnrealClient.h"
#include "Components/PoseableMeshComponent.h"

AKioskGameMode::AKioskGameMode(){DefaultPawnClass=nullptr;}
void AKioskGameMode::BeginPlay(){Super::BeginPlay();GetWorld()->SpawnActor<AKioskStage>();}
AKioskStage::AKioskStage(){
    PrimaryActorTick.bCanEverTick=true;
    RootComponent=CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
    Camera=CreateDefaultSubobject<UCameraComponent>(TEXT("Camera"));Camera->SetupAttachment(RootComponent);
    Camera->SetRelativeLocation(FVector(350,0,90));Camera->SetRelativeRotation(FRotator(0,180,0));Camera->FieldOfView=35;
    Camera->bConstrainAspectRatio=false;
    Camera->PostProcessSettings.bOverride_AutoExposureMinBrightness=true;Camera->PostProcessSettings.AutoExposureMinBrightness=1;
    Camera->PostProcessSettings.bOverride_AutoExposureMaxBrightness=true;Camera->PostProcessSettings.AutoExposureMaxBrightness=1;
    KeyLight=CreateDefaultSubobject<UDirectionalLightComponent>(TEXT("KeyLight"));KeyLight->SetupAttachment(RootComponent);KeyLight->SetRelativeRotation(FRotator(-20,-150,0));KeyLight->SetIntensity(3);KeyLight->SetCastShadows(false);
    FillLight=CreateDefaultSubobject<UDirectionalLightComponent>(TEXT("FillLight"));FillLight->SetupAttachment(RootComponent);FillLight->SetRelativeRotation(FRotator(-15,130,0));FillLight->SetIntensity(1);FillLight->SetCastShadows(false);
    Voice=CreateDefaultSubobject<UKioskPcmSynth>(TEXT("Voice"));Voice->SetupAttachment(RootComponent);
}
void AKioskStage::BeginPlay(){
    Super::BeginPlay();
    if(auto* PC=GetWorld()->GetFirstPlayerController()){PC->SetViewTarget(this);PC->bShowMouseCursor=false;PC->SetInputMode(FInputModeGameOnly());}
    Voice->Start();
    bPreviewMode=FParse::Value(FCommandLine::Get(),TEXT("CharacterPreview="),PreviewPath);
    if(bPreviewMode){LoadPreview();bMotionSuite=FParse::Param(FCommandLine::Get(),TEXT("MotionSuite"));MetricsStart=FPlatformTime::Seconds();return;}
    FString Text;
    if(FFileHelper::LoadFileToString(Text,*(FPaths::ProjectContentDir()/TEXT("Data/avatars.json")))){
        auto Reader=TJsonReaderFactory<>::Create(Text);FJsonSerializer::Deserialize(Reader,Avatars);
    }
    ApplyAvatar(TEXT("diagnostic_slate"));
    MetricsStart=FPlatformTime::Seconds();Connect();
}
void AKioskStage::LoadPreview(){
    FString Text;TSharedPtr<FJsonObject> Spec;
    if(!FFileHelper::LoadFileToString(Text,*PreviewPath)){ClientError(TEXT("Cannot read preview manifest"));return;}
    auto Reader=TJsonReaderFactory<>::Create(Text);
    if(!FJsonSerializer::Deserialize(Reader,Spec)||!Spec.IsValid()){ClientError(TEXT("Invalid preview JSON"));return;}
    FString Id,ClassPath;
    if(!Spec->TryGetStringField(TEXT("id"),Id)||!Spec->TryGetStringField(TEXT("actor_class"),ClassPath)||ClassPath!=TEXT("/Script/HoloKiosk.KioskCharacter")){ClientError(TEXT("Preview requires native KioskCharacter"));return;}
    Avatars.Empty();Avatars.Add(MakeShared<FJsonValueObject>(Spec));AvatarId.Empty();ApplyAvatar(Id);
    if(AvatarId!=Id)return;
    bPreviewSpeaking=false;PreviewJaw=0;PreviewBlink=-1;PreviewAudioPath.Empty();
    double Jaw=0,Blink=-1,Distance=350,Height=90;
    Spec->TryGetNumberField(TEXT("preview_jaw"),Jaw);Spec->TryGetNumberField(TEXT("preview_blink"),Blink);
    Spec->TryGetNumberField(TEXT("preview_camera_distance"),Distance);Spec->TryGetNumberField(TEXT("preview_camera_height"),Height);
    if(FMath::IsFinite(Jaw))PreviewJaw=FMath::Clamp(static_cast<float>(Jaw),0.f,1.f);
    if(FMath::IsFinite(Blink))PreviewBlink=FMath::Clamp(static_cast<float>(Blink),-1.f,1.f);
    if(FMath::IsFinite(Distance)&&FMath::IsFinite(Height))Camera->SetRelativeLocation(FVector(FMath::Clamp(Distance,60.0,600.0),0,FMath::Clamp(Height,0.0,200.0)));
    Spec->TryGetStringField(TEXT("preview_audio"),PreviewAudioPath);
    if(!PreviewAudioPath.IsEmpty()&&FPaths::IsRelative(PreviewAudioPath))PreviewAudioPath=FPaths::ConvertRelativePathToFull(FPaths::ProjectDir(),PreviewAudioPath);
    FString State=TEXT("idle");Spec->TryGetStringField(TEXT("preview_state"),State);
    Character->SetDialogueState(State==TEXT("speaking")?FName("speaking"):FName("idle"));
    bool AutoPlay=false;Spec->TryGetBoolField(TEXT("preview_autoplay"),AutoPlay);if(AutoPlay)PlayPreviewAudio();
    UE_LOG(LogTemp,Display,TEXT("Kiosk preview loaded: %s jaw=%.2f blink=%.2f"),*Id,PreviewJaw,PreviewBlink);
    if(GEngine)GEngine->AddOnScreenDebugMessage(-1,12,FColor::Yellow,TEXT("LOCAL PREVIEW: Space audio / J jaw / B blink / R reload / Esc reset / F9 screenshot"));
}
void AKioskStage::PlayPreviewAudio(){
    StopPlayback();bPreviewSpeaking=false;
    if(Character)Character->SetDialogueState("idle");
    TArray<uint8> Data;FWaveModInfo Info;
    const int64 Bytes=IFileManager::Get().FileSize(*PreviewAudioPath);
    if(Bytes<=0||Bytes>4*1024*1024||!FFileHelper::LoadFileToArray(Data,*PreviewAudioPath)||!Info.ReadWaveInfo(Data.GetData(),Data.Num())||!Info.pFormatTag||*Info.pFormatTag!=1||*Info.pChannels!=1||*Info.pSamplesPerSec!=24000||*Info.pBitsPerSample!=16){ClientError(TEXT("Preview audio must be a local PCM16 mono 24000Hz WAV under 4 MB"));return;}
    TArray<uint8> PCM;PCM.Append(Info.SampleDataStart,Info.SampleDataSize);
    Voice->BeginSegment();if(!Voice->AppendPCM(PCM)){ClientError(TEXT("Preview audio queue rejected"));return;}Voice->EndSegment();
    bPreviewSpeaking=true;PreviewJaw=0;if(Character){Character->SetDialogueState("speaking");Character->PlayMotion("speaking");}
    UE_LOG(LogTemp,Display,TEXT("Kiosk local audio started: %d samples"),PCM.Num()/2);
}
void AKioskStage::Connect(){
    if(bShuttingDown)return;
    const uint64 Generation=++ConnectionGeneration;
    if(Socket){Socket->OnMessage().Clear();Socket->OnConnected().Clear();Socket->OnClosed().Clear();Socket->OnConnectionError().Clear();Socket->Close();}
    Socket=FWebSocketsModule::Get().CreateWebSocket(TEXT("ws://127.0.0.1:8780/ws"));
    const TWeakObjectPtr<AKioskStage> Weak(this);
    Socket->OnConnected().AddLambda([Weak,Generation](){AsyncTask(ENamedThreads::GameThread,[Weak,Generation](){if(Weak.IsValid()&&Weak->ConnectionGeneration==Generation){Weak->bConnected=true;Weak->SessionId.Empty();Weak->Turn=-1;}});});
    Socket->OnMessage().AddLambda([Weak,Generation](const FString& Message){AsyncTask(ENamedThreads::GameThread,[Weak,Generation,Message](){if(Weak.IsValid()&&Weak->ConnectionGeneration==Generation)Weak->Receive(Message);});});
    Socket->OnClosed().AddLambda([Weak,Generation](int32 Code,const FString& Reason,bool Clean){AsyncTask(ENamedThreads::GameThread,[Weak,Generation](){if(Weak.IsValid()&&Weak->ConnectionGeneration==Generation)Weak->Disconnected();});});
    Socket->OnConnectionError().AddLambda([Weak,Generation](const FString& Error){AsyncTask(ENamedThreads::GameThread,[Weak,Generation](){if(Weak.IsValid()&&Weak->ConnectionGeneration==Generation)Weak->Disconnected();});});
    Socket->Connect();RetryAt=FPlatformTime::Seconds()+5;
}
void AKioskStage::Disconnected(){bConnected=false;StopPlayback();SessionId.Empty();Turn=-1;RetryAt=FPlatformTime::Seconds()+3;if(Character)Character->SetDialogueState("idle");}
void AKioskStage::Send(const TSharedRef<FJsonObject>& Message){
    if(!Socket||!Socket->IsConnected())return;
    FString Text;auto Writer=TJsonWriterFactory<>::Create(&Text);FJsonSerializer::Serialize(Message,Writer);Socket->Send(Text);
}
void AKioskStage::SendType(const FString& Type){auto M=MakeShared<FJsonObject>();M->SetStringField(TEXT("type"),Type);Send(M);}
void AKioskStage::ClientError(const FString& Message){UE_LOG(LogTemp,Warning,TEXT("Kiosk: %s"),*Message);auto M=MakeShared<FJsonObject>();M->SetStringField(TEXT("type"),TEXT("client.error"));M->SetStringField(TEXT("message"),Message);Send(M);}
void AKioskStage::StopPlayback(){Voice->Flush();if(IsValid(FallbackAudio)){FallbackAudio->Stop();FallbackAudio=nullptr;}SegmentId.Empty();DrainedAt=0;if(Character)Character->SetSpeechEnvelope(0);}
void AKioskStage::Receive(const FString& Message){
    TSharedPtr<FJsonObject> M;auto Reader=TJsonReaderFactory<>::Create(Message);
    if(!FJsonSerializer::Deserialize(Reader,M)||!M.IsValid())return;
    FString Type,IncomingSession;double IncomingTurn=-1;
    if(!M->TryGetStringField(TEXT("type"),Type)||!M->TryGetStringField(TEXT("session_id"),IncomingSession)||!M->TryGetNumberField(TEXT("turn_id"),IncomingTurn))return;
    if(Type==TEXT("hello")){
        if(!SessionId.IsEmpty())return; // Only one handshake per socket generation.
        double Protocol=0;if(!M->TryGetNumberField(TEXT("protocol"),Protocol)||Protocol!=1){ClientError(TEXT("Unsupported protocol"));return;}
        StopPlayback();SessionId=IncomingSession;Turn=static_cast<int64>(IncomingTurn);
        const TArray<TSharedPtr<FJsonValue>>* List;if(M->TryGetArrayField(TEXT("avatars"),List))Avatars=*List;
    }else{
        if(SessionId.IsEmpty()||IncomingSession!=SessionId||IncomingTurn<Turn)return;
        if(IncomingTurn>Turn){StopPlayback();Turn=static_cast<int64>(IncomingTurn);}
    }
    if(Type==TEXT("hello")||Type==TEXT("settings")){const TSharedPtr<FJsonObject>* Value;if(M->TryGetObjectField(TEXT("settings"),Value))Settings(*Value);return;}
    if(Type==TEXT("playback.stop")){StopPlayback();return;}
    if(Type==TEXT("state")){FString State;if(M->TryGetStringField(TEXT("state"),State)&&Character)Character->SetDialogueState(FName(*State));return;}
    if(Type==TEXT("gesture")){FString Name;if(M->TryGetStringField(TEXT("name"),Name)&&Character)Character->SetDialogueState(FName(*Name));return;}
    if(Type==TEXT("speech.begin")){
        StopPlayback();double Rate=0;if(!M->TryGetNumberField(TEXT("sample_rate"),Rate)||Rate!=24000){ClientError(TEXT("Expected 24000 Hz mono PCM"));return;}
        M->TryGetStringField(TEXT("segment_id"),SegmentId);Voice->BeginSegment();return;
    }
    if(Type==TEXT("audio")||Type==TEXT("speech.end")){
        FString Segment;if(!M->TryGetStringField(TEXT("segment_id"),Segment)||Segment.IsEmpty()||Segment!=SegmentId)return;
        if(Type==TEXT("speech.end")){Voice->EndSegment();return;}
        FString Encoded;TArray<uint8> PCM;if(!M->TryGetStringField(TEXT("pcm"),Encoded)||Encoded.Len()>100000||!FBase64::Decode(Encoded,PCM)||!Voice->AppendPCM(PCM)){StopPlayback();ClientError(TEXT("Invalid or excessive PCM payload"));}return;
    }
    if(Type==TEXT("error")){
        StopPlayback();FString Error;M->TryGetStringField(TEXT("message"),Error);UE_LOG(LogTemp,Warning,TEXT("Kiosk service: %s"),*Error);
        if(auto* Sound=LoadObject<USoundWave>(nullptr,TEXT("/Game/Kiosk/ServiceUnavailable.ServiceUnavailable")))FallbackAudio=UGameplayStatics::SpawnSound2D(this,Sound);
    }
}
void AKioskStage::ApplyAvatar(const FString& Id){
    if(AvatarId==Id&&Character)return;
    for(const auto& Entry:Avatars){
        auto Spec=Entry->AsObject();FString EntryId,ClassPath;
        if(!Spec.IsValid()||!Spec->TryGetStringField(TEXT("id"),EntryId)||EntryId!=Id)continue;
        if(!Spec->TryGetStringField(TEXT("actor_class"),ClassPath)||(!ClassPath.StartsWith(TEXT("/Script/HoloKiosk."))&&!ClassPath.StartsWith(TEXT("/Game/"))))break;
        UClass* Class=LoadClass<AKioskCharacter>(nullptr,*ClassPath);if(!Class)break;
        auto* Candidate=GetWorld()->SpawnActor<AKioskCharacter>(Class,FVector::ZeroVector,FRotator::ZeroRotator);
        if(!Candidate)break;FString Error;Candidate->SetActorHiddenInGame(true);
        if(!Candidate->Configure(Spec,Error,bPreviewMode)){Candidate->Destroy();ClientError(Error);return;}
        StopPlayback();if(Character)Character->Destroy();Character=Candidate;Character->SetActorHiddenInGame(false);AvatarId=Id;BaseScale=Character->GetActorScale3D().X;return;
    }
    ClientError(TEXT("Character not installed or incompatible: ")+Id);
}
void AKioskStage::Settings(const TSharedPtr<FJsonObject>& Value){
    FString Id;if(Value->TryGetStringField(TEXT("avatar_id"),Id))ApplyAvatar(Id);
    const TSharedPtr<FJsonObject>* Audio;
    if(Value->TryGetObjectField(TEXT("audio"),Audio)){FString Mode;(*Audio)->TryGetStringField(TEXT("mode"),Mode);bPushToTalk=Mode!=TEXT("hands_free");double Volume=.85;(*Audio)->TryGetNumberField(TEXT("volume"),Volume);Voice->SetVolumeMultiplier(FMath::Clamp(static_cast<float>(Volume),0.f,1.f));}
    FString Active;Value->TryGetStringField(TEXT("active_role"),Active);const TArray<TSharedPtr<FJsonValue>>* Roles;
    if(Value->TryGetArrayField(TEXT("roles"),Roles)&&Character)for(const auto& R:*Roles){auto RoleConfig=R->AsObject();FString RoleId;double Frequency=.5;if(RoleConfig.IsValid()&&RoleConfig->TryGetStringField(TEXT("id"),RoleId)&&RoleId==Active){RoleConfig->TryGetNumberField(TEXT("gesture_frequency"),Frequency);Character->SetGestureFrequency(Frequency);}}
    const TSharedPtr<FJsonObject>* Display;if(!Value->TryGetObjectField(TEXT("display"),Display))return;
    auto Number=[Display](const TCHAR* Key,double Default){double N=Default;(*Display)->TryGetNumberField(Key,N);return N;};
    const int32 Width=FMath::Clamp(static_cast<int32>(Number(TEXT("width"),1080)),480,3840),Height=FMath::Clamp(static_cast<int32>(Number(TEXT("height"),1920)),480,3840);
    bool Full=true;(*Display)->TryGetBoolField(TEXT("fullscreen"),Full);
    if(auto* User=GEngine->GetGameUserSettings()){User->SetScreenResolution(FIntPoint(Width,Height));User->SetFullscreenMode(Full?EWindowMode::WindowedFullscreen:EWindowMode::Windowed);User->SetFrameRateLimit(Number(TEXT("target_fps"),30));User->ApplySettings(false);}
    FDisplayMetrics Displays;FDisplayMetrics::RebuildDisplayMetrics(Displays);const int32 Monitor=static_cast<int32>(Number(TEXT("monitor"),0));
    if(Displays.MonitorInfo.IsValidIndex(Monitor)&&GEngine->GameViewport){auto Window=GEngine->GameViewport->GetWindow();if(Window.IsValid()){const auto& Rect=Displays.MonitorInfo[Monitor].DisplayRect;Window->MoveWindowTo(FVector2D(Rect.Left,Rect.Top));}}
    const double Limit=FMath::Min(1.0,static_cast<double>(FMath::Sqrt(2073600.0/(static_cast<double>(Width)*Height))));
    if(auto* CV=IConsoleManager::Get().FindConsoleVariable(TEXT("r.ScreenPercentage")))CV->Set(static_cast<float>(100*FMath::Min(Limit,Number(TEXT("render_scale"),.75))),ECVF_SetByCode);
    KeyLight->SetIntensity(3*Number(TEXT("brightness"),1));FillLight->SetIntensity(Number(TEXT("brightness"),1));
    if(Character){Character->SetActorLocation(FVector(0,Number(TEXT("avatar_x"),0)*100,Number(TEXT("avatar_y"),0)*100));Character->SetActorRotation(FRotator(0,Number(TEXT("avatar_yaw"),0),0));Character->SetActorScale3D(FVector(BaseScale*Number(TEXT("avatar_scale"),1)));Character->SetDisplayLOD(static_cast<int32>(Number(TEXT("forced_lod"),3))+1);}
    // Keep the whole 180 cm figure inside both portrait and landscape frames.
    const float Aspect=static_cast<float>(Width)/Height;Camera->SetRelativeLocation(FVector(FMath::Max(350.f,110.f*Aspect/FMath::Tan(FMath::DegreesToRadians(Camera->FieldOfView*.5f))),0,90));
}
void AKioskStage::Tick(float DeltaSeconds){
    Super::Tick(DeltaSeconds);const double Now=FPlatformTime::Seconds();
    if(bPreviewMode){
        if(bMotionSuite){RunMotionSuite(DeltaSeconds);return;}
        if(auto* PC=GetWorld()->GetFirstPlayerController()){
            if(PC->WasInputKeyJustPressed(EKeys::R))LoadPreview();
            const FKey Keys[]={EKeys::One,EKeys::Two,EKeys::Three,EKeys::Four,EKeys::Five,EKeys::Six,EKeys::Seven,EKeys::Eight,EKeys::Nine,EKeys::Zero,EKeys::Hyphen,EKeys::Equals};
            const FName Names[]={"idle","wave","explain","nod","bow","point","walk","turn_left","turn_right","speaking","welcome","goodbye"};
            for(int32 I=0;I<12;++I)if(PC->WasInputKeyJustPressed(Keys[I])&&Character){Character->PlayMotion(Names[I]);if(GEngine)GEngine->AddOnScreenDebugMessage(-1,3,FColor::Green,Names[I].ToString());}
            if(PC->WasInputKeyJustPressed(EKeys::SpaceBar)){if(bPreviewSpeaking){StopPlayback();bPreviewSpeaking=false;if(Character){Character->SetDialogueState("idle");Character->PlayMotion("idle");}}else PlayPreviewAudio();}
            if(PC->WasInputKeyJustPressed(EKeys::J))PreviewJaw=PreviewJaw>0?0:1;
            if(PC->WasInputKeyJustPressed(EKeys::B))PreviewBlink=PreviewBlink==1?-1:1;
            if(PC->WasInputKeyJustPressed(EKeys::Escape)){StopPlayback();bPreviewSpeaking=false;PreviewJaw=0;PreviewBlink=-1;if(Character){Character->SetDialogueState("idle");Character->PlayMotion("idle");}}
            if(bPreviewSpeaking&&Voice->IsDrained()){bPreviewSpeaking=false;if(Character){Character->SetDialogueState("idle");Character->PlayMotion("idle");}UE_LOG(LogTemp,Display,TEXT("Kiosk local audio drained; mouth returned to neutral"));}
            if(Character){Character->SetSpeechEnvelope(bPreviewSpeaking?Voice->MouthEnvelope():PreviewJaw);Character->SetBlinkOverride(PreviewBlink);}
            if(PC->IsInputKeyDown(EKeys::LeftControl)&&PC->IsInputKeyDown(EKeys::LeftShift)&&PC->WasInputKeyJustPressed(EKeys::Q))FPlatformMisc::RequestExit(false);
        }
        return;
    }
    if(!bConnected&&Now>=RetryAt)Connect();
    if(Character)Character->SetSpeechEnvelope(Voice->MouthEnvelope());
    if(!SegmentId.IsEmpty()&&Voice->IsDrained()){
        if(DrainedAt==0)DrainedAt=Now;
        if(Now-DrainedAt>=.12){auto M=MakeShared<FJsonObject>();M->SetStringField(TEXT("type"),TEXT("playback.complete"));M->SetNumberField(TEXT("turn_id"),Turn);M->SetStringField(TEXT("segment_id"),SegmentId);Send(M);SegmentId.Empty();DrainedAt=0;}
    }else DrainedAt=0;
    if(auto* PC=GetWorld()->GetFirstPlayerController()){
        if(PC->WasInputKeyJustPressed(EKeys::Escape)){StopPlayback();SendType(TEXT("interrupt"));}
        if(bPushToTalk&&PC->WasInputKeyJustPressed(EKeys::SpaceBar)){StopPlayback();auto M=MakeShared<FJsonObject>();M->SetStringField(TEXT("type"),TEXT("audio.start"));M->SetStringField(TEXT("mode"),TEXT("push_to_talk"));Send(M);}
        if(bPushToTalk&&PC->WasInputKeyJustReleased(EKeys::SpaceBar))SendType(TEXT("audio.end"));
        if(PC->WasInputKeyJustPressed(EKeys::F10))FPlatformProcess::LaunchURL(TEXT("http://127.0.0.1:8780"),nullptr,nullptr);
        if(PC->IsInputKeyDown(EKeys::LeftControl)&&PC->IsInputKeyDown(EKeys::LeftShift)&&PC->WasInputKeyJustPressed(EKeys::Q))FPlatformMisc::RequestExit(false);
    }
    FrameSamples.Add(DeltaSeconds*1000);
    if(Now-MetricsStart>=30){
        FrameSamples.Sort();double Sum=0;for(float V:FrameSamples)Sum+=V;
        auto M=MakeShared<FJsonObject>();M->SetStringField(TEXT("type"),TEXT("metrics"));M->SetNumberField(TEXT("frame_ms_mean"),Sum/FMath::Max(1,FrameSamples.Num()));M->SetNumberField(TEXT("frame_ms_p95"),FrameSamples[FMath::Clamp(FMath::CeilToInt(FrameSamples.Num()*.95f)-1,0,FrameSamples.Num()-1)]);M->SetNumberField(TEXT("sample_seconds"),Now-MetricsStart);Send(M);FrameSamples.Reset();MetricsStart=Now;
    }
}
void AKioskStage::EndPlay(const EEndPlayReason::Type Reason){
    bShuttingDown=true;++ConnectionGeneration;StopPlayback();Voice->Stop();
    if(Socket){Socket->OnMessage().Clear();Socket->OnConnected().Clear();Socket->OnClosed().Clear();Socket->OnConnectionError().Clear();Socket->Close();Socket.Reset();}
    Super::EndPlay(Reason);
}

// Reproducible real-render suite, enabled only with an isolated CharacterPreview.
void AKioskStage::RunMotionSuite(float DeltaSeconds){
    if(!Character)return;
    const FName Names[]={"idle","wave","explain","nod","bow","point","walk","turn_left","turn_right","speaking","welcome","goodbye"};
    const float Durations[]={8,4,5,3,4,4,5.6f,4,4,4,4,4};
    if(MotionSuiteIndex<0){MotionSuiteIndex=0;MotionSuiteAge=0;MotionShot=0;Character->PlayMotion(Names[0]);}
    MotionSuiteAge+=DeltaSeconds;
    const float Duration=Durations[MotionSuiteIndex];
    if(MotionShot<3&&MotionSuiteAge>=(MotionShot==0?Duration*.32f:MotionShot==1?Duration*.65f:Duration+.5f)){
        FString Directory=FPaths::ProjectSavedDir()/TEXT("ActionTests/v2-verified");
        IFileManager::Get().MakeDirectory(*Directory,true);
        const FString Stem=Directory/FString::Printf(TEXT("%02d_%s_%d"),MotionSuiteIndex,*Names[MotionSuiteIndex].ToString(),MotionShot);
        FScreenshotRequest::RequestScreenshot(Stem+TEXT(".png"),false,false);
        auto Report=MakeShared<FJsonObject>();Report->SetStringField(TEXT("requested"),Names[MotionSuiteIndex].ToString());Report->SetStringField(TEXT("active"),Character->ActiveMotion().ToString());Report->SetNumberField(TEXT("time"),Character->MotionTime());
        auto Bones=MakeShared<FJsonObject>();bool Valid=true;
        for(const FName Name:{FName("Root_M"),FName("Head_M"),FName("Wrist_L"),FName("Wrist_R"),FName("Ankle_L"),FName("Ankle_R"),FName("ToesEnd_L"),FName("ToesEnd_R")}){
            const FTransform T=Character->BoneDisplay->GetSocketTransform(Name,RTS_Component);const FVector P=T.GetTranslation();Valid=Valid&&!T.ContainsNaN();
            TArray<TSharedPtr<FJsonValue>> A;A.Add(MakeShared<FJsonValueNumber>(P.X));A.Add(MakeShared<FJsonValueNumber>(P.Y));A.Add(MakeShared<FJsonValueNumber>(P.Z));Bones->SetArrayField(Name.ToString(),A);
        }
        Report->SetBoolField(TEXT("finite"),Valid);Report->SetObjectField(TEXT("bones"),Bones);
        FString Text;auto Writer=TJsonWriterFactory<>::Create(&Text);FJsonSerializer::Serialize(Report,Writer);FFileHelper::SaveStringToFile(Text,*(Stem+TEXT(".json")));
        UE_LOG(LogTemp,Display,TEXT("MotionSuite capture %s finite=%d active=%s"),*Stem,Valid,*Character->ActiveMotion().ToString());++MotionShot;
    }
    MotionRecordAge+=DeltaSeconds;
    if(MotionRecordAge>=.1f&&!FScreenshotRequest::IsScreenshotRequested()){
        MotionRecordAge=0;
        const FString Directory=FPaths::ProjectSavedDir()/TEXT("ActionTests/v2-verified/frames")/Names[MotionSuiteIndex].ToString();
        IFileManager::Get().MakeDirectory(*Directory,true);
        FScreenshotRequest::RequestScreenshot(Directory/FString::Printf(TEXT("frame_%04d.png"),MotionFrame++),false,false);
    }
    if(MotionSuiteAge>Duration+1){
        ++MotionSuiteIndex;MotionSuiteAge=0;MotionShot=0;MotionRecordAge=0;MotionFrame=0;
        if(MotionSuiteIndex==12){bMotionSuite=false;Character->PlayMotion("idle");UE_LOG(LogTemp,Display,TEXT("MotionSuite completed 12 clips"));if(FParse::Param(FCommandLine::Get(),TEXT("MotionSuiteExit")))FPlatformMisc::RequestExit(false);return;}
        Character->PlayMotion(Names[MotionSuiteIndex]);
    }
}
