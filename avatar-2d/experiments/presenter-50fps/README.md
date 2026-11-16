# 1080p / 50 fps + three randomized idle segments

Experimental only. Production engines, assets, credentials, model selection and services are unchanged.

- `prepare.py`: creates a separate optical-flow cache at 50 fps. Every even frame is the original frame, every odd frame is a bidirectional DIS optical-flow midpoint (last frame holds 20 ms). This is synthetic interpolation, not native 50 fps capture. Face coordinates interpolate with each midpoint; face crops come from that exact new body frame. Original resolution, duration, identity and clothing are retained.
- Three contiguous idle segments are selected near 10 s / 20 s using minimum endpoint image differences. No claim that pixel distance alone establishes visual naturalness. Review all six possible joins.
- `idle_scheduler.py`: weighted random among other segments, favoring similar endpoint posture. No immediate repeated segment. Ordinary speech continues idle; returning from actions chooses a compatible segment instead of resetting to frame zero.
- `engine50.py`: 50 independently inferred Wav2Lip frames/second; one 320-sample PCM packet per video frame. Audio remains 16 kHz, 20 ms, and original speed. Isolated WebRTC timebase is 20 ms.
- `encoder50.py`: isolated NVENC 50 fps, H.264 level 4.2, 8 Mbps target / 12 Mbps cap. Network bandwidth must be tested independently.
- `XIAOLIN_50_PRECISION=fp16` explicitly opts into half-precision inference for this experiment only. FP32 trials are retained. Current tuning compares both modes on the same face crops; this is not a substitute for visual acceptance. OpenBLAS is limited to one thread and OpenCV to one thread to avoid small-operation thread overhead; blend masks are cached without changing their formula.
- `check50.py`: frozen local PCM, real server-loopback WebRTC, 300 seconds, all four gestures, interruption, stale-generation rejection and reconnection. No cloud LLM or TTS calls.
- `make_review.py`: 60-second 25/50 fps random-idle comparison, deterministic sequence and six-transition contact sheet.

Rebuild experiment copies: `python build_experiment.py`. Unit checks: `python test_scheduler.py`.

Visual acceptance and external browser receiving performance are separate from server-loopback results. Do not switch production solely based on numeric fps.
