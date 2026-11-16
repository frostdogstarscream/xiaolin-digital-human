#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "GameFramework/GameModeBase.h"
#include "Dom/JsonObject.h"
#include "KioskStage.generated.h"
class AKioskCharacter;
class UKioskPcmSynth;
class UCameraComponent;
class UDirectionalLightComponent;
class UAudioComponent;
class IWebSocket;

UCLASS()
class HOLOKIOSK_API AKioskStage : public AActor {
    GENERATED_BODY()
public:
    AKioskStage();
    virtual void BeginPlay() override;
    virtual void Tick(float DeltaSeconds) override;
    virtual void EndPlay(const EEndPlayReason::Type Reason) override;
private:
    UPROPERTY() UKioskPcmSynth* Voice;
    UPROPERTY() UCameraComponent* Camera;
    UPROPERTY() UDirectionalLightComponent* KeyLight;
    UPROPERTY() UDirectionalLightComponent* FillLight;
    UPROPERTY() AKioskCharacter* Character;
    UPROPERTY() UAudioComponent* FallbackAudio;
    TSharedPtr<IWebSocket> Socket;
    TArray<TSharedPtr<FJsonValue>> Avatars;
    FString SessionId, SegmentId, AvatarId;
    int64 Turn=-1;
    uint64 ConnectionGeneration=0;
    double RetryAt=0,DrainedAt=0,MetricsStart=0;
    TArray<float> FrameSamples;
    bool bConnected=false,bShuttingDown=false,bPushToTalk=true;
    bool bPreviewMode=false;
    FString PreviewPath;
    FString PreviewAudioPath;
    float PreviewJaw=0,PreviewBlink=-1;
    bool bPreviewSpeaking=false;
    bool bMotionSuite=false;
    int32 MotionSuiteIndex=-1,MotionShot=0;
    float MotionSuiteAge=0,MotionRecordAge=0;
    int32 MotionFrame=0;
    void RunMotionSuite(float DeltaSeconds);
    float BaseScale=1;
    void Connect();
    void Receive(const FString& Message);
    void Disconnected();
    void Send(const TSharedRef<FJsonObject>& Message);
    void SendType(const FString& Type);
    void StopPlayback();
    void Settings(const TSharedPtr<FJsonObject>& Value);
    void ClientError(const FString& Message);
    void ApplyAvatar(const FString& Id);
    void LoadPreview();
    void PlayPreviewAudio();
};

UCLASS()
class HOLOKIOSK_API AKioskGameMode : public AGameModeBase {
    GENERATED_BODY()
public:
    AKioskGameMode();
    virtual void BeginPlay() override;
};
