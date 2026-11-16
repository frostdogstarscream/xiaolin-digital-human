from __future__ import annotations
import asyncio
import hashlib
import json
import os
import uuid
from .providers import ProviderError


class SpeechCache:
    def __init__(self, store):
        self.store = store
        self.locks = {}

    def path(self, text, role, model):
        descriptor = json.dumps([text, role.voice, role.speech_rate, model, 24000, "pcm16-mono"], ensure_ascii=False)
        digest = hashlib.sha256(descriptor.encode()).hexdigest()
        return self.store.root / "audio" / (digest + ".pcm")

    async def stream(self, text, role, provider):
        path = self.path(text, role, provider.settings.tts_model)
        # A complete cache file is published atomically. Partial cancelled speech is never cached.
        lock = self.locks.setdefault(path.name, asyncio.Lock())
        async with lock:
            if path.exists():
                with path.open("rb") as f:
                    while frame := f.read(12000):
                        yield frame
                        await asyncio.sleep(0)
                return
            temp = path.with_suffix("." + uuid.uuid4().hex + ".part")
            total = 0
            remainder = b""
            try:
                with temp.open("wb") as f:
                    async for frame in provider.tts(text, role):
                        remainder += frame
                        length = len(remainder) // 2 * 2
                        if not length:
                            continue
                        frame, remainder = remainder[:length], remainder[length:]
                        f.write(frame)
                        total += len(frame)
                        if total > 24_000 * 2 * 180:
                            raise ProviderError("单段语音超过三分钟，请缩短讲解句子。")
                        yield frame
                if total == 0 or remainder:
                    raise ProviderError("语音服务返回空音频或不完整音频。")
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)

    async def prepare(self, chapters, roles, provider, progress):
        jobs = [(sentence, role) for role in roles for sentence in
                [role.greeting] + [s for chapter in chapters for s in chapter["sentences"]]]
        for index, (text, role) in enumerate(jobs):
            async for _ in self.stream(text, role, provider):
                pass
            progress.update(done=index + 1, total=len(jobs))

    def inventory(self, chapters, roles, model):
        return [{"role_id": role.id, "chapter_id": chapter["id"],
                 "cached": sum(self.path(s, role, model).exists() for s in chapter["sentences"]),
                 "total": len(chapter["sentences"])} for role in roles for chapter in chapters]
