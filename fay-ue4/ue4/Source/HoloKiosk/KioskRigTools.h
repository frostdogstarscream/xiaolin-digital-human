#pragma once
#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "KioskRigTools.generated.h"
class USkeletalMesh;

UCLASS()
class HOLOKIOSK_API UKioskRigTools : public UBlueprintFunctionLibrary {
    GENERATED_BODY()
public:
    // Reads bind transforms directly; does not need a world, renderer or animation tick.
    UFUNCTION(BlueprintCallable,Category="Kiosk|Calibration")
    static FString ReferenceRigJson(USkeletalMesh* Mesh);
};
