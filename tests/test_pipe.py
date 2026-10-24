from pathlib import Path

from sitecheck.browser import Chrome


def test_pipe_transport(tmp_path):
    executable = tmp_path / "fake-browser"
    executable.write_text('''#!/usr/bin/env python3
import json
import os
buffer = b""
while True:
    chunk = os.read(3, 65536)
    if not chunk:
        break
    buffer += chunk
    while b"\\0" in buffer:
        data, buffer = buffer.split(b"\\0", 1)
        request = json.loads(data)
        method = request["method"]
        if method == "Target.getTargets":
            result = {"targetInfos": [{"type": "page", "targetId": "test"}]}
        elif method == "Target.attachToTarget":
            result = {"sessionId": "session"}
        elif method == "Runtime.evaluate":
            result = {"result": {"value": 7}}
        else:
            result = {}
        os.write(4, json.dumps({"id": request["id"], "result": result}).encode() + b"\\0")
''')
    executable.chmod(0o755)
    with Chrome(str(executable), timeout=2) as browser:
        assert browser.session == "session"
        assert browser.evaluate("3 + 4") == 7


def test_default_browser_timeout(tmp_path):
    browser = Chrome(str(tmp_path / "fake-browser"))
    assert browser.timeout == 40
