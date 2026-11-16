import math,struct,unittest
from wake_gate import WakeBuffer,wake_question,wav_bytes
import io,wave

class WakeTests(unittest.TestCase):
    def test_prefix_and_homophones(self):
        for text in ['小霖小霖，我要打卡。','小林，小林，我要打卡。','你好，小琳小琳，我要打卡。']:
            self.assertEqual(wake_question(text),'我要打卡。')
    def test_word_only(self):
        self.assertEqual(wake_question('小霖小霖。'),'')
    def test_not_a_wake_prefix(self):
        for text in ['我要打卡','唤醒词是不是小霖小霖','请不要说小霖小霖','我叫小林','小霖']:
            self.assertIsNone(wake_question(text))
    def test_silence_never_recognized(self):
        buffer=WakeBuffer()
        for _ in range(200):self.assertIsNone(buffer.feed(bytes(3200)))
    def test_one_utterance_and_reset(self):
        buffer=WakeBuffer();tone=b''.join(struct.pack('<h',int(4000*math.sin(i*2*math.pi*400/16000))) for i in range(1600))
        for _ in range(10):self.assertIsNone(buffer.feed(tone))
        outputs=[buffer.feed(bytes(3200)) for _ in range(10)];self.assertEqual(sum(bool(x) for x in outputs),1)
        with wave.open(io.BytesIO(wav_bytes(next(x for x in outputs if x))),'rb') as audio:self.assertEqual((audio.getframerate(),audio.getnchannels(),audio.getsampwidth()),(16000,1,2))
    def test_short_noise_discarded(self):
        buffer=WakeBuffer();self.assertIsNone(buffer.feed(struct.pack('<h',3000)*1600))
        self.assertTrue(all(buffer.feed(bytes(3200)) is None for _ in range(10)))

if __name__=='__main__':unittest.main()
