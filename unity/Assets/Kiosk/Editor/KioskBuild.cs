using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

namespace HoloKiosk.Editor
{
    public static class KioskBuild
    {
        [MenuItem("HoloKiosk/Prepare Project")]
        public static void Prepare()
        {
            Directory.CreateDirectory("Assets/Kiosk/Resources");
            Directory.CreateDirectory("Assets/Kiosk/Scenes");
            AssetDatabase.Refresh();
            CreateGestures();
            QuaterniusActions.Install();
            const string profile = "Assets/Kiosk/Resources/LipProfile.asset";
            if (!File.Exists(profile))
                AssetDatabase.CopyAsset("Assets/uLipSync/Assets/Profiles/uLipSync-Profile-Sample-Female.asset", profile);
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            new GameObject("HoloKiosk").AddComponent<KioskApp>();
            EditorSceneManager.SaveScene(scene, "Assets/Kiosk/Scenes/Kiosk.unity");
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene("Assets/Kiosk/Scenes/Kiosk.unity", true) };
            PlayerSettings.companyName = "HoloKiosk";
            PlayerSettings.productName = "全息仓数字人";
            PlayerSettings.defaultScreenWidth = 1280;
            PlayerSettings.defaultScreenHeight = 720;
            PlayerSettings.runInBackground = true;
            PlayerSettings.fullScreenMode = FullScreenMode.FullScreenWindow;
            PlayerSettings.colorSpace = ColorSpace.Linear;
            PlayerSettings.SetScriptingBackend(UnityEditor.Build.NamedBuildTarget.Standalone, ScriptingImplementation.Mono2x);
            PlayerSettings.SetApiCompatibilityLevel(UnityEditor.Build.NamedBuildTarget.Standalone, ApiCompatibilityLevel.NET_Standard);
            PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.StandaloneWindows64, false);
            PlayerSettings.SetGraphicsAPIs(BuildTarget.StandaloneWindows64, new[] { GraphicsDeviceType.Direct3D11 });
            PlayerSettings.stripEngineCode = false;
            QualitySettings.antiAliasing = 2;
            QualitySettings.shadows = ShadowQuality.Disable;
            // Runtime-imported VRM materials are not referenced by an editor scene.
            var graphics = new SerializedObject(AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/GraphicsSettings.asset")[0]);
            var always = graphics.FindProperty("m_AlwaysIncludedShaders");
            var names = new[] { "Standard", "VRM/MToon", "VRM10/MToon10", "UniGLTF/UniUnlit", "Unlit/Texture", "Unlit/Transparent" };
            foreach (string name in names)
            {
                var shader = Shader.Find(name);
                if (shader == null) continue;
                bool exists = Enumerable.Range(0, always.arraySize).Any(i => always.GetArrayElementAtIndex(i).objectReferenceValue == shader);
                if (!exists) { always.InsertArrayElementAtIndex(always.arraySize); always.GetArrayElementAtIndex(always.arraySize - 1).objectReferenceValue = shader; }
            }
            graphics.ApplyModifiedProperties();
            AssetDatabase.SaveAssets();
        }

        [MenuItem("HoloKiosk/Build Windows")]
        public static void Windows()
        {
            try
            {
                Prepare();
                string output = Path.GetFullPath(Path.Combine(Application.dataPath, "../Builds/Windows-Quaternius/HoloKiosk.exe"));
                Directory.CreateDirectory(Path.GetDirectoryName(output));
                var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions {
                    scenes = new[] { "Assets/Kiosk/Scenes/Kiosk.unity" }, locationPathName = output,
                    target = BuildTarget.StandaloneWindows64, options = BuildOptions.CompressWithLz4 });
                File.WriteAllText(Path.Combine(Path.GetDirectoryName(output), "build-report.txt"),
                    $"Result: {report.summary.result}\nErrors: {report.summary.totalErrors}\nWarnings: {report.summary.totalWarnings}\nBytes: {report.summary.totalSize}\n");
                if (Application.isBatchMode) EditorApplication.Exit(report.summary.result == BuildResult.Succeeded ? 0 : 1);
            }
            catch (Exception error)
            {
                UnityEngine.Debug.LogException(error);
                if (Application.isBatchMode) EditorApplication.Exit(1);
                else throw;
            }
        }

        static void CreateGestures()
        {
            const string path = "Assets/Kiosk/Resources/KioskGestures.controller";
            var idle = AssetDatabase.LoadAssetAtPath<AnimationClip>("Assets/Kiosk/Resources/Idle.anim");
            if (File.Exists(path) && idle != null && AnimationUtility.GetCurveBindings(idle).Any(b => b.propertyName == "RootT.y")) return;
            if (File.Exists(path)) AssetDatabase.DeleteAsset(path);
            var controller = AnimatorController.CreateAnimatorControllerAtPath(path);
            controller.AddParameter("BaseParam", AnimatorControllerParameterType.Int);
            var machine = controller.layers[0].stateMachine;
            string[] names = { "Idle", "Listen", "Think", "Explain", "Point", "Greet", "Farewell" };
            for (int i = 0; i < names.Length; i++)
            {
                var clip = new AnimationClip { name = names[i], frameRate = 30, wrapMode = WrapMode.Loop };
                var settings = AnimationUtility.GetAnimationClipSettings(clip);
                settings.loopTime = true;
                settings.keepOriginalPositionY = true;
                AnimationUtility.SetAnimationClipSettings(clip, settings);
                // Humanoid muscle clips use body translation normalized by humanScale.
                // Omitting RootT.y places the hips at ground level in a generated clip.
                clip.SetCurve("", typeof(Animator), "RootT.y", AnimationCurve.Constant(0, 4, 1));
                clip.SetCurve("", typeof(Animator), "RootQ.w", AnimationCurve.Constant(0, 4, 1));
                Curve(clip, "Left Arm Down-Up", -.78f, .015f);
                Curve(clip, "Right Arm Down-Up", -.78f, .015f);
                Curve(clip, "Left Arm Front-Back", .05f, .015f);
                Curve(clip, "Right Arm Front-Back", .05f, .015f);
                Curve(clip, "Left Forearm Stretch", .7f, .02f);
                Curve(clip, "Right Forearm Stretch", .7f, .02f);
                Curve(clip, "Spine Front-Back", 0, .018f);
                Curve(clip, "Chest Front-Back", 0, .014f);
                Curve(clip, "Head Turn Left-Right", 0, .025f);
                Curve(clip, "Head Nod Down-Up", i == 1 ? -.05f : 0, i == 1 ? .045f : .015f);
                if (i >= 3)
                {
                    Curve(clip, "Right Arm Down-Up", i == 5 ? .15f : -.3f, .08f);
                    Curve(clip, "Right Arm Front-Back", .2f, .08f);
                    Curve(clip, "Right Forearm Stretch", .15f, .12f);
                    Curve(clip, "Right Hand Down-Up", .1f, .06f);
                }
                if (i == 3) { Curve(clip, "Left Arm Down-Up", -.5f, .04f); Curve(clip, "Left Forearm Stretch", .2f, .1f); }
                if (i == 2) Curve(clip, "Head Tilt Left-Right", .04f, .015f);
                if (i == 6)
                {
                    Curve(clip, "Head Nod Down-Up", -.06f, .06f);
                    Curve(clip, "Right Arm Down-Up", -.55f, .04f);
                    Curve(clip, "Spine Front-Back", .04f, .02f);
                }
                string clipPath = "Assets/Kiosk/Resources/" + names[i] + ".anim";
                if (File.Exists(clipPath)) AssetDatabase.DeleteAsset(clipPath);
                AssetDatabase.CreateAsset(clip, clipPath);
                var state = machine.AddState(names[i]); state.motion = clip;
                if (i == 0) machine.defaultState = state;
                var transition = machine.AddAnyStateTransition(state);
                transition.hasExitTime = false; transition.duration = .35f; transition.canTransitionToSelf = false;
                transition.AddCondition(AnimatorConditionMode.Equals, i, "BaseParam");
            }
        }

        static void Curve(AnimationClip clip, string muscle, float center, float amplitude)
        {
            if (!HumanTrait.MuscleName.Contains(muscle)) return;
            var curve = new AnimationCurve(new Keyframe(0, center), new Keyframe(1, center + amplitude),
                new Keyframe(2, center), new Keyframe(3, center - amplitude), new Keyframe(4, center));
            for (int i = 0; i < curve.length; i++) curve.SmoothTangents(i, 0);
            clip.SetCurve("", typeof(Animator), muscle, curve);
        }
    }
}
