"""Idempotent post-start initialization of Fay and the semantic attendance tool."""
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(url, data=None):
    headers = {'Content-Type': 'application/json', 'X-Avatar-Client': '1'}
    body = json.dumps(data).encode() if data is not None else None
    with HTTP.open(urllib.request.Request(url, data=body, headers=headers), timeout=90) as response:
        return json.load(response)


deadline = time.monotonic() + 240
while True:
    try:
        health = request('http://127.0.0.1:8766/api/health')
        request('http://127.0.0.1:5010/api/mcp/servers')
        request('http://127.0.0.1:8783/health')
        if health['model_state'] == 'ready' and health['asr']['state'] == 'ready':
            break
    except (OSError, urllib.error.HTTPError):
        pass
    if time.monotonic() > deadline:
        raise RuntimeError('Dependencies did not become ready')
    time.sleep(2)
subprocess.run(['python', '/app/attendance-mcp/manage.py'], check=True)
request('http://127.0.0.1:8766/api/start', {})
print('Fay core, local ASR, presenter and semantic attendance tool ready', flush=True)
