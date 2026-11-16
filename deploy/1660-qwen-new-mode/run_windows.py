"""Local Windows host: retain graceful asyncio cleanup through an owned stop file."""
import asyncio
import contextlib
import os
import json
import time
from pathlib import Path
import sys

ROOT = Path(os.environ.get('XIAOLIN_ROOT', 'D:/XiaolinDigitalHuman'))
STATE = ROOT / 'avatar-2d/runtime/qwen-realtime-v2'
sys.path.insert(0, str(ROOT / 'avatar-2d/experiments/qwen-realtime-v2'))
# Keep optional Linux cloud imports out of this local-only process.
os.environ.pop('XIAOLIN_TURN_HOST', None)
os.environ['QWEN_DEMO_PORT'] = '8771'
os.environ['QWEN_DEMO_ORIGIN'] = 'http://127.0.0.1:8771'
os.environ['QWEN_STATE_DIR'] = str(STATE)
os.environ['FAY_SYSTEM_CONF'] = str(ROOT / 'fay-ue4/runtime/fay-local/app/system.conf')
os.environ['XIAOLIN_PRECISION'] = 'fp32'
os.environ['XIAOLIN_VIDEO_ENCODER'] = 'h264_nvenc'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['MODELSCOPE_OFFLINE'] = '1'

async def main():
    import gateway
    STATE.mkdir(parents=True, exist_ok=True)
    stop = STATE / 'stop.request'
    stop.unlink(missing_ok=True)
    app = asyncio.create_task(gateway.main())
    try:
        while not app.done() and not stop.exists():
            await asyncio.sleep(.25)
        if stop.exists() and not app.done():
            app.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await app
    finally:
        if not app.done():
            app.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await app
        stop.unlink(missing_ok=True)

if __name__ == '__main__':
    receipt=STATE/'graceful-exit.json';STATE.mkdir(parents=True,exist_ok=True)
    receipt.unlink(missing_ok=True)
    exit_code=0
    try:
        asyncio.run(main())
    except BaseException:
        exit_code=1
        raise
    finally:
        receipt.write_text(json.dumps(dict(exit_code=exit_code,cleanup_completed=exit_code==0,time=time.time())),encoding='utf-8')
