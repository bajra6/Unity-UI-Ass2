"""Unity -> online vision API bridge. Python 3.10+, no pip dependencies.

Run: python server.py --model gpt-6.1-terra
Set OPENAI_API_KEY in the server environment. Keys never enter Unity or screenshots.
No game object coordinates are provided to the model.
"""
import argparse
import base64
import json
import math
import os
import re
from pathlib import Path
import threading
import uuid
from datetime import datetime, timezone
import urllib.error
import urllib.request
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.client import HTTPException
from placeholder import make_plan, next_action

ACTIONS = (
    "move_forward", "move_backward", "turn_left", "turn_right", "pick_up",
    "drop", "sit", "stand", "dance", "roll", "wait", "finish",
)
SCHEMA = {
    "type": "object",
    "properties": {
        # Describe the current visual evidence before committing to a movement.
        "reason": {"type": "string"},
        "action": {"type": "string", "enum": list(ACTIONS)},
        "amount": {"type": "number"},
    },
    "required": ["reason", "action", "amount"],
    "additionalProperties": False,
}
SYSTEM = """You control a dog in a white 3D room, using the attached chase-camera image.
The golden dog is at the bottom center, looking toward the center of the image.
The large red ball is the object to fetch. It stops on landing; it does not roll.
The person wearing blue is its owner.
Choose exactly ONE next action using the JSON schema below. Never invent coordinates.
move_forward/move_backward: amount is meters, 0.1 to 1.5.
turn_left/turn_right: amount is degrees, 5 to 90. Left means the dog's left.
pick_up: face the red ball and approach within 2 meters of the dog's center.
drop: after carrying the ball back within 3 meters of the person in blue.
sit, stand, dance, roll are completed animations. If requested first, do them once before fetching.
wait: amount is seconds, 0.1 to 2. finish: only when the user's whole task is complete.
Ground every decision in the CURRENT image. Previous decisions are not evidence of
where an object is now. Never claim the ball is visible based only on history.
For fetching, while Carrying ball is False, your target is ONLY the red ball, not the owner.
Only after a successful pickup and Carrying ball is True should you seek the blue owner.
If the target is genuinely absent from the current image, turn 45 degrees to search.
If it is visible, do NOT use a 45-degree search turn. Align with small 5-15 degree turns:
target left of the dog's forward direction -> turn_left; right -> turn_right.
If the target is already ahead, move_forward, not another search turn. When aligned
and far away, use 1.0-1.5 meter steps. Shorten to 0.3-0.6 meters near the target and
try pick_up when close. Recheck the image after each action.
There is no task requiring you to go to the center of the room.
Read the latest action feedback; a failed pickup means you are NOT carrying the ball.
While carrying the ball, search for the person in blue, approach, and drop it.
Do not repeat a completed dance/roll/sit unless the user asks for repetition.
In reason, briefly state what target you actually see (left/ahead/right/not visible)
and why this action follows. Return only JSON, with action, amount, and reason. Schema:
""" + json.dumps(SCHEMA)

RETURN_SYSTEM = """You control the golden dog using the CURRENT chase-camera image.
Your current task is to go to the PERSON WEARING BLUE and drop the carried ball near them.
Pickup is already complete. The red ball touching the dog's head is attached to its mouth.
Ignore that red ball for navigation. The person in blue is your ONLY destination.
Navigate to the person exactly as you approached the ball:
1. Look for the person in the current image, not in previous descriptions.
2. If absent, turn 45 degrees to search. Keep searching in the same direction until visible.
3. If visible LEFT of the dog's forward direction, turn_left 10-20 degrees.
   If visible RIGHT, turn_right 10-20 degrees. Align before walking; do not walk past them.
4. If ahead and far away, move_forward 1.0-1.5 meters. If nearby, use 0.3-0.6 meters.
5. When close (within 3 meters), try drop. Read its feedback before finishing.
Never pick_up again. Do not approach the ball attached to your mouth.
Choose exactly ONE action. Movement amount is meters (0.1-1.5), turn amount is degrees
(5-90), wait amount is seconds (0.1-2). Return JSON with action, amount, and reason.
In reason, describe the PERSON's current position (left/ahead/right/not visible).
Schema:
""" + json.dumps(SCHEMA)

NAVIGATION_ACTIONS = ("move_forward", "move_backward", "turn_left", "turn_right", "wait")
FETCH_STATES = ("perform_action", "approach_ball", "pick_up", "approach_owner", "drop", "complete")
ANIMATION_ACTIONS = ("sit", "stand", "dance", "roll")
PLAN_ACTIONS = ("get_ball", "deliver_ball", *ANIMATION_ACTIONS, *NAVIGATION_ACTIONS, "drop")
PRIMITIVE_ACTIONS = (*ANIMATION_ACTIONS, *NAVIGATION_ACTIONS, "drop")
PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "reason": {"type": "string"},
        "steps": {"type": "array", "maxItems": 32, "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"action": {"type": "string", "enum": list(PLAN_ACTIONS)}, "amount": {"type": "number"}},
            "required": ["action", "amount"]}},
    }, "required": ["reason", "steps"],
}
PLAN_SYSTEM = """Interpret the user's instruction into an ordered plan for a dog simulator.
Use the screenshot, carrying state and remaining plan to understand the situation.
Available skills: get_ball (navigate to and pick up the red ball), deliver_ball
(navigate to the blue owner with the carried ball and drop it), sit, stand, dance,
roll, move_forward, move_backward, turn_left, turn_right, wait, drop (release here).
A FETCH means BOTH pickup AND return: get_ball then deliver_ball. If already carrying, use deliver_ball only.
get_ball is pickup only. deliver_ball is the COMPLETE return trip, not a single movement.
Do not substitute move_forward for deliver_ball, including when the user says "continue bringing it back".
Navigation is built into these two skills. NEVER insert move/turn steps around them unless
the user explicitly requests a particular movement, distance or turn in addition to fetching.
Preserve explicitly requested ordering: animations may come before acquisition,
between pickup and delivery, or replace the current task. Do not omit requested actions.
Repeated actions should be separate steps. Maximum 32 steps.
New instructions can interrupt an existing task. If asked to resume/continue, preserve the
unfinished relevant steps after the new action. If asked to stop, replace, or forget the
task, discard those steps. Use the meaning of the new instruction; do not blindly append.
Successful delivery ENDS THE ENTIRE TASK and clears context. Discard any steps after
deliver_ball, even if requested. A future task will require a new instruction.
For example, "fetch then do an animation" ends with get_ball, deliver_ball; no animation follows.
"Do an animation then continue returning" while carrying means that animation, deliver_ball.
Use amount=1 for get_ball/deliver_ball/animations/drop. Movement amount is meters
(0.1-1.5); turns are degrees (5-90); waits are seconds (0.1-2). Split longer requests.
An instruction to stop has an empty steps list. Do not invent unsupported skills.
Return JSON with a short reason and the ordered steps. This is planning only;
do not invent a navigation path to the ball or owner: those skills use fresh images.
"""

def validate_plan(value):
    if not isinstance(value, dict) or not isinstance(value.get("steps"), list) or len(value["steps"]) > 32:
        raise ValueError("Model must return a plan of at most 32 steps")
    steps = []
    for step in value["steps"]:
        if not isinstance(step, dict) or step.get("action") not in PLAN_ACTIONS:
            raise ValueError("Plan contains an unsupported skill")
        if step["action"] in ("get_ball", "deliver_ball"):
            steps.append({"action": step["action"], "amount": 1})
        else:
            action = validate_action(step)
            steps.append({"action": action["action"], "amount": action["amount"]})
        if step["action"] == "deliver_ball":
            break  # Delivery always terminates the task, including queued instructions.
    return {"reason": str(value.get("reason", ""))[:500], "steps": steps, "source": "vlm"}
STATE_GOALS = {
    "perform_action": "Complete the requested animation before advancing the fetch task.",
    "approach_ball": "Approach the RED BALL on the floor. Ignore the person for now.",
    "pick_up": "The ball is within pickup range. Pick it up now; do not move or turn.",
    "approach_owner": "Approach the PERSON IN BLUE. The ball is already in your mouth; ignore it for navigation.",
    "drop": "The owner is within delivery range. Drop the ball now; do not move or turn.",
    "complete": "The ball was successfully delivered. Finish the fetch task.",
}
NAVIGATION_SYSTEM = """You guide the golden dog using the CURRENT chase-camera image.
Unity owns the fetch task state. Follow ONLY the current state's goal, not later goals.
The camera is behind the dog. Compare the target with the dog's forward direction.
Describe where the current target is in reason FIRST, then choose ONE matching action.
If the target is absent, turn 45 degrees to search. Keep the same search direction until found.
If the target is visible to the left, turn_left; if to the right, turn_right.
Use 5-15 degree alignment turns (up to 30 for a target far to one side).
If aligned and far away, move_forward 1.0-1.5 meters. Use 0.3-0.6 meters when near.
Do not turn away from a visible, aligned target. Do not go to the center of the room.
Movement amount is meters (0.1-1.5); turn amount is degrees (5-90); wait is seconds (0.1-2).
Unity stops movement at interaction range and handles pickup, drop and completion.
You only navigate. Never choose pick_up, drop or finish during an approach state.
Do not copy previous visual claims or invent coordinates. Inspect the new image each time.
"""

def schema_for_state(state):
    if state not in ("approach_ball", "approach_owner"):
        return SCHEMA
    return {**SCHEMA, "properties": {**SCHEMA["properties"],
                                    "action": {"type": "string", "enum": list(NAVIGATION_ACTIONS)}}}


def validate_action(value):
    if not isinstance(value, dict) or value.get("action") not in ACTIONS:
        raise ValueError("Model returned an unsupported action")
    amount = value.get("amount", .5)
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount):
        raise ValueError("Action amount must be a finite number")
    action = value["action"]
    if action.startswith("turn_"):
        amount = max(5, min(90, amount))
    elif action.startswith("move_"):
        amount = max(.1, min(1.5, amount))
    else:
        amount = max(.1, min(2, amount))
    return {"action": action, "amount": amount, "reason": str(value.get("reason", ""))[:300]}


class VisionBridge:
    def __init__(self, model, api_url="https://api.openai.com/v1", provider="openai", api_key=None, trace_dir=None, mode="auto", api_timeout=30):
        self.mode = mode
        self.api_timeout = api_timeout
        self.fallback_sessions = {}
        self.model = model
        self.api_url = api_url.rstrip("/")
        self.provider = provider
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
        self.sessions = OrderedDict()
        self.lock = threading.Lock()
        self.trace_dir = Path(trace_dir) if trace_dir else None
        self.last_model_response = None
        self.current_state = "command"

    def plan(self, observation):
        if not isinstance(observation, dict):
            raise ValueError("Planning request must be an object")
        session, command, image = (observation.get(k, "") for k in ("session_id", "command", "image_base64"))
        if not isinstance(session, str) or not session or len(session) > 100:
            raise ValueError("A session_id of at most 100 characters is required")
        if not isinstance(command, str) or not command.strip() or len(command) > 4000:
            raise ValueError("A command of at most 4000 characters is required")
        if not isinstance(image, str):
            raise ValueError("A camera image is required")
        raw = base64.b64decode(image, validate=True)
        if not raw.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")):
            raise ValueError("Image must be JPEG or PNG")
        pending = validate_plan({"steps": observation.get("remaining_plan") or []})["steps"]
        with self.lock:
            old = observation.get("supersedes_session")
            if isinstance(old, str):
                self.sessions.pop(old, None)
                self.fallback_sessions.pop(old, None)
            self.sessions.pop(session, None)
            self.fallback_sessions.pop(session, None)
            self.current_state = "planning"
            self.last_model_response = None
            messages = [{"role": "system", "content": PLAN_SYSTEM + "\nSchema: " + json.dumps(PLAN_SCHEMA)},
                        {"role": "user", "content": f"New instruction: {command}\n"
                         f"Carrying ball: {bool(observation.get('holding_ball'))}\n"
                         f"Current state: {observation.get('state', 'idle')}\n"
                         f"Latest result: {str(observation.get('last_result', ''))[:1000]}\n"
                         f"Remaining plan: {json.dumps(pending)}\nInterpret the new instruction and return the revised plan.",
                         "images": [image]}]
            trace = self._trace_observation(observation, raw, messages)
            try:
                plan = validate_plan(self._model_json(messages, raw, image, PLAN_SCHEMA, "dog_plan"))
            except (ValueError, TypeError, KeyError, OSError, HTTPException):
                self._trace_result(trace, error="Planning failed. No task actions were started.")
                raise
            self._trace_result(trace, plan=plan)
            print(f"[{session[:8]}] Plan: " + " -> ".join(s["action"] for s in plan["steps"]), flush=True)
            return plan

    def step(self, observation):
        if not isinstance(observation, dict):
            raise ValueError("Observation must be a JSON object")
        session = observation.get("session_id", "")
        command = observation.get("command", "")
        state = observation.get("state") or "command"
        if state not in ("command", *FETCH_STATES):
            raise ValueError("Unknown task state")
        requested_action = observation.get("requested_action", "")
        if state == "perform_action" and requested_action not in PRIMITIVE_ACTIONS:
            raise ValueError("perform_action requires a supported requested_action")
        image = observation.get("image_base64", "")
        if not isinstance(session, str) or not session or len(session) > 100:
            raise ValueError("A session_id of at most 100 characters is required")
        if not isinstance(command, str) or not command.strip() or len(command) > 4000:
            raise ValueError("A command of at most 4000 characters is required")
        if not isinstance(image, str) or not image:
            raise ValueError("A camera image is required")
        try:
            raw_image = base64.b64decode(image, validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError("Image must be valid base64") from error
        if not raw_image.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")):
            raise ValueError("Image must be JPEG or PNG")
        with self.lock:
            self.current_state = state
            previous = self.sessions.get(session, [])
            # Keep only recent actions/results. Refeeding the model's own visual
            # claims made it repeat stale "ball is left" explanations indefinitely.
            history = "\n".join(previous[-8:]) or "No actions yet."
            feedback = str(observation.get("last_result", ""))[:1000]
            holding = bool(observation.get("holding_ball", observation.get("holding_baton", False)))
            returning = holding and bool(re.search(r"\b(fetch|bring|retrieve|deliver|return)\b", command, re.I))
            active_command = ("Find the person in blue, approach them, and drop the ball you are carrying."
                              if returning else command)
            stage = ("Ball is carried: find the blue owner, approach, then drop. "
                     "The red ball is ALREADY attached to your mouth and moves with you. "
                     "Ignore that red ball for navigation. Your ONLY navigation target is the PERSON IN BLUE. "
                     "When the person is close, try drop. Never pick_up while carrying."
                     if holding else "Ball is NOT carried: find and pick up the red ball. Do not seek the owner yet.")
            if feedback.startswith("Fetch succeeded"):
                stage = "Delivery succeeded. Finish if the user's requested actions are complete."
            completed = [name for name in ("dance", "roll", "sit", "stand")
                         if any(line.lower().startswith("feedback: " + name + " completed")
                                for line in previous + ["Feedback: " + feedback])]
            current_state = "AUTHORITATIVE CURRENT STATE: Carrying ball: " + str(holding) + ".\nIf fetching: " + stage
            # Give the return leg its own target-focused instruction, rather than
            # repeating "find the red ball" and all the approach actions after pickup.
            if returning:
                history = "Pickup is complete. Navigate to the owner using the current image."
            messages = [
                {"role": "system", "content": (RETURN_SYSTEM if returning else SYSTEM) + "\n\n" + current_state},
                {"role": "user", "content": (
                    f"Current instruction: {active_command}\n"
                    f"Animations already completed in this task: {', '.join(completed) or 'none'}\n"
                    f"Recent decisions and feedback:\n{history}\n"
                    f"Latest action result: {feedback}\n"
                    f"Carrying ball: {holding}\n"
                    f"If the command includes fetching, current stage: {stage}\n"
                    "Inspect the attached CURRENT image afresh. Is the current target visible, "
                    "and is it left, ahead, or right? Choose one action from this image, "
                    "not by repeating the previous action.\n\n" + current_state
                ), "images": [image]},
            ]
            if state in FETCH_STATES:
                goal = (f"Perform {requested_action} now. Finish this planned action before advancing."
                        if state == "perform_action" else STATE_GOALS[state])
                if state == "complete" and not feedback.startswith("Fetch succeeded"):
                    goal = "All planned actions are complete. Finish the task and clear its context."
                # State transitions, not old action sequences, define the next subtask.
                messages = [
                    {"role": "system", "content": NAVIGATION_SYSTEM + "\nCURRENT STATE: " + state
                     + "\nCURRENT GOAL: " + goal + "\nSchema: " + json.dumps(schema_for_state(state))},
                    {"role": "user", "content": f"Original user request (overall context): {command}\n"
                     f"State: {state}\nCarrying ball: {holding}\nLatest action result: {feedback}\n"
                     f"Current instruction: {goal}\nInspect this screenshot and choose the next action for this state only.",
                     "images": [image]},
                ]
            self.last_model_response = None
            trace = self._trace_observation(observation, raw_image, messages)
            if state in ("perform_action", "pick_up", "drop", "complete") and self.mode != "placeholder" and session not in self.fallback_sessions:
                amount = observation.get("requested_amount", 1) if state == "perform_action" else .1
                primitive = validate_action({"action": requested_action, "amount": amount}) if state == "perform_action" else None
                action = {"action": requested_action if state == "perform_action" else "finish" if state == "complete" else state, "amount": primitive["amount"] if primitive else .1,
                          "reason": goal, "source": "state_machine"}
            elif session in self.fallback_sessions:
                action = next_action(self.fallback_sessions[session])
            else:
                error = "Placeholder mode selected." if self.mode == "placeholder" else None
                if error is None:
                    try:
                        action = self._model_action(messages, raw_image, image)
                        action["source"] = "vlm"
                    except (ValueError, TypeError, KeyError, AttributeError, OSError, urllib.error.URLError, HTTPException) as failure:
                        # Never echo provider bodies, headers or credentials in fallback metadata.
                        if isinstance(failure, urllib.error.HTTPError):
                            error = f"Vision API returned HTTP {failure.code}."
                        elif not self.api_key and self.provider == "openai":
                            error = "OPENAI_API_KEY is not configured."
                        elif isinstance(failure, (OSError, urllib.error.URLError, HTTPException)):
                            error = "Vision API unavailable or timed out."
                        else:
                            error = "Vision API returned an invalid action."
                        if self.mode == "live":
                            self._trace_result(trace, error=error)
                            raise
                if error is not None:
                    plan, fetch = make_plan(command, history + "\n" + str(observation.get("last_result", "")))
                    self.fallback_sessions[session] = {"plan": plan, "fetch": fetch, "cursor": 0, "error": error}
                    print(f"[{session[:8]}] PLACEHOLDER fallback: {error}", flush=True)
                    action = next_action(self.fallback_sessions[session])
            previous.append("Feedback: " + str(observation.get("last_result", ""))[:1000])
            previous.append("Decision: " + json.dumps({"action": action["action"], "amount": action["amount"]}))
            self.sessions[session] = previous[-160:]
            self.sessions.move_to_end(session)
            if state == "complete":
                self.sessions.pop(session, None)
                self.fallback_sessions.pop(session, None)
                if trace is not None:
                    trace["context_cleared"] = True
            self._trace_result(trace, action=action)
            while len(self.sessions) > 32:
                expired, _ = self.sessions.popitem(last=False)
                self.fallback_sessions.pop(expired, None)
            print(f"[{session[:8]}] {action['action']} {action['amount']}: {action['reason']}", flush=True)
            return action

    def _trace_observation(self, observation, raw_image, messages):
        """Save the exact received bytes BEFORE inference, even if inference fails."""
        if not self.trace_dir:
            return None
        folder = self.trace_dir / "observations"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc)
        extension = ".png" if raw_image.startswith(b"\x89PNG") else ".jpg"
        name = stamp.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
        image_path = folder / (name + extension)
        image_path.write_bytes(raw_image)
        (self.trace_dir / ("latest-observation" + extension)).write_bytes(raw_image)
        record = {"session": observation["session_id"], "step": observation.get("step"),
                  "timestamp_utc": stamp.isoformat(), "command": observation["command"],
                  "previous_result": observation.get("last_result"),
                  "holding_ball": bool(observation.get("holding_ball", observation.get("holding_baton", False))),
                  "state": self.current_state,
                  "requested_action": observation.get("requested_action", ""),
                  "provider": self.provider, "model": self.model,
                  "image_file": image_path.relative_to(self.trace_dir).as_posix(),
                  "system_prompt": messages[0]["content"],
                  "prompt": messages[1]["content"], "status": "pending", "action": None,
                  "model_response": None}
        self._save_trace_record(record)
        print(f"[{observation['session_id'][:8]}] Observation: {image_path.resolve()}", flush=True)
        return record

    def _save_trace_record(self, record):
        data = json.dumps(record, indent=2)
        (self.trace_dir / record["image_file"]).with_suffix(".json").write_text(data, encoding="utf-8")
        (self.trace_dir / "latest-action.json").write_text(data, encoding="utf-8")

    def _trace_result(self, record, action=None, error=None, plan=None):
        if record is None:
            return
        record.update(status="error" if error else "completed", action=action,
                      model_response=self.last_model_response)
        if error:
            record["error"] = error
        if plan is not None:
            record["plan"] = plan
        self._save_trace_record(record)
        with (self.trace_dir / "decisions.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(record) + "\n")


    def _model_action(self, messages, raw_image, image):
        schema = schema_for_state(self.current_state)
        action = validate_action(self._model_json(messages, raw_image, image, schema))
        if action["action"] not in schema["properties"]["action"]["enum"]:
            raise ValueError("Model action is not allowed in the current task state")
        return action

    def _model_json(self, messages, raw_image, image, schema, name="dog_action"):
        headers = {"Content-Type": "application/json"}
        if self.provider == "openai":
            if not self.api_key:
                raise ValueError("Set OPENAI_API_KEY in the Python server environment. ChatGPT Plus is not an API key.")
            mime = "image/png" if raw_image.startswith(b"\x89PNG") else "image/jpeg"
            payload = {
                "model": self.model, "instructions": messages[0]["content"], "store": False,
                "input": [{"role": "user", "content": [
                    {"type": "input_text", "text": messages[1]["content"]},
                    {"type": "input_image", "image_url": f"data:{mime};base64,{image}", "detail": "auto"},
                ]}],
                "text": {"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}},
                "reasoning": {"effort": "low"}, "max_output_tokens": 1200,
            }
            headers["Authorization"] = "Bearer " + self.api_key
            endpoint = self.api_url + "/responses"
        else:
            payload = {"model": self.model, "messages": messages, "stream": False,
                       "format": schema, "options": {"temperature": 0, "num_predict": 1200 if name == "dog_plan" else 200}}
            endpoint = self.api_url + "/api/chat"
        request = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(request, timeout=self.api_timeout) as response:
            answer = json.load(response)
        if self.provider == "openai":
            texts = [part["text"] for item in answer.get("output", [])
                     if item.get("type") == "message" for part in item.get("content", [])
                     if part.get("type") == "output_text"]
            if answer.get("status") == "incomplete" or not texts:
                raise ValueError("Vision API returned no complete action. Check the model, token limit, and API response.")
            content = "".join(texts)
        else:
            content = answer["message"]["content"]
        # Preserve the actual model text alongside the validated/clamped action.
        self.last_model_response = content
        return json.loads(content)


def make_handler(bridge):
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, code, value):
            data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if self.path == "/health":
                self.send_json(200, {"status": "ok", "model": bridge.model, "provider": bridge.provider,
                                     "mode": bridge.mode, "fallback_enabled": bridge.mode != "live",
                                     "key_configured": bool(bridge.api_key) if bridge.provider == "openai" else None,
                                     "note": "Bridge health does not confirm API credits or model availability."})
            else:
                self.send_json(404, {"error": "Unknown endpoint"})

        def do_POST(self):
            if self.path not in ("/step", "/plan"):
                self.send_json(404, {"error": "Unknown endpoint"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 4_000_000:
                    raise ValueError("Request body must be between 1 byte and 4 MB")
                observation = json.loads(self.rfile.read(length))
                self.send_json(200, bridge.plan(observation) if self.path == "/plan" else bridge.step(observation))
            except (ValueError, TypeError) as error:
                self.send_json(400, {"error": str(error)})
            except urllib.error.HTTPError as error:
                detail = error.read(2000).decode("utf-8", errors="replace")
                self.send_json(502, {"error": "Vision provider rejected the request", "detail": detail})
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                self.send_json(503, {"error": "Cannot reach the vision API. Check the server terminal and network connection.", "detail": str(error)})
            except (KeyError, json.JSONDecodeError) as error:
                self.send_json(502, {"error": "Malformed model response", "detail": str(error)})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--model", default=os.environ.get("VLM_MODEL", "gpt-6.1-terra"))
    parser.add_argument("--provider", choices=("openai", "ollama"), default="openai")
    parser.add_argument("--api-url", default=os.environ.get("VLM_API_URL", ""))
    parser.add_argument("--trace-dir", default=str(Path(__file__).parent / "trace"),
                        help="Save latest camera image and JSON decision log here; use an empty string to disable")
    parser.add_argument("--mode", choices=("auto", "placeholder", "live"), default="auto",
                        help="auto falls back if the API fails; placeholder never calls the API; live disables fallback")
    parser.add_argument("--api-timeout", type=float, default=30, help="API timeout in seconds before fallback")
    args = parser.parse_args()
    if args.api_timeout <= 0:
        parser.error("--api-timeout must be positive")
    api_url = args.api_url or ("https://api.openai.com/v1" if args.provider == "openai" else "http://127.0.0.1:11434")
    bridge = VisionBridge(args.model, api_url, args.provider, trace_dir=args.trace_dir, mode=args.mode, api_timeout=args.api_timeout)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(bridge))
    print(f"Good Boy vision bridge: http://127.0.0.1:{args.port}\nProvider: {args.provider}\nVision model: {args.model}\nNo models are downloaded.", flush=True)
    print(f"Mode: {args.mode}. Placeholder actions are scripted demos, not visual navigation.", flush=True)
    if args.provider == "openai" and not bridge.api_key:
        print("OPENAI_API_KEY is not configured. Auto mode will use labelled placeholder responses. Live mode will return an error.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
