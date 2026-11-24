# Who's a good boy?

Unity 6000.6.8f1 prototype for a vision-language-model-controlled dog.

## Play

Open `Assets/Scenes/GoodBoyFetch.unity` and press Play. The grassland and controls are generated when Play begins; the more detailed dog and owner meshes are bundled with the project.

- W/S: walk forward/backward; A/D: turn. Keyboard movement is ready at startup. Click inside the Game view if another window has focus. Only intentionally editing the command box pauses WASD; Enter/Esc or clicking outside restores it. The footer shows the current input mode.
- Click a visible floor point in the middle of the game view to throw toward it. T or **Throw random** throws toward a random point.
- Hold right mouse: orbit the chase camera during manual testing.
- Buttons: sit, stand, dance, roll, sniff, pee, pick up, drop.
- Esc or Stop: cancel the active task.
- The blue figure is the owner; the golden dog is controlled by the agent.
- Pick up while facing the red ball within **2 meters** of the dog's center. Delivery to a named recipient drops within **2 meters** of that recipient; a direct drop releases the ball here. The HUD shows the distance.
- The red ball is 52 cm across. It follows an arc when thrown, stops on first floor contact, and stays still until picked up or thrown again.
- **Server details** shows the last exact JSON response. **Reconnect** checks the Python bridge. Manual buttons are labeled separately from VLM-driven actions.

The CC0 character meshes replace the original cube dog and capsule person. A lightweight procedural dog rig drives its legs and tail; dance/roll/sit are prototype animations, not motion capture. See `ASSET_CREDITS.md` for sources and the `ArtSource` folder for the person conversion script. To regenerate prefabs after changing source art, choose **Good Boy > Rebuild Character Prefabs**.

Rendering uses high-quality SMAA edge smoothing and native Game-view resolution (dynamic resolution is off). In Unity's **Game** tab use **Free Aspect**, disable **Low Resolution Aspect Ratios**, and maximize the tab for a larger view. These settings have been applied in the current editor. Zooming a small Game-view render will still magnify its pixels.

## Vision loop

Unity captures a clean 960x540 chase-camera JPEG (without HUD), sends it with the original user command and last action result to `POST http://127.0.0.1:8000/step`, receives one JSON action, executes it, then observes again. Game coordinates and target positions are not sent to the VLM. No hidden navigation planner moves the dog to the ball.

New instructions first go to `POST /plan` with the screenshot, carrying state, and remaining plan. The VLM interprets them into ordered supported skills; Unity tracks their execution. Use **UPDATE TASK** to submit instructions during a task. Before each capture, the chase camera snaps to the current heading. Fetch skills use an explicit state machine owned by Unity:

| State sent with the screenshot | Immediate goal | Action source |
| --- | --- | --- |
| `approach_ball` | Navigate toward the red ball; ignore the owner | VLM |
| `pick_up` | Ball is within 2 m and low enough to pick up | Fetch controller; no model call |
| `approach_target` | Navigate toward the requested delivery recipient/place; ignore the carried ball | VLM |
| `drop` | Requested destination reached; release the ball and continue the plan | Task controller; no model call |
| `complete` | All requested steps succeeded; finish and clear context | Task controller; no model call |

Each request contains the original user command, screenshot, current state, carrying flag, and execution feedback. Each approach prompt gives only that state's navigation goal, with no old visual claims or ball-approach history replayed on the return leg. The VLM can choose only movement, turning, or waiting in approach states; it cannot finish early or pick/drop at the wrong stage. The HUD displays the state and labels automatic interactions as **Fetch controller**.

Both approach states allow 1.0-1.5 meter moves when far and aligned, shortening to 0.3-0.6 meters nearby. Unity checks proximity during movement and stops as soon as the interaction range is reached, avoiding an overshoot followed by more turning. Automatic fetch pickup does not require extra facing adjustment once nearby; manual pickup retains its facing check. Coordinates are used locally for proximity checks and are not sent to the model. The model describes current visual evidence before choosing its action.

Standalone and compound instructions share this planner. `perform_action` executes each planned primitive before advancing. Success means completing the entire planned instruction. Delivery finishes one step and preserves later actions, so "fetch to the pink guy, then sit" performs pickup, pink delivery, and sitting before success. "Drop it here" succeeds at the current location when carrying. A failed drop does not mark the instruction successful. Command and server history clear only when the whole plan finishes. Screenshot and response logs remain on disk.

During fetch navigation, Unity reports obstacles in the next 1.2 meters. A visible target still follows the centering rule; forward steps shorten to at most 0.3 m near walls. An actual collision, or an obstacle with no visible target, triggers large escape turns (60-90 degrees). Explicit planned movements retain their requested angles. Logs mark escape actions with `navigation_guard: "obstacle_escape"`.

The local Python bridge calls an online vision model through OpenAI's Responses API with an image and a constrained JSON schema. It keeps action history per task. By default, a missing API key, API rejection, timeout or invalid model response switches that task to a clearly labelled placeholder demo. Unity bounds action lengths, enforces pickup distance, handles collisions and stops after 80 decisions. Stop cancels local movement; an already-running model inference may finish in the server but its result is discarded.

## Start the server

Python 3.10+ is required. No pip packages are needed.

```
cd Server
python server.py --model gpt-6.1-terra
```

Set `OPENAI_API_KEY` in the server process environment before starting. Never put it in a Unity script or paste it into chat. API billing/access must be configured independently of the Unity project. ChatGPT Plus does not provide an API key or the Pro/Business API-credit benefit. The model is configurable with `--model` or `VLM_MODEL`. The default is a vision-capable API model, not a local download. `GET /health` confirms the bridge and whether a key is configured, not API credits or model availability.

An optional `--provider ollama --model YOUR_VISION_MODEL` mode is also available, but no local model is needed for the default online mode. `--api-url` selects an alternative Responses-compatible API base URL.

For local Qwen3-VL, keep Ollama running and use `python Server/server.py --provider ollama --model qwen3-vl:4b-instruct --api-url http://127.0.0.1:11434 --mode live --api-timeout 120` from the project root. `live` makes model failures visible instead of running the scripted fallback. Restart the Python bridge after changing its code.

If Unity reports `Unknown endpoint` for `/plan`, an older server may still be running on port 8000. Stop that process and start the updated bridge; editing Python files does not reload a running process. `/health` now reports `protocol_version: 4`, and Unity warns when connected to an older bridge.

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
- `Server/trace/latest-observation.jpg`: exact latest JPEG received from Unity, saved **before** asking the model, including when the model later fails. Open this to see the screenshot the model receives.
- `Server/trace/observations/`: each received screenshot is retained under a timestamped unique filename, with a matching `.json` containing session, step, task state, carrying flag, provider/model, prompts, and response/error. `model_response` is Qwen's exact response text before validation; `action` is the validated/clamped action sent to Unity, including its reason. Controller interactions have `source: "state_machine"` and no model response, because no inference was needed. The raw response is retained even if its JSON is invalid. The server prints the image path. Files accumulate until you remove them.
- `Server/trace/latest-action.json`: metadata for the latest observation, with `status` of `pending`, `completed`, or `error`. `image_file` identifies its archived screenshot; an error never retains an older action. `decisions.jsonl` records completed/failed requests. Traces include placeholder responses too. Run with `--trace-dir ""` to disable saving; the trace directory is Git-ignored and API keys are not logged.

Example server response: `{"action":"move_forward","amount":0.6,"reason":"Approach the red ball"}`. Unity moves the dog 0.6 meters, reports whether it was blocked, captures a new image, and asks for the next action.

The bridge and protocol can be tested without a real model using `python -m unittest -v` inside Server. Real visual navigation still needs to be evaluated with the chosen VLM; a syntactically valid action does not guarantee correct perception or task completion.

## Editor setup

The `Good Boy > Create Fetch Scene` menu creates a dedicated scene if absent and adds it to the build list. Existing scenes are preserved. `GoodBoySetup.CreateScene` is also callable in batch mode. `GoodBoySetup.Verify` tests movement, pickup/delivery ranges, carry alignment through animations, stationary landing, and rendering. It writes `Verification/result.json` and screenshots.

With this project open in Unity, run `python Server/verify_unity.py --project "D:\bajra\IISc\Assignment\IUI\A2\Unity-UI-Ass2" --running-editor` to additionally test both HTTP hops using a local mock vision provider. Add `--placeholder-fallback` to simulate an API outage and verify the fallback sequence. Tests also inject keyboard input to check immediate WASD, typing isolation and Enter restoring movement. They make no paid calls. A passing mock test verifies the integration, **not** the real model's visual navigation ability; evaluate that with a working local or online vision model.

Ball, owner, and described-destination approach use Qwen's `target_screen_x` and `target_screen_y` (x: left=0/right=1; y: top=0/bottom=1; both -1 when absent). The active target is the ball for pickup, then the recipient or place selected in the instruction for delivery. The forward zone is the upper half of the middle 20%: x=0.40?0.60 and y=0?0.50 inclusive. Targets to either side require a turn. A centered target below the midpoint triggers a short 0.25 m backward reposition followed by a new screenshot, not another forward stride or a search turn. Pickup/drop distance and timing are unchanged. No target world position is used for steering; Unity uses distance for pickup/delivery. The outdoor chase camera stays directly behind the dog, including near the fence. Raw visual estimates and adjusted actions remain in the trace logs.

The environment is a procedural sunny meadow with textured ground, short grass in the fetch clearing, taller grass and trees around its edges, distant hills, and a low wooden boundary fence. `GrasslandEnvironment.cs` generates it without additional asset downloads. Grass is decorative and does not block the ball; trees are outside the fetch clearing.

When the current target is absent, the server remembers the first search turn direction for that session and target. Every subsequent search turn keeps that direction, including obstacle-escape turns, until the target is visible. Seeing the target, changing targets, completing the task, or submitting a new plan clears the commitment. Logs include `search_direction` on these actions.


The meadow now includes a second person wearing pink. `pee` and `sniff` work as standalone
commands or within a VLM-generated plan. Examples: "Pee here", "Go to the pink guy and pee",
"Go to the blue guy, sniff, then pee", or "Pee by the left fence". In this game's planner,
"assert dominance" means approach the pink-shirt person and pee, unless another target is specified.

The `go_to` and `deliver_ball` skills carry a `target` description. Plain fetch defaults to the blue owner only when no destination is requested; an explicit recipient always takes precedence. Named destinations use `pink_person`,
`blue_person`, or `red_ball`; other destinations are described visually. The VLM still steers
from screenshots with the upper-middle alignment rule and persistent search direction. Unity
stops within 1.2 m for go_to or 2 m for delivery to named destinations; other destinations use the model's visual `target_close`
assessment. Described destinations must be visible/reachable within the fenced area.

Pee is a timed procedural animation: turn sideways, shift weight, raise the right hind leg,
show a thin gravity-curved stream, lower the leg and return to the starting heading. At a
named destination, local interaction aiming points the stream toward it after navigation.
Sniff lowers the body and sweeps the head direction. Stop cancels both pose and stream.
These use the existing prototype mesh rig rather than motion-capture animation. New clients
require bridge protocol 4; restart your server manually after updating. Tests leave no game
server running.

Paw and toe mesh pieces are bound rigidly to their leg joint, with a smooth lower-leg-to-body weight transition. Unity verification checks that their shape is preserved during the raised-leg pee pose, so they cannot leave stretched triangles attached to the ground.
