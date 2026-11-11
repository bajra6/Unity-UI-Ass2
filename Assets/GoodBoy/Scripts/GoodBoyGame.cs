using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.Networking;
using UnityEngine.Rendering.Universal;

// Room and controls are generated locally; character meshes are bundled CC0 assets.
public class GoodBoyGame : MonoBehaviour
{
    public string serverUrl = "http://127.0.0.1:8000";
    Transform dog, visual, mouth, owner, tail;
    readonly List<Transform> legs = new List<Transform>();
    Rigidbody ball;
    FetchBall fetchBall;
    DogMeshRig dogRig;
    public float pickupRange = 2f;
    public float deliveryRange = 3f;
    string serverStatus = "Checking server…";
    string lastJson = "No server response yet.";
    string actionSource = "Manual";
    bool showDiagnostics, checkingHealth;
    bool editingCommand, clearKeyboardFocus = true;
    public bool IsEditingCommand => editingCommand;
    CharacterController controller;
    Camera dogCamera;
    Material brown, cream, black, red, blue, white, grey, mint;
    bool busy, aiRunning, holding, seated;
    bool fetchTask, fetchDelivered;
    readonly Queue<DogPlanStep> remainingPlan = new Queue<DogPlanStep>();
    DogPlanStep activeStep;
    public string TaskState { get; private set; } = "idle";
    string command = "Find the red ball, pick it up, and bring it back to the person in blue.";
    string activeCommand = "";
    string status = "Ready. Throw the ball, then give your dog a command.";
    string lastResult = "Ready";
    string lastAction = "None";
    string session;
    int decisions;
    int generation;
    float orbit;
    float cameraDistance = 4.2f;
    GUIStyle titleStyle, bodyStyle, smallStyle, buttonStyle, inputStyle;
    public string LastResult => lastResult;
    public bool IsHoldingBall => holding;
    public int DecisionCount => decisions;

    void Start()
    {
        Application.targetFrameRate = 60;
        Application.runInBackground = true;
        BuildWorld();
        StartCoroutine(CheckServer());
    }

    Material Mat(string name, Color color)
    {
        Shader shader = Shader.Find("Universal Render Pipeline/Lit");
        if (!shader) shader = Shader.Find("Standard");
        var material = new Material(shader) { name = name, color = color };
        if (material.HasProperty("_BaseColor")) material.SetColor("_BaseColor", color);
        if (material.HasProperty("_Color")) material.SetColor("_Color", color);
        if (material.HasProperty("_Smoothness")) material.SetFloat("_Smoothness", .15f);
        if (material.HasProperty("_Metallic")) material.SetFloat("_Metallic", 0);
        return material;
    }

    GameObject Shape(string name, PrimitiveType type, Transform parent, Vector3 position, Vector3 scale, Material material, bool collider = false)
    {
        var go = GameObject.CreatePrimitive(type);
        go.name = name;
        go.transform.SetParent(parent, false);
        go.transform.localPosition = position;
        go.transform.localScale = scale;
        var renderer = go.GetComponent<Renderer>();
        renderer.sharedMaterial = material;
        // Explicit per-renderer tint also works when the editor's batching path is active.
        var properties = new MaterialPropertyBlock();
        properties.SetColor("_BaseColor", material.GetColor("_BaseColor"));
        properties.SetColor("_Color", material.color);
        renderer.SetPropertyBlock(properties);
        if (name == "Floor seam") renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
        if (!collider) Destroy(go.GetComponent<Collider>());
        return go;
    }

    void BuildWorld()
    {
        white = Mat("Warm white", new Color(.89f, .91f, .92f));
        grey = Mat("Floor", new Color(.69f, .74f, .77f));
        brown = Mat("Golden coat", new Color(.66f, .36f, .12f));
        cream = Mat("Cream coat", new Color(.98f, .82f, .55f));
        black = Mat("Eyes and nose", new Color(.035f, .045f, .055f));
        red = Mat("Red ball", new Color(.95f, .025f, .035f));
        blue = Mat("Blue shirt", new Color(.025f, .24f, .82f));
        mint = Mat("Collar", new Color(.04f, .7f, .55f));
        Shape("Floor", PrimitiveType.Cube, transform, new Vector3(0, -.15f, 0), new Vector3(20, .3f, 20), grey, true);
        Shape("North wall", PrimitiveType.Cube, transform, new Vector3(0, 2.5f, 10), new Vector3(20, 5, .25f), white, true);
        Shape("South wall", PrimitiveType.Cube, transform, new Vector3(0, 2.5f, -10), new Vector3(20, 5, .25f), white, true);
        Shape("East wall", PrimitiveType.Cube, transform, new Vector3(10, 2.5f, 0), new Vector3(.25f, 5, 20), white, true);
        Shape("West wall", PrimitiveType.Cube, transform, new Vector3(-10, 2.5f, 0), new Vector3(.25f, 5, 20), white, true);
        // Subtle seams provide depth cues without adding obstacles.
        var seam = Mat("Floor seams", new Color(.64f, .69f, .72f));
        for (int i = -8; i <= 8; i += 2)
        {
            Shape("Floor seam", PrimitiveType.Cube, transform, new Vector3(i, .002f, 0), new Vector3(.025f, .004f, 19.5f), seam);
            Shape("Floor seam", PrimitiveType.Cube, transform, new Vector3(0, .002f, i), new Vector3(19.5f, .004f, .025f), seam);
        }
        RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Flat;
        RenderSettings.ambientLight = new Color(.7f, .74f, .8f);
        var lightGo = new GameObject("Soft daylight");
        lightGo.transform.SetParent(transform);
        lightGo.transform.rotation = Quaternion.Euler(50, -25, 0);
        var light = lightGo.AddComponent<Light>();
        light.type = LightType.Directional;
        light.intensity = 1.5f;
        light.shadows = LightShadows.Soft;

        owner = new GameObject("Owner in blue").transform;
        owner.SetParent(transform);
        owner.position = new Vector3(-3, 0, -5);
        AddCharacter("Owner", owner);
        var ownerCollider = owner.gameObject.AddComponent<CapsuleCollider>();
        ownerCollider.center = new Vector3(0,.9f,0);
        ownerCollider.height = 1.8f; ownerCollider.radius = .28f;

        dog = new GameObject("Dog").transform;
        dog.SetParent(transform);
        dog.position = new Vector3(0, .02f, -2);
        controller = dog.gameObject.AddComponent<CharacterController>();
        controller.height = 1.15f;
        controller.radius = .35f;
        controller.center = new Vector3(0, .58f, 0);
        controller.stepOffset = .12f;
        visual = new GameObject("Dog visual").transform;
        visual.SetParent(dog, false);
        AddCharacter("Dog", visual);
        dogRig = visual.gameObject.AddComponent<DogMeshRig>();
        var collar = Shape("Collar", PrimitiveType.Cylinder, visual, new Vector3(0,.69f,.34f), new Vector3(.31f,.035f,.31f), mint);
        collar.transform.localRotation = Quaternion.Euler(65,0,0);
        mouth = new GameObject("Mouth attachment").transform;
        mouth.SetParent(visual, false);
        mouth.localPosition = new Vector3(0, .72f, .83f);

        var ballGo = Shape("Red ball", PrimitiveType.Sphere, transform, new Vector3(1, FetchBall.Radius, 2), Vector3.one * FetchBall.Radius * 2, red, true);
        ball = ballGo.AddComponent<Rigidbody>();
        ball.mass = .25f;
        var physics = new PhysicsMaterial("Ball grip") { dynamicFriction = 1, staticFriction = 1, bounciness = 0 };
        ballGo.GetComponent<Collider>().material = physics;
        fetchBall = ballGo.AddComponent<FetchBall>();
        fetchBall.Place(transform, ballGo.transform.position);

        var cameraGo = new GameObject("Dog chase camera");
        cameraGo.transform.SetParent(transform);
        cameraGo.tag = "MainCamera";
        dogCamera = cameraGo.AddComponent<Camera>();
        dogCamera.fieldOfView = 60;
        dogCamera.allowDynamicResolution = false;
        var cameraData = dogCamera.GetUniversalAdditionalCameraData();
        cameraData.renderPostProcessing = true;
        cameraData.antialiasing = AntialiasingMode.SubpixelMorphologicalAntiAliasing;
        cameraData.antialiasingQuality = AntialiasingQuality.High;
        dogCamera.nearClipPlane = .08f;
        dogCamera.farClipPlane = 70;
        dogCamera.backgroundColor = new Color(.85f, .89f, .93f);
        dogCamera.clearFlags = CameraClearFlags.SolidColor;
        cameraGo.AddComponent<AudioListener>();
        UpdateCamera(true);
    }

    void AddCharacter(string name, Transform parent)
    {
        var prefab = Resources.Load<GameObject>("Characters/" + name);
        if (!prefab) { Debug.LogError("Missing character prefab: " + name + ". Run Good Boy > Rebuild Character Prefabs."); return; }
        var model = Instantiate(prefab, parent, false);
        foreach (var renderer in model.GetComponentsInChildren<Renderer>())
        {
            for (int i=0;i<renderer.sharedMaterials.Length;i++)
            {
                var material=renderer.sharedMaterials[i];
                var properties=new MaterialPropertyBlock();
                properties.SetColor("_BaseColor", material.GetColor("_BaseColor"));
                properties.SetColor("_Color", material.GetColor("_BaseColor"));
                renderer.SetPropertyBlock(properties,i);
            }
        }
    }

    void Update()
    {
        if (!dog) return;
        if (Keyboard.current != null)
        {
            if (Keyboard.current.escapeKey.wasPressedThisFrame) Cancel();
            else if (editingCommand && (Keyboard.current.enterKey.wasPressedThisFrame || Keyboard.current.numpadEnterKey.wasPressedThisFrame))
                SetCommandEditing(false);
        }
        if (Mouse.current != null && Mouse.current.leftButton.wasPressedThisFrame)
        {
            float scale = Mathf.Min(Screen.width / 1280f, Screen.height / 720f);
            Vector2 point = Mouse.current.position.ReadValue();
            point = new Vector2(point.x / scale, (Screen.height-point.y) / scale);
            SetCommandEditing(CommandRect(Screen.width/scale, Screen.height/scale).Contains(point));
        }
        if (Mouse.current != null && Mouse.current.rightButton.isPressed && !aiRunning)
        {
            SetCommandEditing(false);
            orbit += Mouse.current.delta.ReadValue().x * .13f;
        }
        if (Mouse.current != null && Mouse.current.leftButton.wasPressedThisFrame && !busy && !aiRunning)
        {
            Vector2 mouse = Mouse.current.position.ReadValue();
            float uiScale = Mathf.Min(Screen.width / 1280f, Screen.height / 720f);
            // Keep all HUD clicks separate from the aim-and-throw area.
            if (mouse.y > 225 * uiScale && mouse.y < Screen.height - 150 * uiScale)
            {
                Ray ray = dogCamera.ScreenPointToRay(mouse);
                if (new Plane(Vector3.up, Vector3.zero).Raycast(ray, out float distance))
                {
                    Vector3 target = ray.GetPoint(distance);
                    if (Mathf.Abs(target.x) < 9 && Mathf.Abs(target.z) < 9) ThrowAt(target);
                }
            }
        }
        if (!aiRunning && !busy && !editingCommand && Keyboard.current != null)
        {
            float turn = (Keyboard.current.dKey.isPressed ? 1 : 0) - (Keyboard.current.aKey.isPressed ? 1 : 0);
            float move = (Keyboard.current.wKey.isPressed ? 1 : 0) - (Keyboard.current.sKey.isPressed ? 1 : 0);
            dog.Rotate(0, turn * 110 * Time.deltaTime, 0);
            if (move != 0) { seated = false; visual.localRotation = Quaternion.identity; controller.Move(dog.forward * move * 2 * Time.deltaTime); AnimateWalk(Time.time); }
            else ResetLegs();
            if (Keyboard.current.tKey.wasPressedThisFrame) ThrowBall();
        }
        controller.Move(Vector3.down * 3 * Time.deltaTime);
        if (dogRig) dogRig.SetSeated(seated);
        if (!busy) visual.localPosition = new Vector3(0, seated ? -.15f : 0, 0);
    }

    void LateUpdate() { if (dogCamera) UpdateCamera(false); }

    static Rect CommandRect(float width, float height) => new Rect(36, height - 163, width - 230, 40);

    public void SetCommandEditing(bool editing)
    {
        editingCommand = editing;
        clearKeyboardFocus = !editing;
    }

    void UpdateCamera(bool snap)
    {
        Vector3 target = dog.position + Vector3.up * .8f;
        Vector3 offset = Quaternion.Euler(0, dog.eulerAngles.y + orbit, 0) * new Vector3(0, 2.0f, -cameraDistance);
        Vector3 desired = target + offset;
        desired.x = Mathf.Clamp(desired.x, -9.6f, 9.6f);
        desired.z = Mathf.Clamp(desired.z, -9.6f, 9.6f);
        dogCamera.transform.position = snap ? desired : Vector3.Lerp(dogCamera.transform.position, desired, 10 * Time.deltaTime);
        dogCamera.transform.LookAt(target + dog.forward * .1f);
    }

    void AnimateWalk(float time)
    {
        if (dogRig) dogRig.SetPose(1, seated);
        for (int i = 0; i < legs.Count; i++) legs[i].localRotation = Quaternion.Euler(Mathf.Sin(time * 12 + (i % 3 == 0 ? 0 : Mathf.PI)) * 27, 0, 0);
    }

    void ResetLegs() { foreach (var leg in legs) leg.localRotation = Quaternion.identity; }

    public void ThrowBall()
    {
        if (busy || aiRunning) return;
        Vector2 direction = UnityEngine.Random.insideUnitCircle.normalized;
        if (direction.sqrMagnitude < .1f) direction = Vector2.up;
        Vector3 target = new Vector3(direction.x * UnityEngine.Random.Range(3f, 7f), .15f, direction.y * UnityEngine.Random.Range(3f, 7f));
        ThrowAt(target);
    }

    public void ThrowAt(Vector3 target)
    {
        if (busy || aiRunning) return;
        holding = false;
        fetchDelivered = false;
        TaskState = "idle";
        target.y = FetchBall.Radius;
        Vector3 origin = owner.position + Vector3.up * 1.4f + Vector3.forward * .8f;
        float flightTime = .9f;
        Vector3 velocity = (target-origin)/flightTime - .5f * Physics.gravity * flightTime;
        fetchBall.Launch(transform, origin, velocity);
        lastResult = "The player threw the ball. Search for it.";
        status = "Ball thrown! It stops where it lands. Give your dog a command.";
    }

    public void Cancel()
    {
        SetCommandEditing(false);
        generation++;
        aiRunning = false;
        fetchTask = false;
        remainingPlan.Clear();
        activeStep = null;
        TaskState = "idle";
        busy = false;
        StopAllCoroutines();
        checkingHealth = false;
        visual.localRotation = Quaternion.identity;
        visual.localPosition = Vector3.zero;
        seated = false;
        ResetLegs();
        status = "Stopped. Ready for a new command.";
        lastResult = "Previous command cancelled.";
    }

    public void TestAction(string action)
    {
        if (busy || aiRunning) return;
        SetCommandEditing(false);
        actionSource = "Manual button";
        StartCoroutine(Execute(new DogAction { action = action, amount = action.StartsWith("turn") ? 30 : .6f }));
    }

    public IEnumerator Execute(DogAction instruction)
    {
        busy = true;
        string action = instruction.action ?? "";
        lastAction = action;
        status = "Dog: " + action.Replace('_', ' ');
        float amount = instruction.amount;
        if (float.IsNaN(amount) || float.IsInfinity(amount)) amount = .5f;
        if (action == "move_forward" || action == "move_backward")
        {
            seated = false;
            visual.localRotation = Quaternion.identity;
            float distance = Mathf.Clamp(amount, .1f, 1.5f);
            Vector3 start = dog.position;
            float remaining = distance;
            while (remaining > .00001f)
            {
                // Do not walk past a target while completing a long VLM move.
                if (fetchTask && aiRunning && InteractionReady()) break;
                float step = Mathf.Min(1.5f * Time.deltaTime, remaining);
                controller.Move(dog.forward * (action == "move_forward" ? 1 : -1) * step);
                AnimateWalk(Time.time);
                remaining -= step;
                yield return null;
            }
            lastResult = fetchTask && aiRunning && InteractionReady()
                ? (holding ? "Reached delivery range." : "Reached pickup range.")
                : Vector3.Distance(start, dog.position) < distance * .6f ? "Movement blocked by a collision." : "Movement completed.";
        }
        else if (action == "turn_left" || action == "turn_right")
        {
            float degrees = Mathf.Clamp(amount, 5, 90);
            float duration = degrees / 100;
            for (float t = 0; t < duration;)
            {
                if (fetchTask && aiRunning && InteractionReady()) break;
                float dt = Mathf.Min(Time.deltaTime, duration - t);
                dog.Rotate(0, (action == "turn_left" ? -1 : 1) * 100 * dt, 0);
                t += dt;
                yield return null;
            }
            lastResult = "Turn completed.";
        }
        else if (action == "pick_up")
        {
            Vector3 flat = ball.position - dog.position; flat.y = 0;
            bool inFront = flat.sqrMagnitude < .01f || Vector3.Dot(dog.forward, flat.normalized) > -.15f;
            if (!holding && flat.magnitude <= pickupRange && ball.position.y < 1.5f && (inFront || (fetchTask && aiRunning)))
            {
                fetchBall.Carry(mouth);
                holding = true;
                lastResult = "Pickup succeeded. Ball is in the dog's mouth. Return to the person in blue.";
            }
            else lastResult = holding ? "Already holding the ball." : "Pickup failed. Face the ball within " + pickupRange.ToString("0.0") + " m.";
        }
        else if (action == "drop")
        {
            if (!holding) lastResult = "Drop failed: not carrying the ball.";
            else
            {
                Vector3 offset = dog.position - owner.position; offset.y = 0;
                bool returned = offset.magnitude <= deliveryRange;
                if (returned) fetchDelivered = true;
                holding = false;
                fetchBall.Launch(transform, mouth.position, Vector3.zero);
                lastResult = returned ? "Fetch succeeded: ball delivered to the person." : "Ball dropped away from the person.";
            }
        }
        else if (action == "sit" || action == "stand")
        {
            seated = action == "sit";
            float from = visual.localPosition.y;
            float to = seated ? -.15f : 0;
            for (float t = 0; t < .4f; t += Time.deltaTime)
            { visual.localPosition = new Vector3(0, Mathf.Lerp(from, to, t / .4f), 0); yield return null; }
            visual.localPosition = new Vector3(0, to, 0);
            visual.localRotation = seated ? Quaternion.Euler(-12, 0, 0) : Quaternion.identity;
            lastResult = seated ? "Sit completed. Dog is sitting." : "Stand completed. Dog is standing.";
        }
        else if (action == "dance" || action == "roll")
        {
            seated = false;
            for (float t = 0; t < 2.4f; t += Time.deltaTime)
            {
                float phase = t / 2.4f;
                if (action == "roll")
                {
                    visual.localPosition = new Vector3(0, -.12f + Mathf.Sin(phase * Mathf.PI) * .25f, 0);
                    visual.localRotation = Quaternion.Euler(0, 0, phase * 360);
                }
                else
                {
                    visual.localPosition = new Vector3(0, Mathf.Abs(Mathf.Sin(t * 7)) * .25f, 0);
                    visual.localRotation = Quaternion.Euler(-20, Mathf.Sin(t * 5) * 35, Mathf.Sin(t * 9) * 12);
                    AnimateWalk(t);
                }
                yield return null;
            }
            visual.localRotation = Quaternion.identity;
            visual.localPosition = Vector3.zero;
            lastResult = action + " completed.";
        }
        else if (action == "wait")
        { yield return new WaitForSeconds(Mathf.Clamp(amount, .1f, 2)); lastResult = "Wait completed."; }
        else if (action == "finish") lastResult = instruction.source == "placeholder" ? instruction.reason
            : fetchDelivered ? "Fetch succeeded: ball delivered to the person. Task complete."
            : "Task complete.";
        else lastResult = "Rejected unknown action: " + action;
        ResetLegs();
        busy = false;
        status = lastResult;
    }

    string CaptureObservation()
    {
        // A decision must see the final heading, not the chase camera's eased pose.
        UpdateCamera(true);
        const int width=960, height=540;
        var target = RenderTexture.GetTemporary(width, height, 24);
        var previousTarget = dogCamera.targetTexture;
        var previousActive = RenderTexture.active;
        float previousAspect = dogCamera.aspect;
        Texture2D image = null;
        try
        {
            dogCamera.targetTexture = target;
            dogCamera.aspect = (float)width / height;
            dogCamera.Render();
            RenderTexture.active = target;
            image = new Texture2D(width, height, TextureFormat.RGB24, false);
            image.ReadPixels(new Rect(0, 0, width, height), 0, 0);
            image.Apply();
            return Convert.ToBase64String(image.EncodeToJPG(85));
        }
        finally
        {
            dogCamera.targetTexture = previousTarget;
            dogCamera.aspect = previousAspect;
            RenderTexture.active = previousActive;
            RenderTexture.ReleaseTemporary(target);
            if (image) Destroy(image);
        }
    }

    bool InteractionReady()
    {
        Vector3 offset = (holding ? owner.position : ball.position) - dog.position;
        offset.y = 0;
        return holding ? offset.magnitude <= deliveryRange
            : offset.magnitude <= pickupRange && ball.position.y < 1.5f;
    }

    void RefreshTaskState()
    {
        if (fetchDelivered)
        {
            remainingPlan.Clear(); activeStep = null; TaskState = "complete"; return;
        }
        while (activeStep != null && activeStep.action == "get_ball" && holding) AdvancePlan();
        if (activeStep == null) { TaskState = "complete"; return; }
        fetchTask = activeStep.action == "get_ball" || activeStep.action == "deliver_ball";
        TaskState = !fetchTask ? "perform_action"
            : holding ? (InteractionReady() ? "drop" : "approach_owner")
            : (InteractionReady() ? "pick_up" : "approach_ball");
    }

    void AdvancePlan()
    {
        activeStep = remainingPlan.Count > 0 ? remainingPlan.Dequeue() : null;
    }

    public void BeginCommand(string userCommand)
    {
        command = userCommand;
        BeginAI();
    }

    public void BeginAI()
    {
        if (string.IsNullOrWhiteSpace(command)) return;
        var pending = new List<DogPlanStep>();
        if (activeStep != null) pending.Add(activeStep);
        pending.AddRange(remainingPlan);
        string previousSession = session;
        string previousState = TaskState;
        string feedback = activeStep != null ? lastResult : "Ready for a new instruction.";
        Cancel();
        orbit = 0;
        session = Guid.NewGuid().ToString("N");
        decisions = 0;
        fetchDelivered = false;
        aiRunning = true;
        activeCommand = command;
        TaskState = "planning";
        actionSource = "VLM server";
        lastJson = "Waiting for server response…";
        StartCoroutine(PlanAndRun(generation, pending.ToArray(), previousSession, previousState, feedback));
    }

    IEnumerator PlanAndRun(int run, DogPlanStep[] pending, string previousSession, string previousState, string feedback)
    {
        var observation = new DogObservation { session_id = session, command = activeCommand, image_base64 = CaptureObservation(),
            holding_ball = holding, state = previousState, last_result = feedback, remaining_plan = pending, supersedes_session = previousSession };
        status = "Understanding your instruction…";
        using (var request = new UnityWebRequest(serverUrl.TrimEnd('/') + "/plan", "POST"))
        {
            request.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(JsonUtility.ToJson(observation)));
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            request.timeout = 180;
            yield return request.SendWebRequest();
            if (run != generation) yield break;
            lastJson = request.downloadHandler.text;
            if (request.result != UnityWebRequest.Result.Success)
            {
                status = "Could not plan the instruction. Check Server details. " + request.error;
                showDiagnostics = true; aiRunning = false; TaskState = "idle"; yield break;
            }
            DogPlan plan = null;
            try { plan = JsonUtility.FromJson<DogPlan>(lastJson); }
            catch (Exception error) { Debug.LogWarning(error.Message); }
            var supported = new HashSet<string> { "get_ball", "deliver_ball", "sit", "stand", "dance", "roll", "move_forward", "move_backward", "turn_left", "turn_right", "wait", "drop" };
            if (plan == null || plan.steps == null || plan.steps.Length > 32
                || Array.Exists(plan.steps, step => step == null || !supported.Contains(step.action) || float.IsNaN(step.amount) || float.IsInfinity(step.amount)))
            {
                status = "Server returned an invalid task plan."; aiRunning = false; TaskState = "idle"; yield break;
            }
            foreach (var step in plan.steps)
            {
                remainingPlan.Enqueue(step);
                if (step.action == "deliver_ball") break;
            }
            lastResult = "New plan accepted.";
            Debug.Log("VLM plan: " + lastJson);
            AdvancePlan();
        }
        yield return AILoop(run);
    }

    IEnumerator AILoop(int run)
    {
        aiRunning = true;
        while (aiRunning && run == generation && decisions < 80)
        {
            yield return new WaitForSeconds(.3f);
            RefreshTaskState();
            var observation = new DogObservation { session_id = session, command = activeCommand, image_base64 = CaptureObservation(), last_result = lastResult, holding_ball = holding, state = TaskState,
                requested_action = TaskState == "perform_action" ? activeStep.action : "", requested_amount = activeStep != null ? activeStep.amount : 1, step = decisions };
            status = "Looking and thinking… (decision " + (decisions + 1) + ")";
            using (var request = new UnityWebRequest(serverUrl.TrimEnd('/') + "/step", "POST"))
            {
                request.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(JsonUtility.ToJson(observation)));
                request.downloadHandler = new DownloadHandlerBuffer();
                request.SetRequestHeader("Content-Type", "application/json");
                request.timeout = 180;
                yield return request.SendWebRequest();
                if (run != generation) yield break;
                if (request.result != UnityWebRequest.Result.Success)
                {
                    status = "Server unavailable or returned an error. " + request.error + " — start Server/server.py and check its terminal.";
                    lastJson = request.downloadHandler.text;
                    if (string.IsNullOrEmpty(lastJson)) lastJson = request.error;
                    serverStatus = "Request failed — open Server details";
                    showDiagnostics = true;
                    Debug.LogWarning(status + " " + lastJson);
                    break;
                }
                lastJson = request.downloadHandler.text;
                serverStatus = "Connected • " + serverUrl;
                DogAction action = null;
                try { action = JsonUtility.FromJson<DogAction>(request.downloadHandler.text); }
                catch (Exception error) { status = "Invalid server response: " + error.Message; }
                if (action == null) break;
                bool placeholder = action.source == "placeholder";
                actionSource = placeholder ? "PLACEHOLDER demo" : action.source == "state_machine" ? "Task controller" : "VLM server";
                serverStatus = placeholder ? "PLACEHOLDER • " + action.fallback_error : "Connected • " + serverUrl;
                decisions++;
                if (!placeholder)
                {
                    bool navigation = action.action == "move_forward" || action.action == "move_backward"
                        || action.action == "turn_left" || action.action == "turn_right" || action.action == "wait";
                    bool allowed = (TaskState == "approach_ball" || TaskState == "approach_owner") ? navigation
                        : TaskState == "perform_action" ? action.action == activeStep.action
                        : TaskState == "pick_up" ? action.action == "pick_up"
                        : TaskState == "drop" ? action.action == "drop"
                        : action.action == "finish";
                    if (!allowed)
                    {
                        lastResult = "Rejected " + action.action + " during " + TaskState + ". Follow the current state.";
                        Debug.LogWarning(lastResult);
                        continue;
                    }
                }
                Debug.Log(actionSource + " decision " + decisions + ": " + JsonUtility.ToJson(action));
                yield return Execute(action);
                if (TaskState == "perform_action" && action.action == activeStep.action)
                {
                    if (lastResult.IndexOf("failed", StringComparison.OrdinalIgnoreCase) >= 0)
                    { status = "Plan stopped: " + lastResult; break; }
                    AdvancePlan();
                }
                RefreshTaskState();
                if (action.action == "finish")
                {
                    remainingPlan.Clear(); activeStep = null; command = ""; activeCommand = "";
                    break;
                }
            }
        }
        if (decisions >= 80) status = "Stopped at 80 decisions. Give a new command to continue.";
        aiRunning = false;
    }

    public IEnumerator CheckServer()
    {
        if (checkingHealth) yield break;
        checkingHealth = true;
        using (var request = UnityWebRequest.Get(serverUrl.TrimEnd('/') + "/health"))
        {
            request.timeout=4;
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success) serverStatus = "Server offline • start Server/server.py";
            else
            {
                var health = JsonUtility.FromJson<BridgeHealth>(request.downloadHandler.text);
                serverStatus = health.provider + " / " + health.model;
                if (health.provider == "openai")
                    serverStatus += health.key_configured ? " • key configured" : " • API key missing";
                else if (health.provider == "ollama")
                    serverStatus += " • no API key required";
                if (health.mode == "placeholder") serverStatus = "PLACEHOLDER mode • scripted demos, no API calls";
                else if (health.fallback_enabled) serverStatus += " • fallback enabled";
            }
        }
        checkingHealth = false;
    }

    void Styles()
    {
        if (titleStyle != null) return;
        titleStyle = new GUIStyle(GUI.skin.label) { fontSize = 25, fontStyle = FontStyle.Bold, normal = { textColor = Color.white } };
        bodyStyle = new GUIStyle(GUI.skin.label) { fontSize = 15, wordWrap = true, normal = { textColor = new Color(.88f, .93f, .94f) } };
        smallStyle = new GUIStyle(bodyStyle) { fontSize = 12 };
        buttonStyle = new GUIStyle(GUI.skin.button) { fontSize = 14, padding = new RectOffset(10, 10, 8, 8) };
        inputStyle = new GUIStyle(GUI.skin.textField) { fontSize = 16, padding = new RectOffset(12, 12, 10, 10) };
    }

    void Panel(Rect area)
    {
        Color previous = GUI.color;
        GUI.color = new Color(.055f, .09f, .12f, .94f);
        GUI.DrawTexture(area, Texture2D.whiteTexture);
        GUI.color = previous;
    }

    void OnGUI()
    {
        if (!dog) return;
        Styles();
        float scale = Mathf.Min(Screen.width / 1280f, Screen.height / 720f);
        GUI.matrix = Matrix4x4.TRS(Vector3.zero, Quaternion.identity, Vector3.one * scale);
        float width = Screen.width / scale, height = Screen.height / scale;
        if (Event.current.type == EventType.MouseDown)
            SetCommandEditing(CommandRect(width,height).Contains(Event.current.mousePosition));
        if (Event.current.type == EventType.KeyDown && editingCommand &&
            (Event.current.keyCode == KeyCode.Return || Event.current.keyCode == KeyCode.KeypadEnter || Event.current.keyCode == KeyCode.Escape))
        { SetCommandEditing(false); Event.current.Use(); }
        if (clearKeyboardFocus) { GUI.FocusControl(null); GUIUtility.keyboardControl=0; clearKeyboardFocus=false; }
        Panel(new Rect(20, 20, 370, 100));
        GUI.Label(new Rect(36, 29, 345, 40), "WHO'S A GOOD BOY?", titleStyle);
        GUI.Label(new Rect(36, 71, 340, 45), "A vision-guided dog fetch simulator\nThrow. Command. Observe.", smallStyle);
        Panel(new Rect(width - 300, 20, 280, 125));
        GUI.Label(new Rect(width - 284, 32, 250, 105), "DOG STATUS\n" + (aiRunning || TaskState == "complete" ? TaskState == "perform_action" ? activeStep?.action : TaskState.Replace('_', ' ') : holding ? "Carrying red ball" : seated ? "Sitting" : "Ready to explore") + "\n" + actionSource + ": " + lastAction + "\nServer decisions: " + decisions, bodyStyle);

        Panel(new Rect(410, 20, width - 730, 100));
        GUI.Label(new Rect(425, 29, width-760, 40), serverStatus, smallStyle);
        if (GUI.Button(new Rect(425, 76, 145, 29), showDiagnostics ? "Hide server details" : "Server details")) showDiagnostics = !showDiagnostics;
        if (GUI.Button(new Rect(580, 76, 90, 29), "Reconnect")) StartCoroutine(CheckServer());
        if (showDiagnostics)
        {
            Panel(new Rect(20, 155, 560, 185));
            GUI.Label(new Rect(35, 165, 530, 25), "LAST SERVER JSON  •  " + serverUrl + "/step", smallStyle);
            GUI.Label(new Rect(35, 195, 530, 100), lastJson, GUI.skin.textArea);
            GUI.Label(new Rect(35, 302, 530, 25), "Camera image → Python → vision API → JSON → dog action", smallStyle);
        }
        Vector3 ballOffset = ball.position-dog.position; ballOffset.y=0;
        Vector3 ownerOffset = owner.position-dog.position; ownerOffset.y=0;
        string proximity = holding ? "Owner: " + ownerOffset.magnitude.ToString("0.0") + " m • drop within " + deliveryRange + " m"
            : "Ball: " + ballOffset.magnitude.ToString("0.0") + " m • pick up within " + pickupRange + " m";
        Panel(new Rect(20, height - 261, 450, 32));
        GUI.Label(new Rect(36, height - 258, 425, 26), proximity, bodyStyle);
        Panel(new Rect(20, height - 225, width - 40, 205));
        GUI.Label(new Rect(36, height - 215, width - 72, 45), status, bodyStyle);
        GUI.enabled = true;
        GUI.SetNextControlName("DogCommand");
        command = GUI.TextField(CommandRect(width,height), command, inputStyle);
        if (GUI.Button(new Rect(width - 180, height - 163, 144, 40), aiRunning ? "UPDATE TASK" : "ASK DOG / VLM", buttonStyle)) BeginAI();
        GUI.enabled = !busy && !aiRunning;
        string[] labels = { "Throw random", "Sit", "Stand", "Dance", "Roll", "Pick up", "Drop" };
        string[] actions = { "", "sit", "stand", "dance", "roll", "pick_up", "drop" };
        for (int i = 0; i < labels.Length; i++)
            if (GUI.Button(new Rect(36 + i * 133, height - 110, 123, 35), labels[i], buttonStyle))
            { SetCommandEditing(false); if (i == 0) ThrowBall(); else TestAction(actions[i]); }
        GUI.enabled = true;
        if (GUI.Button(new Rect(width - 180, height - 110, 144, 35), "STOP / ESC", buttonStyle)) Cancel();
        string hint = editingCommand ? "Typing command • WASD paused • Enter / Esc or click outside the command box to return to movement."
            : aiRunning || busy ? "Dog is executing an action • Esc stops it and restores WASD."
            : "WASD READY • W/S walk • A/D turn • Click floor to throw • T random throw • Right mouse orbit • Click the command box to type.";
        GUI.Label(new Rect(36, height - 62, width - 72, 32), hint, smallStyle);
        // IMGUI may auto-focus its first text control. Only an intentional edit owns WASD.
        if (!editingCommand) { GUI.FocusControl(null); GUIUtility.keyboardControl=0; }
        // Restore normal coordinates for any other UI.
        GUI.matrix = Matrix4x4.identity;
    }
}
