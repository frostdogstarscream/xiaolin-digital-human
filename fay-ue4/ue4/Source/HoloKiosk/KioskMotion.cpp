#include "KioskMotion.h"
#include "Engine/SkeletalMesh.h"

bool FKioskMotion::Load(const TSharedPtr<FJsonObject>& Spec,USkeletalMesh* Mesh,FString& Error){
    Clips.Empty();Previous.Empty();Last.Empty();Active=NAME_None;
    const TSharedPtr<FJsonObject>* Library;
    if(!Spec->TryGetObjectField(TEXT("motion_clips"),Library))return true;
    Reference=Mesh->GetRefSkeleton().GetRefBonePose();
    if((*Library)->Values.Num()>16){Error=TEXT("Too many motion clips");return false;}
    for(const auto& Item:(*Library)->Values){
        const TSharedPtr<FJsonObject>* Obj;FKioskMotionClip Clip;double Duration=0;
        if(!Item.Value->TryGetObject(Obj)||!(*Obj)->TryGetNumberField(TEXT("duration"),Duration)||!FMath::IsFinite(Duration)||Duration<.5||Duration>30||!(*Obj)->TryGetBoolField(TEXT("loop"),Clip.Loop)){Error=TEXT("Invalid clip duration/loop");return false;}
        Clip.Duration=Duration;
        const TSharedPtr<FJsonObject>* Tracks;
        if(!(*Obj)->TryGetObjectField(TEXT("tracks"),Tracks)||(*Tracks)->Values.Num()<1||(*Tracks)->Values.Num()>32){Error=TEXT("Invalid motion tracks");return false;}
        for(const auto& TrackItem:(*Tracks)->Values){
            FKioskMotionTrack Track;Track.Bone=Mesh->GetRefSkeleton().FindBoneIndex(FName(*TrackItem.Key));
            const TArray<TSharedPtr<FJsonValue>>* Keys;
            if(Track.Bone==INDEX_NONE||!TrackItem.Value->TryGetArray(Keys)||Keys->Num()<2||Keys->Num()>512){Error=TEXT("Invalid motion bone/keys");return false;}
            for(const auto& Value:*Keys){
                const TSharedPtr<FJsonObject>* Key;FKioskMotionKey K;double KeyTime=0;
                if(!Value->TryGetObject(Key)||!(*Key)->TryGetNumberField(TEXT("time"),KeyTime)||!FMath::IsFinite(KeyTime)||KeyTime<0||KeyTime>Duration||(Track.Keys.Num()>0&&KeyTime<=Track.Keys.Last().Time)){Error=TEXT("Invalid key time");return false;}
                K.Time=KeyTime;
                auto Array=[&](const TCHAR* Name,int32 Count,double Limit,TArray<double>& Out){
                    const TArray<TSharedPtr<FJsonValue>>* A;if(!(*Key)->TryGetArrayField(Name,A)||A->Num()!=Count)return false;
                    for(const auto& V:*A){double N;if(!V->TryGetNumber(N)||!FMath::IsFinite(N)||FMath::Abs(N)>Limit)return false;Out.Add(N);}return true;
                };
                TArray<double> Q,T;
                if(!Array(TEXT("rotation"),4,1.001,Q)||!Array(TEXT("translation"),3,60,T)){Error=TEXT("Invalid key transform");return false;}
                K.Rotation=FQuat(Q[0],Q[1],Q[2],Q[3]);K.Translation=FVector(T[0],T[1],T[2]);
                if(FMath::Abs(K.Rotation.SizeSquared()-1)>.002){Error=TEXT("Motion quaternion is not normalized");return false;}
                K.Rotation.Normalize();Track.Keys.Add(K);
            }
            if(Track.Keys[0].Time!=0||FMath::Abs(Track.Keys.Last().Time-Duration)>.001){Error=TEXT("Motion track must span clip");return false;}
            Clip.Tracks.Add(MoveTemp(Track));
        }
        Clips.Add(FName(*Item.Key),MoveTemp(Clip));
    }
    if(!Clips.Contains("idle")){Error=TEXT("Motion library needs idle");return false;}
    Play("idle");return true;
}
bool FKioskMotion::Play(FName Name){
    if(!Clips.Contains(Name))return false;
    Previous=Last;Active=Name;Time=0;Blend=0;
    UE_LOG(LogTemp,Display,TEXT("Kiosk motion started: %s"),*Name.ToString());return true;
}
void FKioskMotion::Apply(float DeltaSeconds,TArray<FTransform>& Pose){
    auto* Clip=Clips.Find(Active);if(!Clip)return;
    Time+=DeltaSeconds;Blend=FMath::Min(1.f,Blend+DeltaSeconds/.35f);
    if(Time>Clip->Duration){
        if(Clip->Loop)Time=FMath::Fmod(Time,Clip->Duration);
        else{UE_LOG(LogTemp,Display,TEXT("Kiosk motion completed: %s"),*Active.ToString());Play(Clips.Contains(ReturnName)?ReturnName:FName("idle"));Clip=Clips.Find(Active);}
    }
    for(const auto& Track:Clip->Tracks){
        if(!Pose.IsValidIndex(Track.Bone))continue;
        int32 I=0;while(I+1<Track.Keys.Num()-1&&Track.Keys[I+1].Time<Time)++I;
        const auto& A=Track.Keys[I];const auto& B=Track.Keys[I+1];
        const float Alpha=FMath::Clamp((Time-A.Time)/(B.Time-A.Time),0.f,1.f);
        auto& T=Pose[Track.Bone];T=Reference[Track.Bone];
        T.SetRotation((T.GetRotation()*FQuat::Slerp(A.Rotation,B.Rotation,Alpha)).GetNormalized());
        T.AddToTranslation(FMath::Lerp(A.Translation,B.Translation,Alpha));
    }
    if(Previous.Num()==Pose.Num()&&Blend<1){const float Weight=Blend*Blend*(3-2*Blend);for(int32 I=0;I<Pose.Num();++I){FTransform T;T.Blend(Previous[I],Pose[I],Weight);Pose[I]=T;}}
    Last=Pose;
}
