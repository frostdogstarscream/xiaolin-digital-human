using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace HoloKiosk.Editor
{
    public static class QuaterniusActions
    {
        public static void Install()
        {
            const string source = "Assets/Kiosk/Animations/Quaternius/UAL1_Standard.fbx";
            var importer = AssetImporter.GetAtPath(source) as ModelImporter;
            if (importer == null) throw new InvalidOperationException("Quaternius FBX missing");
            importer.animationType = ModelImporterAnimationType.Human;
            importer.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
            importer.autoGenerateAvatarMappingIfUnspecified = true;
            importer.importAnimation = true;
            importer.materialImportMode = ModelImporterMaterialImportMode.None;
            var takes = importer.defaultClipAnimations;
            foreach (var take in takes)
            {
                take.name = take.name.Substring(take.name.LastIndexOf('|') + 1);
                take.loopTime = take.name.EndsWith("_Loop", StringComparison.Ordinal);
                take.loopPose = take.loopTime;
                take.lockRootRotation = true;
                take.lockRootHeightY = true;
                take.lockRootPositionXZ = true;
                take.keepOriginalOrientation = false;
                take.keepOriginalPositionY = true;
                take.keepOriginalPositionXZ = true;
            }
            importer.clipAnimations = takes;
            importer.SaveAndReimport();
            var assets = AssetDatabase.LoadAllAssetsAtPath(source);
            var avatar = assets.OfType<Avatar>().Single();
            if (!avatar.isValid || !avatar.isHuman) throw new InvalidOperationException("Quaternius humanoid mapping invalid");
            var clips = assets.OfType<AnimationClip>().Where(c => !c.name.StartsWith("__preview__") && c.name != "A_TPose").OrderBy(c => c.name).ToArray();
            if (clips.Length != 42 || clips.Any(c => !c.humanMotion || c.length <= 0))
                throw new InvalidOperationException("Expected 42 valid humanoid motion clips: " + string.Join(",", clips.Select(c => c.name)));
            var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>("Assets/Kiosk/Resources/KioskGestures.controller");
            var machine = controller.layers[0].stateMachine;
            foreach (var state in machine.states.Where(s => s.state.name.StartsWith("UAL/")).ToArray()) machine.RemoveState(state.state);
            machine.states.Single(s => s.state.name == "Idle").state.motion = clips.Single(c => c.name == "Idle_Loop");
            machine.states.Single(s => s.state.name == "Explain").state.motion = clips.Single(c => c.name == "Idle_Talking_Loop");
            var catalog = new AnimationCatalog { actions = new AnimationEntry[clips.Length] };
            for (int i = 0; i < clips.Length; i++)
            {
                var clip = clips[i];
                var state = machine.AddState("UAL/" + clip.name);
                state.motion = clip;
                var transition = machine.AddAnyStateTransition(state);
                transition.hasExitTime = false;
                transition.duration = .35f;
                transition.canTransitionToSelf = false;
                transition.AddCondition(AnimatorConditionMode.Equals, 100 + i, "BaseParam");
                catalog.actions[i] = new AnimationEntry { name = clip.name, parameter = 100 + i, duration = clip.length, loop = clip.isLooping };
            }
            File.WriteAllText("Assets/Kiosk/Resources/QuaterniusCatalog.json", JsonUtility.ToJson(catalog, true));
            AssetDatabase.ImportAsset("Assets/Kiosk/Resources/QuaterniusCatalog.json");
            EditorUtility.SetDirty(controller);
            AssetDatabase.SaveAssets();
            Debug.Log("QUATERNIUS_IMPORT_OK human=true clips=" + clips.Length);
        }
    }
}
