"""Prepare isolated SAPI audio for testing the real native playback path without cloud calls."""
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service.store import Store
from service.speech import SpeechCache

root = Path(__file__).resolve().parents[1] / 'runtime/native-smoke'
text = (root / 'speech-test.txt').read_text(encoding='utf-8-sig')
with wave.open(str(root / 'speech-test.wav'), 'rb') as audio:
    assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 24000)
    pcm = audio.readframes(audio.getnframes())
with_store = Store(root)
try:
    settings = with_store.settings
    settings.roles[0].name = '本地声音测试（非百炼）'
    settings.roles[0].voice = 'windows-huihui-test'
    settings.roles[0].greeting = text
    settings.display.fullscreen = False
    with_store.save_settings(settings)
    chapters = with_store.get('chapters')
    for chapter in chapters:
        chapter['sentences'] = [text, text]
    with_store.set('chapters', chapters)
    SpeechCache(with_store).path(text, settings.role, settings.ai.tts_model).write_bytes(pcm)
    print(f'Prepared isolated local audio: {len(pcm)/48000:.2f} seconds; no cloud calls.')
finally:
    with_store.close()
