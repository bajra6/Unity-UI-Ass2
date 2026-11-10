import base64
import json
import threading
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from server import VisionBridge, make_handler, validate_action


class BridgeTests(unittest.TestCase):
    def observation(self, **changes):
        return {"session_id":"fallback-test", "command":"Dance then fetch the ball",
                "image_base64":base64.b64encode(b"\xff\xd8\xfftest-image").decode(), **changes}

    def test_missing_key_runs_finite_labelled_demo_without_network(self):
        bridge=VisionBridge("test",api_key="")
        with patch("server.urllib.request.urlopen") as upstream:
            actions=[bridge.step(self.observation(step=i)) for i in range(6)]
        upstream.assert_not_called()
        self.assertEqual([a['action'] for a in actions],['dance','move_forward','turn_left','move_forward','finish','finish'])
        self.assertTrue(all(a['source']=='placeholder' for a in actions))
        self.assertIn('Fetch was not performed',actions[-1]['reason'])

    def test_api_failures_fall_back_once_per_task_and_new_task_retries(self):
        for error in (urllib.error.HTTPError('test',401,'Unauthorized',{},None),
                      urllib.error.HTTPError('test',429,'Quota',{},None),
                      TimeoutError(), ValueError('invalid model JSON')):
            with self.subTest(error=type(error).__name__):
                bridge=VisionBridge('test',api_key='test-key')
                with patch.object(bridge,'_model_action',side_effect=error) as upstream:
                    a=bridge.step(self.observation(command='sit'))
                    b=bridge.step(self.observation(command='sit',step=1))
                    self.assertEqual(upstream.call_count,1)
                    bridge.step(self.observation(session_id='new-task',command='stand'))
                    self.assertEqual(upstream.call_count,2)
                self.assertEqual(a['action'],'sit')
                self.assertEqual(b['action'],'finish')
                self.assertEqual(a['source'],'placeholder')

    def test_live_mode_and_invalid_input_do_not_silently_fall_back(self):
        with self.assertRaises(ValueError):
            VisionBridge('test',api_key='',mode='live').step(self.observation())
        bridge=VisionBridge('test',api_key='')
        with self.assertRaises(ValueError):bridge.step(self.observation(image_base64='invalid'))
        self.assertFalse(bridge.fallback_sessions)

    def test_forced_placeholder_skips_api_and_completed_animation(self):
        bridge=VisionBridge('test',api_key='test-key',mode='placeholder')
        with patch.object(bridge,'_model_action') as upstream:
            action=bridge.step(self.observation(last_result='dance completed.'))
        upstream.assert_not_called()
        self.assertEqual(action['action'],'move_forward')

    def test_rejects_unknown_and_non_finite_actions(self):
        for value in ({"action": "teleport"}, {"action": "move_forward", "amount": float("nan")}, {"action": "turn_left", "amount": True}):
            with self.assertRaises(ValueError):
                validate_action(value)

    def test_bounds_model_movements(self):
        self.assertEqual(validate_action({"action": "move_forward", "amount": 100})["amount"], 1.5)
        self.assertEqual(validate_action({"action": "turn_left", "amount": -90})["amount"], 5)

    def test_image_and_action_feedback_reach_model_and_next_decision(self):
        received = []

        class FakeOllama(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                answer = {"message": {"content": json.dumps({"action": "dance", "amount": 1, "reason": "Dance before fetching"})}}
                body = json.dumps(answer).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        ollama = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
        threading.Thread(target=ollama.serve_forever, daemon=True).start()
        bridge = VisionBridge("test-vision", f"http://127.0.0.1:{ollama.server_port}", provider="ollama")
        http = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(bridge))
        threading.Thread(target=http.serve_forever, daemon=True).start()
        image = base64.b64encode(b"\xff\xd8\xfftest-image").decode()
        observation = {"session_id": "test", "command": "Dance then fetch", "image_base64": image, "last_result": "Ready", "holding_ball": False}
        try:
            for feedback in ("Ready", "dance completed."):
                observation["last_result"] = feedback
                request = urllib.request.Request(f"http://127.0.0.1:{http.server_port}/step", data=json.dumps(observation).encode(), headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(json.load(response)["action"], "dance")
            self.assertEqual(received[0]["messages"][1]["images"], [image])
            self.assertIn("dance completed.", received[1]["messages"][1]["content"])
            self.assertIn("Decision:", received[1]["messages"][1]["content"])
            self.assertNotIn("images", received[1]["messages"][0])
        finally:
            http.shutdown()
            http.server_close()
            ollama.shutdown()
            ollama.server_close()

    def test_online_provider_image_schema_and_authorization(self):
        received = []

        class FakeOpenAI(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                body = json.dumps({"status": "completed", "output": [{"type": "reasoning"}, {"type": "message", "content": [
                    {"type": "output_text", "text": json.dumps({"action": "turn_left", "amount": 30, "reason": "Search for ball"})}
                ]}]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenAI)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        trace=tempfile.TemporaryDirectory()
        try:
            bridge = VisionBridge("test-vision", f"http://127.0.0.1:{upstream.server_port}/v1", api_key="test-key", trace_dir=trace.name)
            image = base64.b64encode(b"\xff\xd8\xfftest-image").decode()
            action = bridge.step({"session_id": "online-test", "command": "Fetch", "image_base64": image,"holding_ball":True})
            self.assertEqual(action["action"], "turn_left")
            path, authorization, payload = received[0]
            self.assertEqual(path, "/v1/responses")
            self.assertEqual(authorization, "Bearer test-key")
            self.assertEqual(payload["input"][0]["content"][1]["image_url"], "data:image/jpeg;base64," + image)
            self.assertTrue(payload["text"]["format"]["strict"])
            self.assertFalse(payload["store"])
            self.assertIn("Carrying ball: True",payload["input"][0]["content"][0]["text"])
            self.assertEqual((Path(trace.name)/'latest-observation.jpg').read_bytes(),base64.b64decode(image))
            saved=(Path(trace.name)/'latest-action.json').read_text()
            self.assertEqual(json.loads(saved)['action'],action)
            self.assertNotIn('test-key',saved)
            self.assertEqual(len((Path(trace.name)/'decisions.jsonl').read_text().splitlines()),1)
        finally:
            upstream.shutdown()
            upstream.server_close()
            trace.cleanup()


if __name__ == "__main__":
    unittest.main()
