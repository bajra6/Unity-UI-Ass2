import base64
import json
import io
import threading
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from server import VisionBridge, make_handler, validate_action, validate_plan


class BridgeTests(unittest.TestCase):
    def test_plan_preserves_order_and_delivery_discards_tail(self):
        plan = validate_plan({'steps': [{'action': a, 'amount': 1} for a in
                                      ('sit', 'stand', 'roll', 'dance', 'get_ball', 'deliver_ball', 'dance')]})
        self.assertEqual([s['action'] for s in plan['steps']], ['sit','stand','roll','dance','get_ball','deliver_ball'])
        with self.assertRaises(ValueError):
            validate_plan({'steps': [{'action': 'teleport', 'amount': 1}]})

    def test_planner_receives_remaining_plan_and_replaces_old_context(self):
        bridge = VisionBridge('test', provider='ollama', mode='live')
        bridge.sessions['old'] = ['Old conversation']
        with patch.object(bridge, '_model_json', return_value={'steps': [{'action': 'sit', 'amount': 1}, {'action': 'deliver_ball', 'amount': 1}]}) as model:
            plan = bridge.plan(self.observation(command='Sit, then continue returning.', holding_ball=True,
                               remaining_plan=[{'action': 'deliver_ball', 'amount': 1}], supersedes_session='old'))
        self.assertNotIn('old', bridge.sessions)
        self.assertIn('deliver_ball', model.call_args.args[0][1]['content'])
        self.assertEqual(plan['steps'][0]['action'], 'sit')

    def test_completion_clears_history_and_fallback_state(self):
        bridge = VisionBridge('test', provider='ollama', mode='live')
        bridge.sessions['fallback-test'] = ['Old reasoning']
        with patch.object(bridge, '_model_action') as model:
            action = bridge.step(self.observation(state='complete', last_result='Fetch succeeded: ball delivered to the person.'))
        model.assert_not_called()
        self.assertEqual(action['action'], 'finish')
        self.assertNotIn('fallback-test', bridge.sessions)

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

    def test_history_does_not_repeat_model_visual_claims(self):
        bridge = VisionBridge('test', provider='ollama', mode='live')
        action = {'action': 'turn_left', 'amount': 45, 'reason': 'The red ball is to the left.'}
        with patch.object(bridge, '_model_action', return_value=action.copy()) as model:
            bridge.step(self.observation())
            bridge.step(self.observation(last_result='Pickup failed. Face the ball within 2.0 m.', holding_ball=False))
        prompt = model.call_args.args[0][1]['content']
        self.assertNotIn('The red ball is to the left.', prompt)
        self.assertIn('turn_left', prompt)
        self.assertIn('Pickup failed', prompt)
        self.assertIn('Do not seek the owner yet', prompt)

    def test_latest_feedback_updates_completed_animations_and_fetch_stage(self):
        bridge = VisionBridge('test', provider='ollama', mode='live')
        action = {'action': 'wait', 'amount': .1, 'reason': 'Test'}
        with patch.object(bridge, '_model_action', return_value=action.copy()) as model:
            bridge.step(self.observation(last_result='dance completed.', holding_ball=True))
            prompt = model.call_args.args[0][1]['content']
            self.assertIn('Animations already completed in this task: dance', prompt)
            self.assertIn('Ball is carried: find the blue owner', prompt)
            bridge.step(self.observation(last_result='Fetch succeeded: ball delivered to the person.', holding_ball=False))
            self.assertIn('Delivery succeeded.', model.call_args.args[0][1]['content'])

    def test_trace_saves_each_input_before_inference_and_keeps_failed_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bridge = VisionBridge('test', provider='ollama', mode='live', trace_dir=directory)
            first = b'\xff\xd8\xfffirst-image'
            second = b'\xff\xd8\xffsecond-image'
            def reply(messages, raw_image, image):
                self.assertEqual((root / 'latest-observation.jpg').read_bytes(), raw_image)
                pending = json.loads((root / 'latest-action.json').read_text())
                self.assertEqual(pending['status'], 'pending')
                self.assertIsNone(pending['action'])
                self.assertEqual((root / pending['image_file']).read_bytes(), raw_image)
                if raw_image == second:
                    raise TimeoutError('Do not log raw provider errors or credentials')
                return {'action': 'move_forward', 'amount': .5, 'reason': 'Ball ahead'}
            with patch.object(bridge, '_model_action', side_effect=reply):
                bridge.step(self.observation(image_base64=base64.b64encode(first).decode(), step=0))
                with self.assertRaises(TimeoutError):
                    bridge.step(self.observation(image_base64=base64.b64encode(second).decode(), step=1))
            records = [json.loads(line) for line in (root / 'decisions.jsonl').read_text().splitlines()]
            self.assertEqual([r['status'] for r in records], ['completed', 'error'])
            for record, expected in zip(records, (first, second)):
                path = root / record['image_file']
                self.assertEqual(path.read_bytes(), expected)
                self.assertEqual(json.loads(path.with_suffix('.json').read_text()), record)
            self.assertNotEqual(records[0]['image_file'], records[1]['image_file'])
            self.assertNotIn('credentials', (root / 'latest-action.json').read_text())

    def test_return_leg_has_owner_instruction_without_replaying_ball_approach(self):
        bridge = VisionBridge('test', provider='ollama', mode='live')
        with patch.object(bridge, '_model_action', return_value={'action': 'move_forward', 'amount': 1.5, 'reason': 'Ball ahead'}) as model:
            bridge.step(self.observation(command='Find the red ball and bring it to the owner.'))
            bridge.step(self.observation(command='Find the red ball and bring it to the owner.', holding_ball=True,
                                         last_result="Pickup succeeded. Ball is in the dog's mouth."))
            messages = model.call_args.args[0]
            self.assertIn('Find the person in blue, approach them, and drop', messages[1]['content'])
            self.assertNotIn('Find the red ball', messages[1]['content'])
            self.assertNotIn('Decision:', messages[1]['content'])
            self.assertIn('ONLY destination', messages[0]['content'])
            bridge.step(self.observation(command='Sit.', holding_ball=True))
            self.assertIn('Current instruction: Sit.', model.call_args.args[0][1]['content'])

    def test_interaction_states_do_not_call_model(self):
        bridge = VisionBridge('test', provider='ollama', mode='live')
        with patch.object(bridge, '_model_action') as model:
            for state, expected in (('pick_up', 'pick_up'), ('drop', 'drop'), ('complete', 'finish')):
                action = bridge.step(self.observation(state=state, holding_ball=state == 'drop'))
                self.assertEqual(action['action'], expected)
                self.assertEqual(action['source'], 'state_machine')
            model.assert_not_called()

    def test_navigation_state_restricts_actions_and_sends_current_goal(self):
        raw = json.dumps({'reason': 'Owner is near', 'action': 'finish', 'amount': .1})
        bridge = VisionBridge('test', provider='ollama', mode='live')
        with patch('server.urllib.request.urlopen', return_value=io.StringIO(json.dumps({'message': {'content': raw}}))) as request:
            with self.assertRaisesRegex(ValueError, 'current task state'):
                bridge.step(self.observation(state='approach_owner', holding_ball=True))
            payload = json.loads(request.call_args.args[0].data)
            self.assertIn('PERSON IN BLUE', payload['messages'][1]['content'])
            self.assertIn('State: approach_owner', payload['messages'][1]['content'])
            self.assertNotIn('finish', payload['format']['properties']['action']['enum'])
            self.assertNotIn('pick_up', payload['format']['properties']['action']['enum'])
        with self.assertRaisesRegex(ValueError, 'Unknown task state'):
            bridge.step(self.observation(state='teleport'))

    def test_raw_model_response_is_logged_before_validation_and_cleared_on_failure(self):
        raw_reply = '{"reason":"Ball ahead", "action":"move_forward", "amount":99}'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bridge = VisionBridge('test', provider='ollama', mode='live', trace_dir=directory)
            replies = [io.StringIO(json.dumps({'message': {'content': raw_reply}})),
                       io.StringIO(json.dumps({'message': {'content': 'not valid JSON'}})),
                       TimeoutError()]
            with patch('server.urllib.request.urlopen', side_effect=replies):
                action = bridge.step(self.observation(step=0))
                self.assertEqual(action['amount'], 1.5)
                record = json.loads((root / 'latest-action.json').read_text())
                self.assertEqual(record['model_response'], raw_reply)
                self.assertEqual(record['action']['amount'], 1.5)
                with self.assertRaises(ValueError):
                    bridge.step(self.observation(step=1))
                record = json.loads((root / 'latest-action.json').read_text())
                self.assertEqual(record['model_response'], 'not valid JSON')
                self.assertEqual(record['status'], 'error')
                with self.assertRaises(TimeoutError):
                    bridge.step(self.observation(step=2))
                self.assertIsNone(json.loads((root / 'latest-action.json').read_text())['model_response'])

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
            self.assertIn("Carrying ball: False", received[1]["messages"][0]["content"])
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
            self.assertIn("Ignore that red ball for navigation", payload["instructions"])
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
