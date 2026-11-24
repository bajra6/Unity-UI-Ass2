"""Exercise Unity instruction completion over HTTP with deterministic model plans.

Run with the Unity editor closed. The temporary bridge closes on exit.
"""
import json
import os
from pathlib import Path
import subprocess
import threading
from http.server import ThreadingHTTPServer

from server import VisionBridge, make_handler


def main():
    root = Path(__file__).resolve().parent.parent
    bridge = VisionBridge('test-planner', provider='ollama', mode='live')

    def model_json(messages, raw_image, image, schema, name='dog_action'):
        assert name == 'dog_plan', 'Targets start within interaction range; no navigation inference expected.'
        prompt = messages[1]['content']
        steps = [{'action': 'drop', 'amount': 1}]
        if 'then sit' in prompt:
            destination = 'pink_person' if 'pink person' in prompt else 'blue_person'
            steps = [{'action': 'get_ball', 'amount': 1},
                     {'action': 'deliver_ball', 'target': destination, 'amount': 1},
                     {'action': 'sit', 'amount': 1}]
        return {'reason': 'Instruction completion integration test', 'steps': steps}

    bridge._model_json = model_json
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(bridge))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        (root / 'Verification').mkdir(exist_ok=True)
        (root / 'Verification/result.json').write_text('{"status":"starting"}')
        env = dict(os.environ, GOODBOY_VERIFY_INSTRUCTIONS='1',
                   GOODBOY_VERIFY_URL=f'http://127.0.0.1:{server.server_port}')
        result = subprocess.run([
            r'C:\Program Files\Unity\Hub\Editor\6000.6.8f1\Editor\Unity.exe',
            '-batchmode', '-projectPath', str(root), '-executeMethod', 'GoodBoySetup.Verify',
            '-logFile', str(root / 'Server/trace/instruction-verification.log')],
            env=env, cwd=root, timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise SystemExit(f'Unity exited with code {result.returncode}; see Server/trace/instruction-verification.log')
        outcome = json.loads((root / 'Verification/result.json').read_text())
        print(outcome, flush=True)
        if result.returncode or outcome['status'] != 'passed':
            raise SystemExit(1)
        print('INSTRUCTION_COMPLETION_OK', flush=True)
    finally:
        server.shutdown()
        server.server_close()
        print('Temporary bridge closed.', flush=True)


if __name__ == '__main__':
    main()
