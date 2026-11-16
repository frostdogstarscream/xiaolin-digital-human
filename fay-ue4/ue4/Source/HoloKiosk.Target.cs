using UnrealBuildTool;
public class HoloKioskTarget : TargetRules {
    public HoloKioskTarget(TargetInfo Target) : base(Target) {
        Type = TargetType.Game;
        DefaultBuildSettings = BuildSettingsVersion.V2;
        ExtraModuleNames.Add("HoloKiosk");
    }
}
