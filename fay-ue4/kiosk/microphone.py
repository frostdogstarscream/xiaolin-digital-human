"""Local microphone capture. AEC must be provided by the installed audio device.

Voice activity is detected locally. Cloud ASR confirms the wake phrase and
barge-in; this is intentionally not advertised as offline wake-word detection.
"""
import asyncio
from collections import deque
import numpy as np


class Microphone:
    def __init__(self, session, driver=None):
        self.session = session
        self.driver = driver
        self.stream = None
        self.task = None
        self.queue = asyncio.Queue(maxsize=100)
        self.preroll = deque(maxlen=10)
        self.recording = False
        self.manual = False
        self.closed = False
        self.silence = 0
        self.voiced = 0
        self.frames = 0
        self.cooldown = 0

    async def start(self):
        if self.driver is None:
            import sounddevice
            self.driver = sounddevice
        loop = asyncio.get_running_loop()
        def enqueue(data):
            if self.closed:
                return
            if self.queue.full():
                # Bounded memory; discard oldest capture audio on a stalled network.
                self.queue.get_nowait()
            self.queue.put_nowait(data)
        def callback(data, frames, at, status):
            loop.call_soon_threadsafe(enqueue, bytes(data))
        device = self.session.store.settings.audio.microphone or None
        self.stream = self.driver.RawInputStream(samplerate=16000, blocksize=320, channels=1,
                                                 dtype="int16", device=device, callback=callback)
        self.stream.start()
        self.task = asyncio.create_task(self.run())

    async def manual_start(self):
        self.manual = True
        await self.session.begin_audio("push_to_talk")
        self.recording = True
        self.frames = self.silence = 0

    async def manual_end(self):
        self.manual = False
        if self.recording:
            self.recording = False
            await self.session.end_audio()

    async def run(self):
        try:
            while not self.closed:
                frame = await self.queue.get()
                try:
                    await self.feed(frame)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.recording = self.manual = False
                    self.cooldown = 250  # Retry after five seconds, not every audio block.
                    await self.session.abort_capture()
                    await self.session.emit("error", message="麦克风或语音识别连接失败，请检查配置。", fallback="service_unavailable")
        except asyncio.CancelledError:
            pass

    async def feed(self, frame):
        settings = self.session.store.settings.audio
        if self.cooldown:
            self.cooldown -= 1
            return
        if self.recording and self.session.asr is None:
            # Role/config changes or explicit interruption ended the capture.
            self.recording = self.manual = False
        values = np.frombuffer(frame, dtype="<i2").astype(np.float32) / 32768
        rms = float(np.sqrt(np.mean(values * values))) if values.size else 0
        voiced = rms >= settings.vad_threshold
        self.preroll.append(frame)
        if not self.recording:
            if settings.mode != "hands_free" or not settings.aec_verified:
                return
            self.voiced = self.voiced + 1 if voiced else 0
            if self.voiced < 3:
                return
            self.voiced = self.silence = self.frames = 0
            await self.session.begin_audio("hands_free")
            self.recording = True
            for buffered in self.preroll:
                await self.session.asr.feed(buffered)
            self.preroll.clear()
            return
        self.frames += 1
        if self.session.asr:
            await self.session.asr.feed(frame)
        self.silence = 0 if voiced else self.silence + 20
        if self.frames >= 750 or (not self.manual and self.silence >= settings.silence_ms):
            self.recording = self.manual = False
            self.preroll.clear()
            await self.session.end_audio()
            self.cooldown = 10

    async def close(self):
        self.closed = True
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
