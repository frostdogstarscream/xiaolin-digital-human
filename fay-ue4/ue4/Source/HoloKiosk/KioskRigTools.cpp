#include "KioskRigTools.h"
#include "Engine/SkeletalMesh.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"

FString UKioskRigTools::ReferenceRigJson(USkeletalMesh* Mesh){
    if(!Mesh)return TEXT("");
    const auto& Ref=Mesh->GetRefSkeleton();
    const auto& Local=Ref.GetRefBonePose();
    TArray<FTransform> Component;Component.SetNum(Local.Num());
    TArray<TSharedPtr<FJsonValue>> Bones;
    for(int32 I=0;I<Local.Num();++I){
        const int32 Parent=Ref.GetParentIndex(I);
        Component[I]=Parent==INDEX_NONE?Local[I]:Local[I]*Component[Parent];
        auto B=MakeShared<FJsonObject>();
        B->SetStringField(TEXT("name"),Ref.GetBoneName(I).ToString());
        B->SetStringField(TEXT("parent"),Parent==INDEX_NONE?TEXT(""):Ref.GetBoneName(Parent).ToString());
        auto Vec=[](const FVector& V){TArray<TSharedPtr<FJsonValue>> A;A.Add(MakeShared<FJsonValueNumber>(V.X));A.Add(MakeShared<FJsonValueNumber>(V.Y));A.Add(MakeShared<FJsonValueNumber>(V.Z));return A;};
        auto Quat=[](const FQuat& Q){TArray<TSharedPtr<FJsonValue>> A;A.Add(MakeShared<FJsonValueNumber>(Q.X));A.Add(MakeShared<FJsonValueNumber>(Q.Y));A.Add(MakeShared<FJsonValueNumber>(Q.Z));A.Add(MakeShared<FJsonValueNumber>(Q.W));return A;};
        B->SetArrayField(TEXT("position"),Vec(Component[I].GetTranslation()));
        B->SetArrayField(TEXT("rotation"),Quat(Component[I].GetRotation()));
        B->SetArrayField(TEXT("local_position"),Vec(Local[I].GetTranslation()));
        B->SetArrayField(TEXT("local_rotation"),Quat(Local[I].GetRotation()));
        Bones.Add(MakeShared<FJsonValueObject>(B));
    }
    auto Result=MakeShared<FJsonObject>();Result->SetStringField(TEXT("mesh"),Mesh->GetPathName());Result->SetArrayField(TEXT("bones"),Bones);
    FString Text;auto Writer=TJsonWriterFactory<>::Create(&Text);FJsonSerializer::Serialize(Result,Writer);return Text;
}
