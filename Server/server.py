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
from pathlib import Path
import threading
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
        "action": {"type": "string", "enum": list(ACTIONS)},
        "amount": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["action", "amount", "reason"],
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
If the target is not visible, turn 45 degrees to search. Once visible, turn toward it,
then approach in short steps. Use smaller steps when close. Read action feedback.
While carrying the ball, search for the person in blue, approach, and drop it.
Do not repeat a completed dance/roll/sit unless the user asks for repetition.
Return only JSON, with action, amount, and a short reason. Schema:
""" + json.dumps(SCHEMA)


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

    def step(self, observation):
        if not isinstance(observation, dict):
            raise ValueError("Observation must be a JSON object")
        session = observation.get("session_id", "")
        command = observation.get("command", "")
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
            previous = self.sessions.get(session, [])
            history = "\n".join(previous[-30:]) or "No actions yet."
            completed = [name for name in ("dance", "roll", "sit", "stand")
                         if any(line.startswith("Feedback: " + name + " completed")
                                or (name == "sit" and line.startswith("Feedback: Sit completed"))
                                or (name == "stand" and line.startswith("Feedback: Stand completed"))
                                for line in previous)]
            messages = [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": (
                    f"Original user command: {command}\n"
                    f"Animations already completed in this task: {', '.join(completed) or 'none'}\n"
                    f"Recent decisions and feedback:\n{history}\n"
                    f"Latest action result: {str(observation.get('last_result', ''))[:1000]}\n"
                    f"Carrying ball: {bool(observation.get('holding_ball', observation.get('holding_baton', False)))}\n"
                    "Look at the current image and choose the next action."
                ), "images": [image]},
            ]
            if session in self.fallback_sessions:
                action = next_action(self.fallback_sessions[session])
            else:
                error = "Placeholder mode selected." if self.mode == "placeholder" else None
                if error is None:
                    try:
                        action = self._model_action(messages, raw_image, image)
                        action["source"] = "vlm"
                    except (ValueError, TypeError, KeyError, AttributeError, OSError, urllib.error.URLError, HTTPException) as failure:
                        if self.mode == "live":
                            raise
                        # Never echo provider bodies, headers or credentials in fallback metadata.
                        if isinstance(failure, urllib.error.HTTPError):
                            error = f"Vision API returned HTTP {failure.code}."
                        elif not self.api_key and self.provider == "openai":
                            error = "OPENAI_API_KEY is not configured."
                        elif isinstance(failure, (OSError, urllib.error.URLError, HTTPException)):
                            error = "Vision API unavailable or timed out."
                        else:
                            error = "Vision API returned an invalid action."
                if error is not None:
                    plan, fetch = make_plan(command, history + "\n" + str(observation.get("last_result", "")))
                    self.fallback_sessions[session] = {"plan": plan, "fetch": fetch, "cursor": 0, "error": error}
                    print(f"[{session[:8]}] PLACEHOLDER fallback: {error}", flush=True)
                    action = next_action(self.fallback_sessions[session])
            if self.trace_dir:
                self.trace_dir.mkdir(parents=True, exist_ok=True)
                image_name = "latest-observation.png" if raw_image.startswith(b"\x89PNG") else "latest-observation.jpg"
                (self.trace_dir / image_name).write_bytes(raw_image)
                record = {"session": session, "step": observation.get("step"), "command": command,
                          "previous_result": observation.get("last_result"), "action": action}
                (self.trace_dir / "latest-action.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
                with (self.trace_dir / "decisions.jsonl").open("a", encoding="utf-8") as log:
                    log.write(json.dumps(record) + "\n")
            previous.append("Feedback: " + str(observation.get("last_result", ""))[:1000])
            previous.append("Decision: " + json.dumps(action))
            self.sessions[session] = previous[-160:]
            self.sessions.move_to_end(session)
            while len(self.sessions) > 32:
                expired, _ = self.sessions.popitem(last=False)
                self.fallback_sessions.pop(expired, None)
            print(f"[{session[:8]}] {action['action']} {action['amount']}: {action['reason']}", flush=True)
            return action


    def _model_action(self, messages, raw_image, image):
        headers = {"Content-Type": "application/json"}
        if self.provider == "openai":
            if not self.api_key:
                raise ValueError("Set OPENAI_API_KEY in the Python server environment. ChatGPT Plus is not an API key.")
            mime = "image/png" if raw_image.startswith(b"\x89PNG") else "image/jpeg"
            payload = {
                "model": self.model, "instructions": SYSTEM, "store": False,
                "input": [{"role": "user", "content": [
                    {"type": "input_text", "text": messages[1]["content"]},
                    {"type": "input_image", "image_url": f"data:{mime};base64,{image}", "detail": "auto"},
                ]}],
                "text": {"format": {"type": "json_schema", "name": "dog_action", "strict": True, "schema": SCHEMA}},
                "reasoning": {"effort": "low"}, "max_output_tokens": 1200,
            }
            headers["Authorization"] = "Bearer " + self.api_key
            endpoint = self.api_url + "/responses"
        else:
            payload = {"model": self.model, "messages": messages, "stream": False,
                       "format": SCHEMA, "options": {"temperature": 0, "num_predict": 200}}
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
        return validate_action(json.loads(content))


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
            if self.path != "/step":
                self.send_json(404, {"error": "Unknown endpoint"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 4_000_000:
                    raise ValueError("Request body must be between 1 byte and 4 MB")
                observation = json.loads(self.rfile.read(length))
                self.send_json(200, bridge.step(observation))
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
