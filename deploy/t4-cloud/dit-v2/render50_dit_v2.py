"""50 fps render loop for Xiaolin-DiT-v2 (256x256 Dual-Reference GAN Student):
- Zero-latency 10-frame lookahead pre-articulation ramp (closed-to-closed smoothstep)
- Solid alpha=1.0 across active speech + 22-frame (440ms) post-speech geometric lip-closure tail
- 8-frame closed-mouth smoothstep ramp back to 0.0 (zero GPU overhead during pure idle!)
"""
import numpy as np
from engine_baseline import clear_queue, AudioFrameData

LEFT_HIST_CHUNKS = 30  # 600ms rolling past context for Whisper encoder (adds 0ms latency)


def _compute_batch_envelopes(presenter, packets) -> list[float]:
    with presenter.asr.output_queue.mutex:
        future_packets = list(presenter.asr.output_queue.queue)

    alphas = []
    for i in range(len(packets)):
        cur_speaking = packets[i].type == 0
        if cur_speaking:
            presenter._post_speech_hold = 30
            alphas.append(1.0)
            continue

        hold = presenter._post_speech_hold
        if hold > 8:
            post_a = 1.0
        elif hold > 0:
            t = hold / 9.0
            post_a = t * t * (3.0 - 2.0 * t)
        else:
            post_a = 0.0
        if hold > 0:
            presenter._post_speech_hold = hold - 1

        upcoming = packets[i + 1 :] + future_packets
        first_speech_dist = None
        for idx_u, pkt_u in enumerate(upcoming[:10]):
            if pkt_u.type == 0:
                first_speech_dist = idx_u + 1
                break
        if first_speech_dist is not None and first_speech_dist <= 4:
            pre_a = 1.0
        elif first_speech_dist is not None and first_speech_dist <= 10:
            t = (11.0 - first_speech_dist) / 7.0
            pre_a = t * t * (3.0 - 2.0 * t)
        else:
            pre_a = 0.0

        alphas.append(max(post_a, pre_a))
    return alphas


def render(self, quit_event):
    self.quit_event = quit_event
    try:
        while not quit_event.is_set():
            if self.output.get_buffer_size() >= 4:
                quit_event.wait(0.005)
                continue
            with self.lock:
                generation = self.generation
                if self.reset_requested.is_set():
                    self.reset_requested.clear()
                    if not self.preserve_motion_on_reset:
                        self.motion = None
                    self.preserve_motion_on_reset = False
                    self._post_speech_hold = 0
                    clear_queue(self.asr.output_queue)
                    clear_queue(self.asr.feat_queue)
                    self.asr.frames = [np.zeros(self.chunk, np.float32) for _ in range(LEFT_HIST_CHUNKS + self.opt.r)]
                    for _ in range(self.opt.r):
                        self.asr.output_queue.put(AudioFrameData(np.zeros(self.chunk, np.float32), 1))
                    player = self.output._player
                    clear_queue(player.audio._queue)
                    clear_queue(player.video._queue)
                    for wave, info in self.pending_audio:
                        self.asr.put_audio_frame(wave, info)
                    self.pending_audio.clear()

            self.asr.run_step()
            pcm_window = self.asr.feat_queue.get(timeout=2)
            packets = [self.asr.output_queue.get(timeout=2) for _ in range(self.batch_size)]
            for p in packets:
                if p.type == 0 and p.userdata.get("generation") != generation:
                    p.data = np.zeros(self.chunk, np.float32)
                    p.type = 1
                    p.userdata = {}

            tokens = [self._advance(packets[i : i + 1]) for i in range(self.batch_size)]
            speaking = [p.type == 0 for p in packets]
            env_alphas = _compute_batch_envelopes(self, packets)
            need_infer = any(a > 1e-3 for a in env_alphas)
            pred = self._infer(tokens, pcm_window) if need_infer else [None] * self.batch_size

            for i, token in enumerate(tokens):
                with self.lock:
                    if generation != self.generation or quit_event.is_set():
                        break
                    self.speaking = speaking[i]
                    self.output.push_video_frame(
                        self._compose(token, pred[i] if env_alphas[i] > 1e-3 else None, env_alphas[i])
                    )
                    self.stats["video_frames"] += 1
                    self.stats["speech_frames"] += int(speaking[i])
                    for p in packets[i : i + 1]:
                        self.output.push_audio_frame((p.data * 32767).clip(-32768, 32767).astype(np.int16), p.userdata)
    except Exception as exc:
        self.error = type(exc).__name__
        self.callback({"error": "实时渲染中断，请重新连接展示。"})
    finally:
        self.speaking = False
        self.output.stop()
