"""Start or stop only this loopback media-review process."""
import json, os, subprocess, sys, time, urllib.request, webbrowser
from pathlib import Path
import psutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'outputs/presenter-v2-1080'
SCRIPT = HERE / 'review_server.py'
STATE = OUT / 'preview-process.json'
URL = 'http://127.0.0.1:8769/'

def healthy():
    try:
        with urllib.request.urlopen(URL, timeout=2) as response:
            return '新形象 1080p 预览' in response.read().decode('utf-8')
    except Exception:
        return False

def owned_process():
    if not STATE.exists():
        return None
    try:
        state = json.loads(STATE.read_text())
        process = psutil.Process(state['pid'])
        arguments = process.cmdline()
        if abs(process.create_time() - state['created']) < 1 and any(
            (Path(arg) if Path(arg).is_absolute() else Path(process.cwd()) / arg).resolve() == SCRIPT
            for arg in arguments[1:] if arg.endswith('.py')
        ):
            return process
    except (OSError, ValueError, KeyError, psutil.Error):
        pass
    return None

if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    command = sys.argv[1] if len(sys.argv) > 1 else 'start'
    if command == 'stop':
        process = owned_process()
        if process:
            process.terminate()
            process.wait(timeout=10)
            STATE.unlink(missing_ok=True)
            print('Preview stopped.')
        else:
            print('No owned preview process is running.')
    elif command == 'start':
        if not healthy():
            with (OUT / 'preview-server.log').open('ab') as log:
                process = subprocess.Popen([sys.executable, str(SCRIPT)], cwd=ROOT,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS) if os.name == 'nt' else 0,
                    start_new_session=os.name != 'nt')
            STATE.write_text(json.dumps({'pid': process.pid, 'created': psutil.Process(process.pid).create_time()}))
            for _ in range(30):
                if healthy():
                    break
                if process.poll() is not None:
                    raise SystemExit('Preview could not start. See preview-server.log.')
                time.sleep(.2)
            else:
                raise SystemExit('Preview did not become ready.')
        if '--no-browser' not in sys.argv:
            webbrowser.open(URL)
        print(URL)
    else:
        raise SystemExit('Expected start or stop.')
