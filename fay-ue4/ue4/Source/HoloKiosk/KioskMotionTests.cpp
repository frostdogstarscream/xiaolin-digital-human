#if WITH_DEV_AUTOMATION_TESTS
#include "KioskMotion.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Engine/SkeletalMesh.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FKioskMotionRegression,"HoloKiosk.Motion.TransitionsAndRecovery",EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FKioskMotionRegression::RunTest(const FString& Parameters){
    FString Text;TSharedPtr<FJsonObject> Spec;
    if(!FFileHelper::LoadFileToString(Text,*(FPaths::ProjectDir()/TEXT("../assets/girl008-actions-preview-v2.json")))){AddError(TEXT("Missing authored library"));return false;}
    auto Reader=TJsonReaderFactory<>::Create(Text);
    if(!FJsonSerializer::Deserialize(Reader,Spec)){AddError(TEXT("Invalid authored JSON"));return false;}
    auto* Mesh=LoadObject<USkeletalMesh>(nullptr,*Spec->GetStringField(TEXT("skeletal_mesh")));
    if(!Mesh){AddError(TEXT("Real imported mesh was not loaded"));return false;}
    FKioskMotion Motion;FString Error;
    if(!Motion.Load(Spec,Mesh,Error)){AddError(Error);return false;}
    const auto Reference=Mesh->GetRefSkeleton().GetRefBonePose();auto Pose=Reference;
    auto Step=[&](float Delta){Pose=Reference;Motion.Apply(Delta,Pose);};
    TestEqual(TEXT("Authored entry count"),Motion.Clips.Num(),12);
    for(FName Name:{FName("wave"),FName("bow"),FName("point"),FName("turn_left")}){
        TestTrue(TEXT("Start gesture"),Motion.Play(Name));
        for(int32 I=0;I<50;++I)Step(1.f/60);
        const auto Before=Pose;
        TestTrue(TEXT("Interrupt with nod"),Motion.Play("nod"));Step(0);
        for(int32 I=0;I<Pose.Num();++I)if(!Pose[I].Equals(Before[I],.0001f)){AddError(TEXT("Pose jumped at interruption"));return false;}
        for(int32 I=0;I<240;++I)Step(1.f/60);
        TestEqual(TEXT("One-shot returned to idle"),Motion.Active,FName("idle"));
    }
    Motion.ReturnName="speaking";Motion.Play("wave");
    for(int32 I=0;I<270;++I)Step(1.f/60);
    TestEqual(TEXT("Gesture during speech resumes speaking"),Motion.Active,FName("speaking"));
    const FName Before=Motion.Active;TestFalse(TEXT("Unknown action rejected"),Motion.Play("missing_action"));TestEqual(TEXT("Unknown action preserves state"),Motion.Active,Before);
    Motion.ReturnName="idle";Motion.Play("walk");
    for(int32 I=0;I<1800;++I){
        Step(1.f/60);
        for(int32 J=0;J<Pose.Num();++J){
            if(Pose[J].ContainsNaN()||!Pose[J].IsRotationNormalized()){AddError(TEXT("Invalid pose after repeated walk loops"));return false;}
            if(Mesh->GetRefSkeleton().GetBoneName(J)!="Root_M"&&!Pose[J].GetTranslation().Equals(Reference[J].GetTranslation(),.0001f)){AddError(TEXT("Bone length changed"));return false;}
        }
    }
    TestEqual(TEXT("Walk stays looping"),Motion.Active,FName("walk"));
    Motion.Play("idle");for(int32 I=0;I<60;++I)Step(1.f/60);
    TestTrue(TEXT("Reset restores root without accumulated displacement"),Pose[Mesh->GetRefSkeleton().FindBoneIndex("Root_M")].GetTranslation().Equals(Reference[Mesh->GetRefSkeleton().FindBoneIndex("Root_M")].GetTranslation(),.0001f));
    return true;
}
#endif
