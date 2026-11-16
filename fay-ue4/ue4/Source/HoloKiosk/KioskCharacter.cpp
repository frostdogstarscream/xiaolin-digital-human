#include "KioskCharacter.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/PoseableMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Animation/AnimationAsset.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "UObject/ConstructorHelpers.h"

AKioskCharacter::AKioskCharacter() {
    PrimaryActorTick.bCanEverTick=true;
    RootComponent=CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
    Body=CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Body")); Body->SetupAttachment(RootComponent);
    Body->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    BoneDisplay=CreateDefaultSubobject<UPoseableMeshComponent>(TEXT("BoneDisplay"));BoneDisplay->SetupAttachment(RootComponent);
    BoneDisplay->SetCollisionEnabled(ECollisionEnabled::NoCollision);BoneDisplay->SetVisibility(false);
    // Copy only after the source animation has evaluated, then refresh in this tick.
    PrimaryActorTick.TickGroup=TG_PostUpdateWork;
    AddTickPrerequisiteComponent(Body);
    static ConstructorHelpers::FObjectFinder<UStaticMesh> Sphere(TEXT("/Engine/BasicShapes/Sphere.Sphere"));
    static ConstructorHelpers::FObjectFinder<UStaticMesh> Cube(TEXT("/Engine/BasicShapes/Cube.Cube"));
    const FVector Positions[]={FVector(0,0,158),FVector(0,0,111),FVector(0,-14,45),FVector(0,14,45),FVector(0,-33,111),FVector(0,33,111)};
    const FVector Sizes[]={FVector(.28f),FVector(.28f,.46f,.60f),FVector(.16f,.17f,.83f),FVector(.16f,.17f,.83f),FVector(.13f,.13f,.62f),FVector(.13f,.13f,.62f)};
    for(int32 I=0;I<6;++I){auto* Mesh=CreateDefaultSubobject<UStaticMeshComponent>(*FString::Printf(TEXT("Calibration%d"),I));Mesh->SetupAttachment(RootComponent);Mesh->SetStaticMesh(I==0?Sphere.Object:Cube.Object);Mesh->SetRelativeLocation(Positions[I]);Mesh->SetRelativeScale3D(Sizes[I]);Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);Calibration.Add(Mesh);}
}
bool AKioskCharacter::Configure(const TSharedPtr<FJsonObject>& Spec,FString& Error,bool bPreview) {
    Morphs.Empty();Animations.Empty();FaceBones.Empty();BodyBones.Empty();bBoneFace=false;
    FString Driver=TEXT("morph"),Motion=TEXT("animations");
    Spec->TryGetStringField(TEXT("face_driver"),Driver);Spec->TryGetStringField(TEXT("motion_mode"),Motion);
    if(Driver!=TEXT("morph") && Driver!=TEXT("bones")){Error=TEXT("Unknown face driver");return false;}
    if(Motion!=TEXT("animations") && !(bPreview && (Motion==TEXT("reference_pose")||Motion==TEXT("procedural")))){Error=TEXT("Procedural/reference pose is preview-only");return false;}
    FString Kind; Spec->TryGetStringField(TEXT("kind"),Kind); bDiagnostic=Kind==TEXT("diagnostic");
    FString Path;
    if(!bDiagnostic){
        if(!Spec->TryGetStringField(TEXT("skeletal_mesh"),Path) || !Path.StartsWith(TEXT("/Game/"))){Error=TEXT("Missing cooked skeletal mesh path");return false;}
        auto* Mesh=LoadObject<USkeletalMesh>(nullptr,*Path);
        if(!Mesh){Error=TEXT("Skeletal mesh is not available in this build: ")+Path;return false;}
        const TSharedPtr<FJsonObject>* Map;
        bBoneFace=Driver==TEXT("bones");
        if(bBoneFace){
            if(!Spec->TryGetObjectField(TEXT("face_bones"),Map)){Error=TEXT("Missing face_bones");return false;}
            TSet<int32> Used;
            for(const FString Key:{FString("jaw_open"),FString("blink_left"),FString("blink_right")}){
                const TArray<TSharedPtr<FJsonValue>>* Bindings;
                if(!(*Map)->TryGetArrayField(Key,Bindings) || Bindings->Num()<1 || Bindings->Num()>64){Error=TEXT("Missing/invalid bone channel: ")+Key;return false;}
                for(const auto& Value:*Bindings){
                    const TSharedPtr<FJsonObject>* Binding;FString Name;
                    if(!Value->TryGetObject(Binding) || !(*Binding)->TryGetStringField(TEXT("bone"),Name)){Error=TEXT("Invalid bone binding");return false;}
                    FKioskFaceBone B;B.Channel=FName(*Key);B.Index=Mesh->GetRefSkeleton().FindBoneIndex(FName(*Name));
                    if(B.Index==INDEX_NONE || Used.Contains(B.Index)){Error=TEXT("Missing/duplicate bone: ")+Name;return false;}
                    auto Vector=[&](const TCHAR* Field,double Limit,FVector& Out){
                        const TArray<TSharedPtr<FJsonValue>>* A;
                        if(!(*Binding)->TryGetArrayField(Field,A)||A->Num()!=3)return false;
                        double N[3];for(int I=0;I<3;++I)if(!(*A)[I]->TryGetNumber(N[I])||!FMath::IsFinite(N[I])||FMath::Abs(N[I])>Limit)return false;
                        Out=FVector(N[0],N[1],N[2]);return true;
                    };
                    FVector Rotation;
                    if(!Vector(TEXT("rotation"),45,Rotation)||!Vector(TEXT("translation"),5,B.Translation)){Error=TEXT("Invalid face transform");return false;}
                    B.Rotation=FRotator(Rotation.X,Rotation.Y,Rotation.Z);Used.Add(B.Index);FaceBones.Add(B);
                }
            }
        }else{
            if(Spec->TryGetObjectField(TEXT("morphs"),Map)) for(const auto& Item:(*Map)->Values){Morphs.Add(FName(*Item.Key),FName(*Item.Value->AsString()));}
            for(const FName Key:{FName("jaw_open"),FName("blink_left"),FName("blink_right")}){
                const FName* M=Morphs.Find(Key);
                if(!M || !Mesh->FindMorphTarget(*M)){Error=TEXT("Missing required morph: ")+Key.ToString();return false;}
            }
        }
        Body->SetSkeletalMesh(Mesh);
        if(Motion==TEXT("procedural")){
            const TArray<TSharedPtr<FJsonValue>>* List=nullptr;
            if(!bBoneFace||!Spec->TryGetArrayField(TEXT("body_bones"),List)||List->Num()<1||List->Num()>32){Error=TEXT("Procedural preview needs body_bones and bone face driver");return false;}
            TSet<int32> Used;
            for(const auto& Value:*List){
                const TSharedPtr<FJsonObject>* Binding;FString Name;
                if(!Value->TryGetObject(Binding)||!(*Binding)->TryGetStringField(TEXT("bone"),Name)){Error=TEXT("Invalid body bone");return false;}
                FKioskBodyBone B;B.Index=Mesh->GetRefSkeleton().FindBoneIndex(FName(*Name));
                if(B.Index==INDEX_NONE||Used.Contains(B.Index)){Error=TEXT("Missing/duplicate body bone: ")+Name;return false;}
                for(const auto& Face:FaceBones)if(Face.Index==B.Index){Error=TEXT("Body and face bone overlap");return false;}
                auto Rotation=[&](const TCHAR* Field,double Limit,FRotator& Out){
                    const TArray<TSharedPtr<FJsonValue>>* A;
                    if(!(*Binding)->TryGetArrayField(Field,A)||A->Num()!=3)return false;
                    double N[3];for(int I=0;I<3;++I)if(!(*A)[I]->TryGetNumber(N[I])||!FMath::IsFinite(N[I])||FMath::Abs(N[I])>Limit)return false;
                    Out=FRotator(N[0],N[1],N[2]);return true;
                };
                double Phase=0;
                if(!Rotation(TEXT("rotation"),120,B.Base)||!Rotation(TEXT("idle"),3,B.Idle)||!Rotation(TEXT("speaking"),8,B.Talk)||!(*Binding)->TryGetNumberField(TEXT("phase"),Phase)||!FMath::IsFinite(Phase)||FMath::Abs(Phase)>10){Error=TEXT("Invalid body pose values");return false;}
                B.Phase=Phase;Used.Add(B.Index);BodyBones.Add(B);
            }
        }
        if(bBoneFace){
            BoneDisplay->SetSkeletalMesh(Mesh);
            Body->VisibilityBasedAnimTickOption=EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
            Body->bEnableUpdateRateOptimizations=false;
            Body->SetForcedLOD(1); // Keep source face bones available for pose copying.
        }
        if(Spec->TryGetObjectField(TEXT("animations"),Map)) for(const auto& Item:(*Map)->Values){
            const FString AnimPath=Item.Value->AsString();
            if(!AnimPath.StartsWith(TEXT("/Game/"))){Error=TEXT("Invalid animation path");return false;}
            auto* Anim=LoadObject<UAnimationAsset>(nullptr,*AnimPath);
            if(!Anim || Anim->GetSkeleton()!=Mesh->GetSkeleton()){Error=TEXT("Animation must use this mesh's skeleton: ")+AnimPath;return false;}
            Animations.Add(FName(*Item.Key),Anim);
        }
        if(Motion==TEXT("animations") && (!Animations.Contains("idle") || !Animations.Contains("speaking"))){Error=TEXT("Idle and speaking animations are required");return false;}
        if(Motion!=TEXT("animations") && Animations.Num()){Error=TEXT("Procedural/reference preview cannot contain animations");return false;}
    }
    if(Spec->HasField(TEXT("motion_clips")) && (!bPreview || Motion!=TEXT("procedural"))){Error=TEXT("Keyframe library is preview-only");return false;}
    if(!this->MotionPlayer.Load(Spec,Body->SkeletalMesh,Error))return false;
    for(const auto& Clip:this->MotionPlayer.Clips)for(const auto& Track:Clip.Value.Tracks)for(const auto& Face:FaceBones)if(Track.Bone==Face.Index){Error=TEXT("Motion track overlaps face driver");return false;}
    double Yaw=0,Scale=1;Spec->TryGetNumberField(TEXT("mesh_yaw"),Yaw);Spec->TryGetNumberField(TEXT("mesh_scale"),Scale);
    if(!FMath::IsFinite(Yaw)||!FMath::IsFinite(Scale)||FMath::Abs(Yaw)>180||Scale<=0||Scale>100){Error=TEXT("Invalid mesh transform");return false;}
    Body->SetRelativeRotation(FRotator(0,Yaw,0));Body->SetRelativeScale3D(FVector(Scale));
    BoneDisplay->SetRelativeTransform(Body->GetRelativeTransform());
    BoneDisplay->SetVisibility(!bDiagnostic && bBoneFace);Body->SetVisibility(!bDiagnostic && !bBoneFace);
    for(auto* M:Calibration) M->SetVisibility(bDiagnostic);
    if(bDiagnostic)SetActorScale3D(FVector(Scale));
    SetDialogueState("idle");return true;
}
void AKioskCharacter::SetDialogueState(FName State){
    if(DialogueState==State && Body->IsPlaying())return;
    DialogueState=State;
    MotionPlayer.ReturnName=State=="speaking"?FName("speaking"):FName("idle");
    FName Key=State;
    if(State=="asleep")Key="idle";
    if(State=="thinking")Key="listening";
    UAnimationAsset** Anim=Animations.Find(Key);if(!Anim)Anim=Animations.Find("idle");
    if(Anim)Body->PlayAnimation(*Anim,State!="welcome" && State!="point");
    OnDialogueState(State);
}
void AKioskCharacter::SetDisplayLOD(int32 LOD){
    if(bBoneFace){Body->SetForcedLOD(1);BoneDisplay->SetForcedLOD(LOD);}else Body->SetForcedLOD(LOD);
}
void AKioskCharacter::SetSpeechEnvelope(float Value){TargetMouth=FMath::Clamp(Value,0.f,1.f);if(TargetMouth==0)MouthOpen=0;}
void AKioskCharacter::Tick(float DeltaSeconds){
    Super::Tick(DeltaSeconds);Age+=DeltaSeconds;
    MouthOpen=FMath::FInterpTo(MouthOpen,TargetMouth,DeltaSeconds,18.f);
    if(Age>=NextBlink){BlinkStart=Age;NextBlink=Age+FMath::FRandRange(2.8f,5.4f);}
    const float BlinkAge=Age-BlinkStart;
    const float Blink=BlinkOverride>=0?BlinkOverride:(BlinkAge>=0 && BlinkAge<.18f?FMath::Sin(BlinkAge/.18f*PI):0);
    if(bBoneFace){
        BoneDisplay->CopyPoseFromSkeletalComponent(Body);
        TalkBlend=FMath::FInterpTo(TalkBlend,DialogueState=="speaking"?1.f:0.f,DeltaSeconds,3.f);
        for(const auto& B:BodyBones)if(BoneDisplay->BoneSpaceTransforms.IsValidIndex(B.Index)){
            const float Idle=FMath::Sin(Age*1.25f+B.Phase),Talk=FMath::Sin(Age*2.2f+B.Phase)*TalkBlend*GestureFrequency;
            const FRotator Offset=B.Base+B.Idle*Idle+B.Talk*Talk;
            auto& T=BoneDisplay->BoneSpaceTransforms[B.Index];T.SetRotation((T.GetRotation()*Offset.Quaternion()).GetNormalized());
        }
        MotionPlayer.Apply(DeltaSeconds,BoneDisplay->BoneSpaceTransforms);
        // Deltas are relative to the freshly evaluated local pose, never cumulative.
        // Refresh recalculates descendants, including teeth and lips under the jaw.
        for(const auto& B:FaceBones)if(BoneDisplay->BoneSpaceTransforms.IsValidIndex(B.Index)){
            const float Weight=B.Channel=="jaw_open"?MouthOpen:Blink;
            auto& Transform=BoneDisplay->BoneSpaceTransforms[B.Index];
            const FQuat Delta=FQuat::Slerp(FQuat::Identity,B.Rotation.Quaternion(),Weight);
            Transform.SetRotation((Transform.GetRotation()*Delta).GetNormalized());
            Transform.AddToTranslation(Transform.GetRotation().RotateVector(B.Translation*Weight));
        }
        BoneDisplay->MarkRefreshTransformDirty();BoneDisplay->RefreshBoneTransforms(nullptr);
    }
    if(const FName* M=Morphs.Find("jaw_open"))Body->SetMorphTarget(*M,MouthOpen);
    if(const FName* M=Morphs.Find("blink_left"))Body->SetMorphTarget(*M,Blink);
    if(const FName* M=Morphs.Find("blink_right"))Body->SetMorphTarget(*M,Blink);
    // Optional artist-authored smile; precise phoneme visemes can be supplied by
    // a Blueprint override. Amplitude-driven jaw opening is the baseline only.
    if(const FName* M=Morphs.Find("smile"))Body->SetMorphTarget(*M,DialogueState=="welcome"?.35f:.08f);
    if(bDiagnostic && Calibration.Num()==6){Calibration[0]->SetRelativeScale3D(FVector(.28f,.28f,.28f+MouthOpen*.025f));Calibration[5]->SetRelativeRotation(FRotator(0,0,DialogueState=="speaking"?FMath::Sin(Age*2)*8*GestureFrequency:0));}
    OnSpeechEnvelope(MouthOpen);
}
