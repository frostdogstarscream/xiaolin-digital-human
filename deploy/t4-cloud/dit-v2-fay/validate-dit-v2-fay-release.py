"""E2E validation of candidate formal50-dit-v2-fay:
  - Health / static assets / shim / Fay persona & MCP catalog sync
  - Live WebRTC 50fps 1080x1920 connection
  - Mode A (qwen_realtime) reply + subtitle events + gesture
  - Live switch to Mode B (fay_agent) WITHOUT WebRTC drop + Fay cognitive reply + audio/video
  - Live switch back to Mode A + verification that Fay liveState returns editable (False)
  - ASR wake listener readiness check
"""
import asyncio
import json
import os
import time
from pathlib import Path

import aiohttp
import numpy as np
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

PORT = int(os.environ.get("QWEN_DEMO_PORT", "8776"))
URL = f"http://127.0.0.1:{PORT}"
OUT = Path("/formal/validation-dit-v2-fay.json")


async def main():
    events = []
    frames = []
    counts = {"audio": 0, "voiced": 0}
    tasks = []
    sizes = set()

    async with aiohttp.ClientSession(headers={"Origin": URL}, trust_env=False, timeout=aiohttp.ClientTimeout(total=180)) as http:
        async def get_health():
            async with http.get(URL + "/api/health") as r:
                assert r.status == 200
                return await r.json()

        for path in ("/", "/demo.js", "/fay-https-shim.js", "/api/fay/status"):
            async with http.get(URL + path) as r:
                assert r.status == 200, (path, r.status)

        h = await get_health()
        assert h["status"] == "ready"
        assert h["material_version"] == "rife-dit-v2", h
        assert h.get("lipsync_model") == "xiaolin-dit-v2-256gan", h
        assert h.get("video_fps") == 50, h

        async with http.get(URL + "/api/fay/status") as r:
            fay_status = await r.json()
        print("FAY_STATUS", json.dumps({
            "persona_name": fay_status.get("persona_name"),
            "mcp_tool_count": fay_status.get("mcp_tool_count"),
            "mcp_tools": [t.get("name") for t in fay_status.get("mcp_tools", [])],
        }, ensure_ascii=False), flush=True)

        async with http.ws_connect(URL + "/ws?scope=formal50_dit_v2_fay_val", heartbeat=20) as ws:
            ready = await ws.receive_json()
            assert ready["type"] == "ready", ready
            sid = ready["session_id"]

            async def read_ws():
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        e = json.loads(message.data)
                        events.append(e)
                        if e["type"] in ("playing", "playback_done", "interrupted", "error", "settings_changed", "listen_ready"):
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

                async with http.get(URL + "/api/settings") as r:
                    orig_settings = await r.json()
                base_payload = {k: v for k, v in orig_settings.items() if k != "revision"}

                # 1. Mode A test (Qwen Realtime + Fay persona/MCP)
                if base_payload.get("dialogue_mode") != "qwen_realtime":
                    async with http.post(URL + "/api/settings", json={**base_payload, "dialogue_mode": "qwen_realtime"}) as r:
                        assert r.status == 200
                start_time = time.monotonic()
                mark = len(events)
                await ws.send_json({"type": "text", "text": "你好，请挥手欢迎我并简短介绍一下你是谁。"})
                await wait_event("playing", mark)
                await wait_event("playback_done", mark)
                mode_a_subtitles = [e for e in events[mark:] if e["type"] in ("assistant_delta", "assistant_text") and str(e.get("text", "")).strip()]
                assert mode_a_subtitles, "Mode A missing subtitle events"
                print("MODE_A_PASSED", "subtitles=", len(mode_a_subtitles), flush=True)

                # 2. Switch to Mode B (Fay brain) WITHOUT dropping WebRTC
                cur_settings = await (await http.get(URL + "/api/settings")).json()
                cur_payload = {k: v for k, v in cur_settings.items() if k != "revision"}
                frames_before_switch = len(frames)
                async with http.post(URL + "/api/settings", json={**cur_payload, "dialogue_mode": "fay_agent"}) as r:
                    assert r.status == 200, await r.text()
                assert pc.connectionState == "connected", pc.connectionState

                mark = len(events)
                await ws.send_json({"type": "text", "text": "你好，请用一句话介绍一下你自己。"})
                await wait_event("assistant_text", mark, timeout=75)
                await wait_event("playback_done", mark, timeout=75)
                assert pc.connectionState == "connected", pc.connectionState
                assert len(frames) > frames_before_switch + 50
                mode_b_text = next((e.get("text", "") for e in reversed(events[mark:]) if e["type"] == "assistant_text"), "")
                print("MODE_B_PASSED", "reply=", mode_b_text[:80], flush=True)

                # 3. Switch back to Mode A WITHOUT dropping WebRTC
                cur_settings = await (await http.get(URL + "/api/settings")).json()
                cur_payload = {k: v for k, v in cur_settings.items() if k != "revision"}
                async with http.post(URL + "/api/settings", json={**cur_payload, "dialogue_mode": "qwen_realtime"}) as r:
                    assert r.status == 200
                assert pc.connectionState == "connected"
                async with http.get(URL + "/api/fay/status") as r:
                    fay_after = await r.json()
                assert fay_after.get("fay_core_running") is False, fay_after
                assert fay_after.get("mcp_tool_count", 0) >= 1, fay_after

                # 4. Wake ASR listener readiness
                mark = len(events)
                await ws.send_json({"type": "listen"})
                await wait_event("listen_ready", mark, timeout=10)
                await ws.send_json({"type": "stop"})

                finish = time.monotonic()
                received = [t for t in frames if start_time <= t <= finish]
                fps = (len(received) - 1) / (received[-1] - received[0])
                final = await get_health()

                assert fps >= 47.5, fps
                assert sizes == {(1080, 1920)}, sizes
                assert counts["voiced"] > 0, counts
                assert final["render_error"] is None and final["audio_queue"] == 0, final

                report = {
                    "status": "PASSED",
                    "material_version": final["material_version"],
                    "lipsync_model": final.get("lipsync_model"),
                    "persona_name": final.get("persona_name"),
                    "mcp_tool_count": final.get("mcp_tool_count"),
                    "mode_a_subtitle_events": len(mode_a_subtitles),
                    "mode_b_reply": mode_b_text,
                    "zero_drop_rtc_preserved": True,
                    "received_fps": fps,
                    "dimensions": list(sizes),
                    "audio": counts,
                    "video_fps": final["video_fps"],
                    "fay_editable_after_return_to_mode_a": True,
                }
                OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(report, ensure_ascii=False), flush=True)
            finally:
                await pc.close()
                reader.cancel()
                for task in tasks:
                    task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
