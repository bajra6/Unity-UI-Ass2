using System;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.LowLevel;

public static class GoodBoySetup
{
    [MenuItem("Good Boy/Create Fetch Scene")]
    public static void CreateScene()
    {
        const string scenePath = "Assets/Scenes/GoodBoyFetch.unity";
        Directory.CreateDirectory("Assets/Scenes");
        // Dedicated new scene; never replace the user's existing scene.
        if (File.Exists(scenePath))
        {
            Debug.Log("GoodBoyFetch scene already exists. Preserving it.");
            return;
        }
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        new GameObject("Dog Fetch Simulator").AddComponent<GoodBoyGame>();
        EditorSceneManager.SaveScene(scene, scenePath);
        var existing = new System.Collections.Generic.List<EditorBuildSettingsScene>(EditorBuildSettings.scenes);
        existing.Insert(0, new EditorBuildSettingsScene(scenePath, true));
        EditorBuildSettings.scenes = existing.ToArray();
        AssetDatabase.SaveAssets();
        Debug.Log("GOODBOY_SETUP_OK: " + scenePath);
    }

    // Batch smoke test: enter Play Mode, run real actions and capture the rendered game.
    public static void Verify()
    {
        Directory.CreateDirectory("Verification");
        File.WriteAllText("Verification/result.json", "{\"status\":\"running\"}");
        EditorSceneManager.OpenScene("Assets/Scenes/GoodBoyFetch.unity");
        SessionState.SetBool("GoodBoyVerify", true);
        EditorApplication.EnterPlaymode();
    }

    public static void Complete(int code, string message)
    {
        SessionState.SetBool("GoodBoyVerify", false);
        File.WriteAllText("Verification/result.json", JsonUtility.ToJson(new VerificationResult { code=code, status=code==0 ? "passed":"failed", message=message },true));
        if(Application.isBatchMode) EditorApplication.Exit(code);
        else EditorApplication.delayCall += () => EditorApplication.ExitPlaymode();
    }

    [Serializable] class VerificationResult { public int code; public string status; public string message; }

    [InitializeOnLoadMethod]
    static void RegisterVerification()
    {
        EditorApplication.playModeStateChanged -= OnVerificationState;
        EditorApplication.playModeStateChanged += OnVerificationState;
    }

    static void OnVerificationState(PlayModeStateChange state)
    {
        if (SessionState.GetBool("GoodBoyVerify", false) && state == PlayModeStateChange.EnteredPlayMode)
            new GameObject("Prototype verification").AddComponent<GoodBoyVerification>();
    }
}

public class GoodBoyVerification : MonoBehaviour
{
    Transform mouth;
    FetchBall ball;
    bool watchCarry;
    float maxCarryError;
    Keyboard testKeyboard, originalKeyboard;
    InputSettings.EditorInputBehaviorInPlayMode previousInputBehavior;
    InputSettings.BackgroundBehavior previousBackgroundBehavior;
    bool inputOverride;
    void OnDestroy()
    {
        if(testKeyboard != null && testKeyboard.added) InputSystem.RemoveDevice(testKeyboard);
        if(originalKeyboard != null && originalKeyboard.added) originalKeyboard.MakeCurrent();
        if(inputOverride)
        {
            InputSystem.settings.editorInputBehaviorInPlayMode=previousInputBehavior;
            InputSystem.settings.backgroundBehavior=previousBackgroundBehavior;
        }
    }
    void LateUpdate()
    {
        if(watchCarry && ball && mouth)
            maxCarryError=Mathf.Max(maxCarryError,Vector3.Distance(ball.transform.position,mouth.position));
    }

    void Fail(int code, string message) { Debug.LogError(message); GoodBoySetup.Complete(code,message); }

    System.Collections.Generic.Dictionary<SkinnedMeshRenderer, float[]> FootShapes()
    {
        var result = new System.Collections.Generic.Dictionary<SkinnedMeshRenderer, float[]>();
        foreach (var skin in GameObject.Find("Dog").GetComponentsInChildren<SkinnedMeshRenderer>())
        {
            string part = skin.transform.parent.name;
            if (!part.StartsWith("Toe") && !part.StartsWith("Rounded paw")) continue;
            var baked = new Mesh(); skin.BakeMesh(baked);
            var vertices = baked.vertices;
            var lengths = new float[vertices.Length];
            for (int i = 0; i < lengths.Length; i++) lengths[i] = Vector3.Distance(vertices[0], vertices[i]);
            result[skin] = lengths;
            Destroy(baked);
        }
        return result;
    }

    void Capture(string name, bool portrait=false)
    {
        var camera=Camera.main;
        var pos=camera.transform.position;var rot=camera.transform.rotation;
        if(portrait) { camera.transform.position=new Vector3(3.2f,2.1f,1.8f);camera.transform.LookAt(new Vector3(-.5f,.9f,-2.6f)); }
        if(name=="dominance-view")
        {
            Vector3 pinkPosition = GameObject.Find("Person in pink").transform.position;
            camera.transform.position=pinkPosition+new Vector3(3,2.2f,4);
            camera.transform.LookAt(pinkPosition+new Vector3(-.5f,.7f,.4f));
        }
        var rt=RenderTexture.GetTemporary(1600,900,24);
        var oldTarget=camera.targetTexture;var oldActive=RenderTexture.active;
        camera.targetTexture=rt;camera.Render();RenderTexture.active=rt;
        var texture=new Texture2D(1600,900,TextureFormat.RGB24,false);
        texture.ReadPixels(new Rect(0,0,1600,900),0,0);texture.Apply();
        File.WriteAllBytes("Verification/"+name+".png",texture.EncodeToPNG());
        camera.targetTexture=oldTarget;RenderTexture.active=oldActive;RenderTexture.ReleaseTemporary(rt);Destroy(texture);
        camera.transform.SetPositionAndRotation(pos,rot);
    }

    System.Collections.IEnumerator Start()
    {
        yield return new WaitForSeconds(1);
        var game = UnityEngine.Object.FindAnyObjectByType<GoodBoyGame>();
        if (!game) { Fail(2,"Game missing"); yield break; }
        var dog = GameObject.Find("Dog").transform;
        originalKeyboard=Keyboard.current;
        previousInputBehavior=InputSystem.settings.editorInputBehaviorInPlayMode;
        previousBackgroundBehavior=InputSystem.settings.backgroundBehavior;
        inputOverride=true;
        InputSystem.settings.editorInputBehaviorInPlayMode=InputSettings.EditorInputBehaviorInPlayMode.AllDeviceInputAlwaysGoesToGameView;
        InputSystem.settings.backgroundBehavior=InputSettings.BackgroundBehavior.IgnoreFocus;
        testKeyboard=InputSystem.AddDevice<Keyboard>("GoodBoy verification keyboard");
        InputSystem.EnableDevice(testKeyboard);
        Vector3 keyboardStart=dog.position;
        InputSystem.QueueStateEvent(testKeyboard,new KeyboardState(Key.W));
        yield return new WaitForSeconds(.2f);
        InputSystem.QueueStateEvent(testKeyboard,new KeyboardState());
        yield return null;
        if(Vector3.Distance(keyboardStart,dog.position)<.2f)
        { Fail(12,"WASD failed immediately after startup. Distance="+Vector3.Distance(keyboardStart,dog.position)+" editing="+game.IsEditingCommand+" keyboard="+Keyboard.current?.name+" enabled="+testKeyboard.enabled);yield break; }
        game.SetCommandEditing(true);
        Vector3 typingStart=dog.position;
        InputSystem.QueueStateEvent(testKeyboard,new KeyboardState(Key.W));
        yield return new WaitForSeconds(.2f);
        if(Vector3.Distance(typingStart,dog.position)>.03f)
        { Fail(13,"Typing W incorrectly moved the dog.");yield break; }
        InputSystem.QueueStateEvent(testKeyboard,new KeyboardState(Key.Enter));
        yield return null; yield return null;
        InputSystem.QueueStateEvent(testKeyboard,new KeyboardState(Key.W));
        yield return new WaitForSeconds(.2f);
        InputSystem.QueueStateEvent(testKeyboard,new KeyboardState());
        yield return null;
        if(game.IsEditingCommand || Vector3.Distance(typingStart,dog.position)<.2f)
        { Fail(14,"Enter did not restore WASD after typing.");yield break; }
        InputSystem.RemoveDevice(testKeyboard);testKeyboard=null;
        if(originalKeyboard!=null) originalKeyboard.MakeCurrent();
        InputSystem.settings.editorInputBehaviorInPlayMode=previousInputBehavior;
        InputSystem.settings.backgroundBehavior=previousBackgroundBehavior;inputOverride=false;
        var keyboardController=dog.GetComponent<CharacterController>();
        keyboardController.enabled=false;dog.position=keyboardStart;keyboardController.enabled=true;
        Debug.Log("GOODBOY_KEYBOARD_OK: immediate W, typing isolation, Enter restores W");
        var baton = GameObject.Find("Red ball").GetComponent<Rigidbody>();
        ball=baton.GetComponent<FetchBall>();
        mouth=GameObject.Find("Mouth attachment").transform;
        yield return game.Execute(new DogAction { action = "pick_up" });
        if (game.IsHoldingBall) { Fail(3,"Pickup incorrectly accepted a distant ball."); yield break; }
        Vector3 start = dog.position;
        yield return game.Execute(new DogAction { action = "dance" });
        yield return game.Execute(new DogAction { action = "sit" });
        yield return game.Execute(new DogAction { action = "stand" });
        yield return game.Execute(new DogAction { action = "roll" });
        var pinkPerson = GameObject.Find("Person in pink");
        if (!pinkPerson) { Fail(14,"Pink-shirt person is missing."); yield break; }
        bool pinkTint = false;
        foreach (var renderer in pinkPerson.GetComponentsInChildren<Renderer>())
            for (int materialIndex = 0; materialIndex < renderer.sharedMaterials.Length; materialIndex++)
            {
                var block = new MaterialPropertyBlock(); renderer.GetPropertyBlock(block, materialIndex);
                Color tint = block.GetColor("_BaseColor");
                if (tint.r > .9f && tint.g < .3f && tint.b > .4f) pinkTint = true;
            }
        if (!pinkTint) { Fail(18,"Pink character's clothing tint was not applied."); yield break; }
        yield return game.Execute(new DogAction { action = "sniff" });
        var feetBefore = FootShapes();
        if (feetBefore.Count != 16) { Fail(20,"Expected four paw meshes and twelve toes."); yield break; }
        game.StartCoroutine(game.Execute(new DogAction { action = "pee" }));
        yield return new WaitForSeconds(2.5f);
        if (!GameObject.Find("Pee stream")) { Fail(15,"Pee stream did not appear."); yield break; }
        foreach (var foot in FootShapes())
            for (int i = 0; i < foot.Value.Length; i++)
                if (Mathf.Abs(foot.Value[i] - feetBefore[foot.Key][i]) > .002f)
                { Fail(21,"Raised paw or toe mesh stretched during pee."); yield break; }
        Capture("pee-view", true);
        game.Cancel();
        yield return null;
        if (GameObject.Find("Pee stream")) { Fail(16,"Stop did not clean up pee effect."); yield break; }
        yield return game.Execute(new DogAction { action = "pee" });
        if (game.LastResult != "pee completed.") { Fail(17,"Pee action did not finish."); yield break; }
        yield return game.Execute(new DogAction { action = "move_forward", amount = .5f });
        if (Mathf.Abs(Vector3.Distance(start, dog.position) - .5f) > .15f)
        { Fail(4,"Movement did not travel the requested distance."); yield break; }
        yield return game.Execute(new DogAction { action = "turn_right", amount = 30 });
        if (Mathf.Abs(Mathf.DeltaAngle(dog.eulerAngles.y, 30)) > 1)
        { Fail(5,"Turn did not reach the requested heading."); yield break; }
        ball.Place(game.transform, dog.position + dog.forward * 1.8f + Vector3.up * FetchBall.Radius);
        yield return game.Execute(new DogAction { action = "pick_up" });
        if (!game.IsHoldingBall || !baton.isKinematic || baton.transform.parent.name != "Mouth attachment")
        { Fail(6,"Pickup at the larger 1.8m range failed."); yield break; }
        watchCarry=true;
        foreach(string action in new[]{"move_forward","turn_left","dance","sit","stand","roll","sniff","pee"})
            yield return game.Execute(new DogAction { action=action,amount=action=="turn_left" ? 60:1 });
        yield return null;
        watchCarry=false;
        if(maxCarryError>.015f || baton.interpolation!=RigidbodyInterpolation.None || baton.detectCollisions)
        { Fail(9,"Carry attachment drifted: "+maxCarryError); yield break; }
        var controller = dog.GetComponent<CharacterController>();
        controller.enabled = false;
        dog.position = new Vector3(-3, .02f, -3.9f);
        controller.enabled = true;
        yield return game.Execute(new DogAction { action = "drop" });
        if (game.IsHoldingBall || !game.LastResult.StartsWith("Drop completed"))
        { Fail(7,"Ball delivery at 1.1m failed."); yield break; }
        yield return new WaitForSeconds(.8f);
        if(!ball.IsSettled) { Fail(10,"Dropped ball did not settle");yield break; }
        game.ThrowAt(new Vector3(3,0,3));
        yield return new WaitForSeconds(1.5f);
        Vector3 landed=baton.position;
        Quaternion landedRotation=baton.rotation;
        yield return new WaitForSeconds(.6f);
        if(!ball.IsSettled || Vector3.Distance(landed,baton.position)>.005f || Quaternion.Angle(landedRotation,baton.rotation)>.1f)
        { Fail(11,"Thrown ball rolled or drifted after landing.");yield break; }
        controller.enabled = false;
        dog.position = new Vector3(0, .02f, -2);
        dog.rotation = Quaternion.identity;
        controller.enabled = true;
        ball.Place(game.transform,new Vector3(1, FetchBall.Radius, 2));
        yield return new WaitForSeconds(.6f);
        var batonMaterial = baton.GetComponent<Renderer>().sharedMaterial;
        Debug.Log("GOODBOY_MATERIAL: shader=" + batonMaterial.shader.name + " color=" + batonMaterial.color + " base=" + (batonMaterial.HasProperty("_BaseColor") ? batonMaterial.GetColor("_BaseColor").ToString() : "absent"));
        string url=SessionState.GetString("GoodBoyVerifyUrl", "");
        if (Environment.GetEnvironmentVariable("GOODBOY_VERIFY_HTTP") == "1" || url.Length>0)
        {
            if(url.Length>0)game.serverUrl=url;
            Vector3 beforeAI=dog.position;
            bool placeholder=SessionState.GetBool("GoodBoyVerifyPlaceholder",false) || Environment.GetEnvironmentVariable("GOODBOY_VERIFY_PLACEHOLDER")=="1";
            game.BeginCommand(placeholder ? "Find the ball" : "Dance, move forward, turn right, then finish.");
            float deadline = Time.realtimeSinceStartup + 35;
            string finishedPrefix=placeholder ? "Placeholder demo finished" : "Instruction completed successfully";
            while ((game.DecisionCount < 4 || !game.LastResult.StartsWith(finishedPrefix)) && Time.realtimeSinceStartup < deadline) yield return null;
            if (game.DecisionCount != 4 || !game.LastResult.StartsWith(finishedPrefix) || Vector3.Distance(beforeAI,dog.position)<.45f)
            { Fail(8,"Unity HTTP movement/action loop failed: " + game.LastResult); yield break; }
            Debug.Log(placeholder ? "GOODBOY_HTTP_OK: API outage -> labelled placeholder movement -> honest finish"
                : "GOODBOY_HTTP_OK: camera -> Python -> mock provider -> dance/move/turn/finish; actual movement verified");
            SessionState.EraseString("GoodBoyVerifyUrl");
            SessionState.EraseBool("GoodBoyVerifyPlaceholder");
        }
        if (Environment.GetEnvironmentVariable("GOODBOY_VERIFY_INSTRUCTIONS") == "1")
        {
            game.serverUrl=Environment.GetEnvironmentVariable("GOODBOY_VERIFY_URL");
            foreach (string recipient in new[] { "pink", "blue" })
            {
                var person = GameObject.Find(recipient == "pink" ? "Person in pink" : "Owner in blue").transform;
                controller.enabled=false; dog.position=person.position+new Vector3(0,.02f,1.8f); dog.rotation=Quaternion.identity; controller.enabled=true;
                ball.Place(game.transform,dog.position+dog.forward*.5f+Vector3.up*FetchBall.Radius);
                game.BeginCommand("Fetch the ball to the " + recipient + " person, then sit.");
                bool sawDrop=false, sawSit=false;
                float deadline=Time.realtimeSinceStartup+25;
                while (Time.realtimeSinceStartup<deadline && !game.InstructionSucceeded)
                {
                    if (game.LastResult.StartsWith("Drop completed")) sawDrop=true;
                    if (game.LastResult.StartsWith("Sit completed")) sawSit=true;
                    yield return null;
                }
                if (!game.InstructionSucceeded || !sawDrop || !sawSit || game.IsHoldingBall || game.DecisionCount!=4)
                { game.Cancel(); Fail(22,"Instruction did not complete pickup, delivery and sit for " + recipient); yield break; }
            }
            controller.enabled=false;dog.position=new Vector3(0,.02f,5);dog.rotation=Quaternion.identity;controller.enabled=true;
            ball.Place(game.transform,dog.position+dog.forward*.5f+Vector3.up*FetchBall.Radius);
            yield return game.Execute(new DogAction { action="pick_up" });
            game.BeginCommand("Drop it here.");
            float dropDeadline=Time.realtimeSinceStartup+15;
            while (!game.InstructionSucceeded && Time.realtimeSinceStartup<dropDeadline) yield return null;
            if (!game.InstructionSucceeded || game.IsHoldingBall || game.DecisionCount!=2)
            { game.Cancel(); Fail(23,"Drop here failed away from both people."); yield break; }
            game.BeginCommand("Drop it here."); // Empty-handed: must fail, not claim success.
            float failureDeadline=Time.realtimeSinceStartup+15;
            while (!game.LastResult.StartsWith("Drop failed") && Time.realtimeSinceStartup<failureDeadline) yield return null;
            if (game.InstructionSucceeded || !game.LastResult.StartsWith("Drop failed"))
            { game.Cancel(); Fail(24,"Failed drop incorrectly completed the instruction."); yield break; }
            game.Cancel();
            Debug.Log("GOODBOY_INSTRUCTIONS_OK: pink/blue delivery then sit, drop here, and failed-drop handling");
        }
        if (Environment.GetEnvironmentVariable("GOODBOY_VERIFY_DOMINANCE") == "1")
        {
            controller.enabled=false;dog.position=new Vector3(0,.02f,-2);dog.rotation=Quaternion.identity;controller.enabled=true;
            game.serverUrl=Environment.GetEnvironmentVariable("GOODBOY_VERIFY_URL");
            game.BeginCommand("Assert dominance.");
            bool sawPee = false;
            float deadline=Time.realtimeSinceStartup+100;
            while (Time.realtimeSinceStartup < deadline)
            {
                if (!sawPee && GameObject.Find("Pee stream")) { sawPee=true; Capture("dominance-view"); }
                if (game.LastResult=="Instruction completed successfully.") break;
                yield return null;
            }
            if (!sawPee || game.LastResult!="Instruction completed successfully." || Vector3.Distance(dog.position,pinkPerson.transform.position)>1.25f)
            { game.Cancel(); Fail(19,"Dominance flow failed to approach pink person and finish pee."); yield break; }
            Debug.Log("GOODBOY_DOMINANCE_OK: real VLM plan -> approach pink person -> pee -> finish");
        }
        controller.enabled=false;dog.position=new Vector3(0,.02f,-2);dog.rotation=Quaternion.identity;controller.enabled=true;
        yield return new WaitForSeconds(.5f);
        Capture("game-view"); Capture("characters",true);
        ball.Place(game.transform,dog.position+dog.forward*1.8f+Vector3.up*FetchBall.Radius);
        yield return game.Execute(new DogAction {action="pick_up"});
        yield return null;
        Capture("carry-view",true);
        string summary="Startup WASD, typing isolation, movement, turn, pickup, delivery, stationary landing, pink clothing, sniff/pee, stop cleanup, carrying during animations and render passed. Max carry error: "+maxCarryError;
        Debug.Log("GOODBOY_PLAY_OK: "+summary);
        GoodBoySetup.Complete(0,summary);
    }
}
