using UnrealBuildTool;
public class HoloKioskEditorTarget : TargetRules {
    public HoloKioskEditorTarget(TargetInfo Target) : base(Target) {
        Type = TargetType.Editor;
        DefaultBuildSettings = BuildSettingsVersion.V2;
        ExtraModuleNames.Add("HoloKiosk");
    }
}
