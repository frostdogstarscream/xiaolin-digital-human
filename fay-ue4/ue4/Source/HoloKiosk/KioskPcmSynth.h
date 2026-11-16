#pragma once
#include "CoreMinimal.h"
#include "Components/SynthComponent.h"
#include "KioskPcmSynth.generated.h"

// Source: mono 24 kHz signed PCM16. Resampled on the audio render thread.
UCLASS(ClassGroup=Audio, meta=(BlueprintSpawnableComponent))
class HOLOKIOSK_API UKioskPcmSynth : public USynthComponent {
    GENERATED_BODY()
public:
    UKioskPcmSynth(const FObjectInitializer& ObjectInitializer);
    void BeginSegment();
    bool AppendPCM(const TArray<uint8>& PCM);
    void EndSegment();
    void Flush();
    bool IsDrained() const;
    float MouthEnvelope() const;
protected:
    virtual bool Init(int32& SampleRate) override;
    virtual int32 OnGenerateAudio(float* OutAudio, int32 NumSamples) override;
private:
    mutable FCriticalSection Guard;
    TArray<float> Samples;
    double Position = 0;
    int32 OutputRate = 48000;
    bool bInputEnded = false;
    float Envelope = 0;
};
