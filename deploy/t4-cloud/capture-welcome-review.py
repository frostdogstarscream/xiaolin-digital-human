"""Capture one welcome utterance for all three offline comparison variants."""
import asyncio
import audioop
import base64
import hashlib
import json
import sys
import wave
from pathlib import Path

sys.path.insert(0, '/formal/avatar-2d/experiments/qwen-realtime-v2')
from provider import QwenConnection

OUTPUT = Path('/formal/smile-review-20261111')
TEXT = '你好，欢迎你！很高兴为你服务。'


async def main():
    target = OUTPUT / 'welcome-16k.wav'
    if target.exists():
        print('REUSING_FROZEN_WELCOME_AUDIO')
        return
    provider = QwenConnection(instructions='你是小霖。请逐字朗读用户给出的中文欢迎语，语气自然亲切，只说原句。')
    chunks = []
    transcript = []
    try:
        await provider.connect()
        await provider.send('conversation.item.create', item=dict(type='message', role='user',
                            content=[dict(type='input_text', text=TEXT)]))
        await provider.send('response.create', response=dict(modalities=['audio', 'text']))
        while True:
            event = await asyncio.wait_for(provider.receive(), 45)
            if event['type'] == 'response.audio.delta':
                chunks.append(base64.b64decode(event['delta']))
            elif event['type'] == 'response.audio_transcript.delta':
                transcript.append(event['delta'])
            elif event['type'] == 'response.done':
                assert event['response']['status'] == 'completed', event['response']['status']
                break
    finally:
        await provider.close()
    assert chunks, 'Provider returned no audio'
    pcm, _ = audioop.ratecv(b''.join(chunks), 2, 1, 24000, 16000, None)
    with wave.open(str(target), 'wb') as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(pcm)
    record = dict(text=TEXT, transcript=''.join(transcript), sample_rate=16000,
                  seconds=len(pcm) / 32000, sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                  cloud_calls=1, voice='longanqian_v3.1')
    (OUTPUT / 'audio.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
    print(json.dumps(record, ensure_ascii=False))


asyncio.run(main())
