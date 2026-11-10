# Who's a good boy?

Unity 6000.6.8f1 prototype for a vision-language-model-controlled dog.

## Play

Open `Assets/Scenes/GoodBoyFetch.unity` and press Play. The room and controls are generated when Play begins; the more detailed dog and owner meshes are bundled with the project.

- W/S: walk forward/backward; A/D: turn. Keyboard movement is ready at startup. Click inside the Game view if another window has focus. Only intentionally editing the command box pauses WASD; Enter/Esc or clicking outside restores it. The footer shows the current input mode.
- Click a visible floor point in the middle of the game view to throw toward it. T or **Throw random** throws toward a random point.
- Hold right mouse: orbit the chase camera during manual testing.
- Buttons: sit, stand, dance, roll, pick up, drop.
- Esc or Stop: cancel the active task.
- The blue figure is the owner; the golden dog is controlled by the agent.
- Pick up while facing the red ball within **2 meters** of the dog's center. Drop within **3 meters** of the owner to complete delivery. The HUD shows the distance.
- The red ball is 52 cm across. It follows an arc when thrown, stops on first floor contact, and stays still until picked up or thrown again.
- **Server details** shows the last exact JSON response. **Reconnect** checks the Python bridge. Manual buttons are labeled separately from VLM-driven actions.

The CC0 character meshes replace the original cube dog and capsule person. A lightweight procedural dog rig drives its legs and tail; dance/roll/sit are prototype animations, not motion capture. See `ASSET_CREDITS.md` for sources and the `ArtSource` folder for the person conversion script. To regenerate prefabs after changing source art, choose **Good Boy > Rebuild Character Prefabs**.

Rendering uses high-quality SMAA edge smoothing and native Game-view resolution (dynamic resolution is off). In Unity's **Game** tab use **Free Aspect**, disable **Low Resolution Aspect Ratios**, and maximize the tab for a larger view. These settings have been applied in the current editor. Zooming a small Game-view render will still magnify its pixels.

## Vision loop

Unity captures a clean 960x540 chase-camera JPEG (without HUD), sends it with the original user command and last action result to `POST http://127.0.0.1:8000/step`, receives one JSON action, executes it, then observes again. Game coordinates and target positions are not sent to the VLM. No hidden navigation planner moves the dog to the ball.

The local Python bridge calls an online vision model through OpenAI's Responses API with an image and a constrained JSON schema. It keeps action history per task. By default, a missing API key, API rejection, timeout or invalid model response switches that task to a clearly labelled placeholder demo. Unity bounds action lengths, enforces pickup distance, handles collisions and stops after 80 decisions. Stop cancels local movement; an already-running model inference may finish in the server but its result is discarded.

## Start the server

Python 3.10+ is required. No pip packages are needed.

```
cd Server
python server.py --model gpt-6.1-terra
```

Set `OPENAI_API_KEY` in the server process environment before starting. Never put it in a Unity script or paste it into chat. API billing/access must be configured independently of the Unity project. ChatGPT Plus does not provide an API key or the Pro/Business API-credit benefit. The model is configurable with `--model` or `VLM_MODEL`. The default is a vision-capable API model, not a local download. `GET /health` confirms the bridge and whether a key is configured, not API credits or model availability.

An optional `--provider ollama --model YOUR_VISION_MODEL` mode is also available, but no local model is needed for the default online mode. `--api-url` selects an alternative Responses-compatible API base URL.

Try: "Sit." Then "Dance, then find the red ball and bring it back to the person in blue."

### Placeholder responses when the API is unavailable

Restart the server after updating its code. `python server.py` defaults to **auto** mode: try the API, then fall back on failure. Without an API key it falls back immediately. A stalled API times out after 30 seconds (configurable with `--api-timeout`). Once a task falls back, its remaining steps stay in placeholder mode; a new command tries the API again.

- `python server.py --mode placeholder`: always use scripted responses; no external API calls or key required.
- `python server.py --mode live`: disable fallback so API errors are returned directly.
- `Server/placeholder.py`: edit the short demo action sequences here.

The placeholder recognizes simple actions such as sit, stand, dance, roll, forward/backward and left/right. A fetch request runs a short movement demonstration and stops. It **does not read the screenshot, locate the ball, or complete a real fetch**. The HUD and JSON show `source: "placeholder"`, the fallback cause, and an honest completion message. For example, try "Dance then fetch" to test the server-to-Unity action loop without a key.

## Inspect the integration

- `Server/server.py`: `SYSTEM` defines what the model can do; `VisionBridge.step()` sends the screenshot to the online model and validates its JSON output.
- `Assets/GoodBoy/Scripts/GoodBoyGame.cs`: `AILoop()` sends observations and receives responses; `Execute()` maps the JSON action to actual Unity movement/animations. The HUD distinguishes real VLM responses from placeholder demos.
- `Assets/GoodBoy/Scripts/FetchBall.cs`: handles flight, stationary landing and mouth attachment. Carrying disables interpolation and collision physics; dropping restores flight physics.
- `Server/trace/latest-observation.jpg`: latest successfully processed camera input; `latest-action.json`: corresponding command, feedback and validated action; `decisions.jsonl`: history. These are written after successful model replies. Run with `--trace-dir ""` to disable saving them. API keys are never written to these files.

Example server response: `{"action":"move_forward","amount":0.6,"reason":"Approach the red ball"}`. Unity moves the dog 0.6 meters, reports whether it was blocked, captures a new image, and asks for the next action.

The bridge and protocol can be tested without a real model using `python -m unittest -v` inside Server. Real visual navigation still needs to be evaluated with the chosen VLM; a syntactically valid action does not guarantee correct perception or task completion.

## Editor setup

The `Good Boy > Create Fetch Scene` menu creates a dedicated scene if absent and adds it to the build list. Existing scenes are preserved. `GoodBoySetup.CreateScene` is also callable in batch mode. `GoodBoySetup.Verify` tests movement, pickup/delivery ranges, carry alignment through animations, stationary landing, and rendering. It writes `Verification/result.json` and screenshots.

With this project open in Unity, run `python Server/verify_unity.py --project "D:\Apps\Unity\Who's a good boy" --running-editor` to additionally test both HTTP hops using a local mock vision provider. Add `--placeholder-fallback` to simulate an API outage and verify the fallback sequence. Tests also inject keyboard input to check immediate WASD, typing isolation and Enter restoring movement. They make no paid calls. A passing mock test verifies the integration, **not** the real model's visual navigation ability; that still requires a funded API key.
