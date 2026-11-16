import numpy as np
from engine_baseline import clear_queue, AudioFrameData

def render(self, quit_event):
    self.quit_event = quit_event
    try:
        while not quit_event.is_set():
            if self.output.get_buffer_size() >= 4:
                quit_event.wait(.005)
                continue
            with self.lock:
                generation = self.generation
                if self.reset_requested.is_set():
                    self.reset_requested.clear()
                    if not self.preserve_motion_on_reset:
                        self.motion = None
                        pass  # Keep last pose for idle segment matching
                    self.preserve_motion_on_reset = False
                    self.asr.frames = []
                    clear_queue(self.asr.output_queue)
                    clear_queue(self.asr.feat_queue)
                    # Pure-silence left/right context, without consuming new speech.
                    self.asr.frames = [np.zeros(self.chunk, np.float32) for _ in range(self.opt.l+self.opt.r)]
                    for _ in range(self.opt.r):
                        self.asr.output_queue.put(AudioFrameData(np.zeros(self.chunk, np.float32), 1))
                    player = self.output._player
                    clear_queue(player.audio._queue)
                    clear_queue(player.video._queue)
                    for wave, info in self.pending_audio:
                        self.asr.put_audio_frame(wave, info)
                    self.pending_audio.clear()
            self.asr.run_step()
            features = self.asr.feat_queue.get(timeout=2)
            packets = [self.asr.output_queue.get(timeout=2) for _ in range(self.batch_size)]
            for p in packets:
                if p.type == 0 and p.userdata.get('generation') != generation:
                    p.data = np.zeros(self.chunk, np.float32)
                    p.type = 1
                    p.userdata = {}
            tokens = [self._advance(packets[i:i+1]) for i in range(self.batch_size)]
            speaking = [any(p.type == 0 for p in packets[i:i+1]) for i in range(self.batch_size)]
            pred = self._infer(tokens, features) if any(speaking) else [None]*self.batch_size
            for i, token in enumerate(tokens):
                with self.lock:
                    if generation != self.generation or quit_event.is_set():
                        break
                    self.speaking = speaking[i]
                    self.output.push_video_frame(self._compose(token, pred[i] if speaking[i] else None))
                    self.stats['video_frames'] += 1
                    self.stats['speech_frames'] += int(speaking[i])
                    for p in packets[i:i+1]:
                        self.output.push_audio_frame((p.data*32767).clip(-32768, 32767).astype(np.int16), p.userdata)
    except Exception as exc:
        self.error = type(exc).__name__
        self.callback({'error': '实时渲染中断，请重新连接展示。'})
    finally:
        self.speaking = False
        self.output.stop()
