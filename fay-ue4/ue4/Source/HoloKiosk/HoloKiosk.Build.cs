using UnrealBuildTool;
public class HoloKiosk : ModuleRules {
    public HoloKiosk(ReadOnlyTargetRules Target) : base(Target) {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new string[] {
            "Core", "CoreUObject", "Engine", "InputCore", "Json", "JsonUtilities",
            "WebSockets", "AudioMixer", "Slate", "SlateCore", "ApplicationCore"
        });
    }
}
