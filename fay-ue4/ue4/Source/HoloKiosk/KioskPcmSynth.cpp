#include "KioskPcmSynth.h"
#include "Misc/ScopeLock.h"

UKioskPcmSynth::UKioskPcmSynth(const FObjectInitializer& ObjectInitializer) : Super(ObjectInitializer) { NumChannels = 1; bAutoActivate = false; }
bool UKioskPcmSynth::Init(int32& SampleRate) { OutputRate = SampleRate; NumChannels = 1; return true; }
void UKioskPcmSynth::BeginSegment() { Flush(); }
void UKioskPcmSynth::Flush() { FScopeLock L(&Guard); Samples.Reset(); Position=0; bInputEnded=false; Envelope=0; }
bool UKioskPcmSynth::AppendPCM(const TArray<uint8>& PCM) {
    FScopeLock L(&Guard);
    if (PCM.Num()%2 || bInputEnded || Samples.Num()+PCM.Num()/2>24000*180) return false;
    for(int32 I=0;I<PCM.Num();I+=2) {
        const int16 V=static_cast<int16>(static_cast<uint16>(PCM[I]) | (static_cast<uint16>(PCM[I+1])<<8));
        Samples.Add(V/32768.0f);
    }
    return true;
}
void UKioskPcmSynth::EndSegment() { FScopeLock L(&Guard); bInputEnded=true; }
bool UKioskPcmSynth::IsDrained() const { FScopeLock L(&Guard); return bInputEnded && Position>=Samples.Num(); }
float UKioskPcmSynth::MouthEnvelope() const { FScopeLock L(&Guard); return Envelope; }
int32 UKioskPcmSynth::OnGenerateAudio(float* OutAudio,int32 NumSamples) {
    FScopeLock L(&Guard);
    double Energy=0;
    const double Step=24000.0/FMath::Max(1,OutputRate);
    for(int32 I=0;I<NumSamples;++I) {
        float V=0;
        const int32 Index=static_cast<int32>(Position);
        if(Index<Samples.Num() && (Index+1<Samples.Num() || bInputEnded)) {
            V=FMath::Lerp(Samples[Index],Samples[FMath::Min(Index+1,Samples.Num()-1)],static_cast<float>(Position-Index));
            Position+=Step;
        }
        OutAudio[I]=V; Energy+=V*V;
    }
    Envelope=FMath::Clamp(static_cast<float>(FMath::Sqrt(Energy/FMath::Max(NumSamples,1)))*6.f,0.f,1.f);
    const int32 Consumed=FMath::Min(static_cast<int32>(Position),Samples.Num());
    if(Consumed>24000) { Samples.RemoveAt(0,Consumed,false); Position-=Consumed; }
    return NumSamples;
}
