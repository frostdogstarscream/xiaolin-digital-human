"""End-to-end WebRTC 50fps + Qwen Realtime + 4-Gesture + Interrupt + ASR validation
against the candidate formal50-ultralight container, saving decoded H.264 sample frames.
"""
import asyncio
import json
import os
import time
from pathlib import Path

import aiohttp
import cv2
import numpy as np
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

PORT = int(os.environ.get("QWEN_DEMO_PORT", "8775"))
URL = f"http://127.0.0.1:{PORT}"
OUT = Path("/formal/validation-ultralight.json")
SHEET = Path("/formal/validation-webrtc-frames.jpg")


async def main():
    events = []
    frames = []
    sampled_bgr = []
    counts = {"audio": 0, "voiced": 0}
    tasks = []
    sizes = set()

    async with aiohttp.ClientSession(headers={"Origin": URL}, trust_env=False, timeout=aiohttp.ClientTimeout(total=180)) as http:
        async def get_health():
            async with http.get(URL + "/api/health") as r:
                assert r.status == 200
                return await r.json()

        h = await get_health()
        assert h["material_version"] == "rife-ultralight-v1", h
        assert h.get("lipsync_model") == "xiaolin-ultralight-v1", h
        assert (h["video_fps"], h["lipsync_backend"], h["precision"]) == (50, "wav2lip", "torch.float16"), h

        async with http.ws_connect(URL + "/ws?scope=formal50_ultralight_val", heartbeat=20) as ws:
            ready = await ws.receive_json()
            assert ready["type"] == "ready"
            sid = ready["session_id"]

            async def read_ws():
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        e = json.loads(message.data)
                        events.append(e)
                        if e["type"] in ("playing", "playback_done", "interrupted", "error", "listen_ready"):
                            print("EVENT", e["type"], flush=True)

            reader = asyncio.create_task(read_ws())

            async def wait_event(kind, start_idx, timeout=75):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    errors = [e for e in events[start_idx:] if e["type"] == "error"]
                    assert not errors, errors
                    found = next((e for e in events[start_idx:] if e["type"] == kind), None)
                    if found:
                        return found
                    await asyncio.sleep(0.1)
                raise TimeoutError(kind)

            pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))

            @pc.on("track")
            def added(track):
                async def consume():
                    try:
                        while True:
                            f = await track.recv()
                            if track.kind == "video":
                                frames.append(time.monotonic())
                                sizes.add((f.width, f.height))
                                if len(frames) % 120 == 25 and len(sampled_bgr) < 12:
                                    bgr = f.to_ndarray(format="bgr24")
                                    sampled_bgr.append(cv2.resize(bgr[120:960, 220:860], (240, 315)))
                            else:
                                counts["audio"] += 1
                                if np.max(np.abs(f.to_ndarray().astype(float))) > 500:
                                    counts["voiced"] += 1
                    except Exception:
                        pass

                tasks.append(asyncio.create_task(consume()))

            try:
                pc.addTransceiver("audio", direction="recvonly")
                pc.addTransceiver("video", direction="recvonly")
                await pc.setLocalDescription(await pc.createOffer())
                async with http.post(
                    URL + "/api/offer",
                    headers={"X-Demo-Session": sid},
                    json={"type": "offer", "sdp": pc.localDescription.sdp},
                ) as r:
                    text = await r.text()
                    assert r.status == 200, text
                    answer = json.loads(text)
                await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))

                deadline = time.monotonic() + 30
                while pc.connectionState != "connected":
                    assert time.monotonic() < deadline, pc.connectionState
                    await asyncio.sleep(0.2)

                warm_deadline = time.monotonic() + 45
                while len(frames) < 100:
                    assert time.monotonic() < warm_deadline, "Media warmup timeout"
                    await asyncio.sleep(0.2)

                start_time = time.monotonic()
                start = len(events)
                await ws.send_json({"type": "text", "text": "请挥手欢迎我，只说“你好，欢迎你”。"})
                await wait_event("playing", start)
                await wait_event("playback_done", start)

                deadline = time.monotonic() + 18
                while True:
                    h = await get_health()
                    if h["active_action"] == "idle" and h["render_stats"]["actions_completed"]["welcome-wave"] >= 1:
                        break
                    assert time.monotonic() < deadline, h["render_stats"]
                    await asyncio.sleep(0.2)
                welcome = h["render_stats"].copy()
                print("WELCOME_WAVE_COMPLETED", flush=True)

                for action, prompt in [
                    ("goodbye-wave", "请挥手告别，动作使用 goodbye-wave，只说“再见”。"),
                    ("explain-open-palms", "请做右手伸手讲解动作 explain-open-palms，只说“请看这里”。"),
                    ("acknowledge-nod", "请做轻微点头动作 acknowledge-nod，只说“好的”。"),
                ]:
                    start = len(events)
                    await ws.send_json({"type": "text", "text": prompt})
                    await wait_event("playing", start)
                    await wait_event("playback_done", start)
                    deadline = time.monotonic() + 26
                    while True:
                        h = await get_health()
                        if h["render_stats"]["actions_completed"].get(action, 0) >= 1 and h["active_action"] == "idle":
                            break
                        assert time.monotonic() < deadline, (action, h["render_stats"])
                        await asyncio.sleep(0.2)
                    print("ACTION_COMPLETED", action, flush=True)

                start = len(events)
                await ws.send_json({"type": "text", "text": "请用十句话详细介绍你能提供哪些帮助。"})
                await wait_event("playing", start)
                mark = len(events)
                await ws.send_json({"type": "interrupt"})
                await wait_event("interrupted", mark, 15)
                await asyncio.sleep(1.0)
                interrupted = await get_health()
                assert interrupted["audio_queue"] == 0, interrupted

                start = len(events)
                await ws.send_json({"type": "text", "text": "只回复“好的”。"})
                await wait_event("playing", start)
                await wait_event("playback_done", start)

                start = len(events)
                await ws.send_json({"type": "listen"})
                await wait_event("listen_ready", start, 10)
                await ws.send_json({"type": "stop"})

                while time.monotonic() - start_time < 60:
                    h = await get_health()
                    assert h["render_error"] is None, h
                    assert pc.connectionState == "connected", pc.connectionState
                    await asyncio.sleep(1.0)

                finish = time.monotonic()
                received = [t for t in frames if start_time <= t <= finish]
                fps = (len(received) - 1) / (received[-1] - received[0])
                final = await get_health()
                full_window_fps = len(received) / (finish - start_time)
                max_gap = max(np.diff(received))

                assert full_window_fps >= 47.5, (full_window_fps, fps)
                assert max_gap < 1.0, max_gap
                assert sizes == {(1080, 1920)}, sizes
                assert counts["voiced"] > 0, counts
                assert final["render_error"] is None and final["audio_queue"] == 0, final

                if sampled_bgr:
                    while len(sampled_bgr) % 4 != 0:
                        sampled_bgr.append(sampled_bgr[-1])
                    rows = [np.hstack(sampled_bgr[r : r + 4]) for r in range(0, len(sampled_bgr), 4)]
                    cv2.imwrite(str(SHEET), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 94])

                report = {
                    "status": "PASSED",
                    "material_version": h["material_version"],
                    "lipsync_model": h.get("lipsync_model"),
                    "actions_completed": final["render_stats"]["actions_completed"],
                    "duration_seconds": finish - start_time,
                    "received_fps": fps,
                    "full_window_fps": full_window_fps,
                    "max_video_gap_seconds": float(max_gap),
                    "received_frames": len(received),
                    "audio": counts,
                    "dimensions": list(sizes),
                    "video_fps": h["video_fps"],
                    "precision": h["precision"],
                    "welcome_stats": welcome,
                    "final_stats": final["render_stats"],
                    "interrupt_queue": interrupted["audio_queue"],
                    "final_queue": final["audio_queue"],
                    "wake_listener_ready": True,
                    "events": events,
                }
                OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({k: v for k, v in report.items() if k != "events"}), flush=True)
            finally:
                await pc.close()
                reader.cancel()
                for task in tasks:
                    task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
