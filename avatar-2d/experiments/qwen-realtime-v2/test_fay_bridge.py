import io
import json
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from capabilities import Settings
from fay_bridge import (
    FayVoiceBuffer,
    decode_audio_to_pcm16k,
    format_persona_prompt,
    infer_gesture_from_text,
    make_tool_alias,
    sanitize_tool_schema,
)


class FayBridgeTests(unittest.TestCase):
    def test_persona_prompt_formatting(self):
        prompt = format_persona_prompt({'name': '小霖', 'job': '展厅顾问', 'additional': '声音温柔，简洁回答。'})
        self.assertIn('小霖', prompt)
        self.assertIn('展厅顾问', prompt)
        self.assertIn('声音温柔', prompt)

    def test_sanitize_tool_schema_and_alias(self):
        raw = {
            '$schema': 'http://json-schema.org/draft-07/schema#',
            '$defs': {'Item': {'type': 'string'}},
            'type': 'object',
            'properties': {
                'city': {'type': ['string', 'null'], 'description': '城市', 'examples': ['北京']},
                'days': {'type': 'integer'},
            },
            'required': ['city', 'missing_field'],
        }
        cleaned = sanitize_tool_schema(raw)
        self.assertNotIn('$schema', cleaned)
        self.assertNotIn('$defs', cleaned)
        self.assertEqual(cleaned['required'], ['city'])
        self.assertEqual(cleaned['properties']['city']['type'], 'string')
        used = {'coordinate_turn'}
        a1 = make_tool_alias('weather.query', used)
        a2 = make_tool_alias('weather.query', used)
        self.assertEqual(a1, 'mcp__weather_query')
        self.assertEqual(a2, 'mcp__weather_query_2')

    def test_fay_voice_buffer_vad(self):
        vad = FayVoiceBuffer()
        silence = b'\x00\x00' * 1600  # 100ms
        loud = struct.pack('<' + 'h' * 1600, *([1500, -1500] * 800))
        started_count = 0
        utterance = None
        started, utt = vad.feed(silence)
        self.assertFalse(started)
        self.assertIsNone(utt)
        for _ in range(4):
            s, utt = vad.feed(loud)
            if s:
                started_count += 1
        self.assertEqual(started_count, 1)
        for _ in range(7):
            _, u = vad.feed(silence)
            if u is not None:
                utterance = u
        self.assertIsNotNone(utterance)
        self.assertGreaterEqual(len(utterance), 3200 * 4)

    def test_decode_wav_to_pcm16k(self):
        buf = io.BytesIO()
        samples = [int(4000 * ((i % 20) / 20.0 - 0.5)) for i in range(4800)]  # 24kHz stereo-less 0.2s
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(struct.pack('<' + 'h' * len(samples), *samples))
        pcm = decode_audio_to_pcm16k(buf.getvalue(), 'test.wav')
        # 0.2s at 16kHz * 2 bytes = ~6400 bytes
        self.assertAlmostEqual(len(pcm), 6400, delta=64)

    def test_settings_dialogue_mode_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Settings(Path(tmp))
            self.assertEqual(s.public()['dialogue_mode'], 'qwen_realtime')
            base = {k: v for k, v in s.public().items() if k != 'revision'}
            updated = s.update({**base, 'dialogue_mode': 'fay_agent'})
            self.assertEqual(updated['dialogue_mode'], 'fay_agent')
            # Backward compat: omitting dialogue_mode keeps current value
            kept = s.update({k: v for k, v in base.items() if k != 'dialogue_mode'})
            self.assertEqual(kept['dialogue_mode'], 'fay_agent')
            with self.assertRaises(ValueError):
                s.update({**base, 'dialogue_mode': 'invalid_mode'})

    def test_infer_gesture_fallback(self):
        self.assertEqual(infer_gesture_from_text('欢迎来到展馆！'), 'welcome-wave')
        self.assertEqual(infer_gesture_from_text('好的，没问题'), 'acknowledge-nod')
        self.assertEqual(infer_gesture_from_text('再见，欢迎下次光临！'), 'goodbye-wave')


if __name__ == '__main__':
    unittest.main(verbosity=2)
