#pragma once
#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
class USkeletalMesh;
struct FKioskMotionKey { float Time=0; FQuat Rotation=FQuat::Identity; FVector Translation=FVector::ZeroVector; };
struct FKioskMotionTrack { int32 Bone=INDEX_NONE; TArray<FKioskMotionKey> Keys; };
struct FKioskMotionClip { float Duration=0; bool Loop=false; TArray<FKioskMotionTrack> Tracks; };
// Isolated preview keyframes, relative to the imported reference pose.
struct FKioskMotion {
    TMap<FName,FKioskMotionClip> Clips;
    TArray<FTransform> Reference,Previous,Last;
    FName Active=NAME_None;
    FName ReturnName="idle";
    float Time=0,Blend=1;
    bool Load(const TSharedPtr<FJsonObject>& Spec,USkeletalMesh* Mesh,FString& Error);
    bool Play(FName Name);
    void Apply(float DeltaSeconds,TArray<FTransform>& Pose);
};
