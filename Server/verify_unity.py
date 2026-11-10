"""Run Unity and both HTTP hops using a mocked online provider; no paid API calls."""
import argparse
import base64
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from server import VisionBridge, make_handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--unity")
    parser.add_argument("--running-editor", action="store_true")
    parser.add_argument("--placeholder-fallback", action="store_true", help="Simulate an HTTP 503 and verify server fallback in Unity")
    args = parser.parse_args()
    observations = []

    class MockVision(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            url = request["input"][0]["content"][1]["image_url"]
            image = base64.b64decode(url.split(",", 1)[1], validate=True)
            if not image.startswith(b"\xff\xd8\xff") or len(image) < 10000:
                self.send_error(400, "Expected a real camera JPEG")
                return
            observations.append(len(image))
            if args.placeholder_fallback:
                self.send_error(503,"Simulated API outage")
                return
            sequence = [("dance",1),("move_forward",.6),("turn_right",30),("finish",1)]
            name,amount=sequence[min(len(observations)-1,3)]
            action = {"action": name, "amount": amount, "reason": "Integration test"}
            body = json.dumps({"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(action)}]}]}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), MockVision)
    bridge = VisionBridge("mock-vision", f"http://127.0.0.1:{upstream.server_port}/v1", api_key="integration-test-only")
    local = ThreadingHTTPServer(("127.0.0.1", 0 if args.running_editor else 8000), make_handler(bridge))
    for server in (upstream, local):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        if args.running_editor:
            from unity_editor import execute
            code=f'UnityEditor.SessionState.SetString("GoodBoyVerifyUrl", "http://127.0.0.1:{local.server_port}"); UnityEditor.SessionState.SetBool("GoodBoyVerifyPlaceholder", {str(args.placeholder_fallback).lower()}); GoodBoySetup.Verify();'
            print(execute(args.project,'script eval',{'code':code}),flush=True)
            deadline=time.monotonic()+100
            path=Path(args.project)/'Verification/result.json'
            while time.monotonic()<deadline:
                if path.exists():
                    result=json.loads(path.read_text())
                    if result['status']!='running':
                        print(result,flush=True)
                        if result['status']!='passed':raise SystemExit(1)
                        break
                time.sleep(1)
            else:raise SystemExit('Unity verification timed out')
        else:
            environment = dict(os.environ, GOODBOY_VERIFY_HTTP="1", GOODBOY_VERIFY_PLACEHOLDER="1" if args.placeholder_fallback else "0")
            result = subprocess.run([
                args.unity, "-batchmode", "-projectPath", args.project,
                "-executeMethod", "GoodBoySetup.Verify", "-logFile",
                os.path.join(args.project, "verification-log.txt"),
            ], env=environment, timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:raise SystemExit(result.returncode)
        expected=1 if args.placeholder_fallback else 4
        if len(observations) != expected:
            raise SystemExit(f"Expected {expected} upstream requests, got {len(observations)}")
        print("UNITY_INTEGRATION_OK:", "API failure -> labelled placeholder movement -> finish" if args.placeholder_fallback else "four real JPEG observations -> JSON movement/actions", "No external API calls.")
        print("JPEG sizes:", observations)
    finally:
        for server in (local, upstream):
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
