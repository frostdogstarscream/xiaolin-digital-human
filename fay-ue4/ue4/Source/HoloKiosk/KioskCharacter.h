#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "Dom/JsonObject.h"
#include "KioskMotion.h"
#include "KioskCharacter.generated.h"
class USkeletalMeshComponent;
class UStaticMeshComponent;
class UAnimationAsset;
class UPoseableMeshComponent;

struct FKioskFaceBone {
    FName Channel;
    int32 Index=INDEX_NONE;
    FRotator Rotation=FRotator::ZeroRotator;
    FVector Translation=FVector::ZeroVector;
};
struct FKioskBodyBone {
    int32 Index=INDEX_NONE;
    FRotator Base=FRotator::ZeroRotator,Idle=FRotator::ZeroRotator,Talk=FRotator::ZeroRotator;
    float Phase=0;
};

// The same interface can be subclassed by a Blueprint for custom Maya rigs.
UCLASS(Blueprintable)
class HOLOKIOSK_API AKioskCharacter : public AActor {
    GENERATED_BODY()
public:
    AKioskCharacter();
    virtual void Tick(float DeltaSeconds) override;
    bool Configure(const TSharedPtr<FJsonObject>& Spec,FString& Error,bool bPreview=false);
    void SetDisplayLOD(int32 LOD);
    UFUNCTION(BlueprintCallable,Category="Kiosk") bool PlayMotion(FName Name) { return MotionPlayer.Play(Name); }
    FName ActiveMotion() const { return MotionPlayer.Active; }
    float MotionTime() const { return MotionPlayer.Time; }
    // Negative values restore automatic blinking; exposed for local calibration.
    UFUNCTION(BlueprintCallable,Category="Kiosk") void SetBlinkOverride(float Value) { BlinkOverride=FMath::Clamp(Value,-1.f,1.f); }
    void SetDialogueState(FName State);
    void SetSpeechEnvelope(float Value);
    void SetGestureFrequency(float Value) { GestureFrequency=FMath::Clamp(Value,0.f,1.f); }
    UFUNCTION(BlueprintImplementableEvent,Category="Kiosk") void OnDialogueState(FName State);
    UFUNCTION(BlueprintImplementableEvent,Category="Kiosk") void OnSpeechEnvelope(float Value);
    UPROPERTY(VisibleAnywhere,BlueprintReadOnly,Category="Kiosk") USkeletalMeshComponent* Body;
    UPROPERTY(VisibleAnywhere,BlueprintReadOnly,Category="Kiosk") UPoseableMeshComponent* BoneDisplay;
    UPROPERTY(BlueprintReadOnly,Category="Kiosk") float MouthOpen=0;
    UPROPERTY(BlueprintReadOnly,Category="Kiosk") FName DialogueState="idle";
private:
    UPROPERTY() TArray<UStaticMeshComponent*> Calibration;
    UPROPERTY() TMap<FName,UAnimationAsset*> Animations;
    TMap<FName,FName> Morphs;
    TArray<FKioskFaceBone> FaceBones;
    TArray<FKioskBodyBone> BodyBones;
    FKioskMotion MotionPlayer;
    float TalkBlend=0;
    bool bBoneFace=false;
    float BlinkOverride=-1;
    float Age=0,NextBlink=3,BlinkStart=-10,TargetMouth=0,GestureFrequency=0.5;
    bool bDiagnostic=true;
};
