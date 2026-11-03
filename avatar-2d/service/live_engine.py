"""Local presenter extension of the pinned LiveTalking Wav2Lip/WebRTC pipeline.

Vendor files stay unchanged. Fay supplies PCM; a single render worker selects the
body and its matching face/coordinates before inference, including during gestures.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from windows_runtime import prepare_runtime
prepare_runtime()

import json
import queue
import threading
import time
from functools import lru_cache
from types import SimpleNamespace

import cv2
import numpy as np
import torch

SOURCE = Path(json.loads((ROOT / 'source-manifest.json').read_text(encoding='utf-8'))['source_directory'])
sys.path.insert(0, str(SOURCE))
from avatars.wav2lip_avatar import LipReal, Wav2Lip
from avatars.base_avatar import AudioFrameData
from server.rtc_manager import RTCManager
from server.session_manager import session_manager


def clear_queue(q):
    with q.mutex:
        q.queue.clear()
        q.not_full.notify_all()


class Assets:
    def __init__(self):
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.dtype = torch.float16 if self.device == 'cuda' and torch.cuda.get_device_capability()[0] >= 8 else torch.float32
        torch.set_num_threads(4)
        if self.device == 'cuda':
            torch.backends.cudnn.benchmark = True
        self.model = Wav2Lip()
        checkpoint = torch.load(ROOT / 'models/wav2lip256.pth', map_location='cpu', weights_only=True)
        self.model.load_state_dict({k.removeprefix('module.'): v for k, v in checkpoint['state_dict'].items()})
        self.model = self.model.to(device=self.device, dtype=self.dtype).eval()
        library = json.loads((ROOT / 'assets/presenter-v1/motions-v1/action-library.json').read_text(encoding='utf-8'))
        self.clips = {}
        for item in library['actions']:
            if not item.get('speech_candidate'):
                continue
            directory = ROOT / 'runtime/avatars' / ('presenter_v1__' + item['id'])
            coords = json.loads((directory / 'coords.json').read_text(encoding='utf-8'))
            if len(coords) != item['frames']:
                raise ValueError('Incomplete prepared motion: ' + item['id'])
            self.clips[item['id']] = (directory, coords)
        # Small face crops are cheap to retain; keep full-body images bounded.
        self.faces = {name: [self.read(directory / 'face_imgs' / f'{i:08d}.png') for i in range(len(coords))]
                      for name, (directory, coords) in self.clips.items()}
        with torch.inference_mode():
            self.model(torch.ones(4, 1, 80, 16, device=self.device, dtype=self.dtype),
                       torch.ones(4, 6, 256, 256, device=self.device, dtype=self.dtype))
        if self.device == 'cuda':
            torch.cuda.synchronize()

    @staticmethod
    def read(path):
        frame = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError('Unreadable prepared image')
        return frame

    @lru_cache(maxsize=32)
    def frame(self, name, index):
        return self.read(self.clips[name][0] / 'full_imgs' / f'{index:08d}.png')


class Presenter(LipReal):
    def __init__(self, opt, assets, callback):
        self.assets = assets
        # LipReal initializes native MelASR and the registered WebRTC output. Text
        # TTS is never started: audio comes exclusively from the existing Fay core.
        super().__init__(opt, assets.model, ([], [], []))
        self.callback = callback
        self.generation = 0
        self.lock = threading.Lock()
        self.reset_requested = threading.Event()
        self.motion_requested = None
        self.pose = ('welcome-wave', 0)
        self.motion = None
        self.motion_index = 0
        self.error = None
        self.stats = dict(video_frames=0, speech_frames=0, motion_frames=0,
                          inference_seconds=0., inference_frames=0, last_motion=None)

    def flush_talk(self):
        with self.lock:
            self.generation += 1
            self.reset_requested.set()
            self.motion_requested = None
            clear_queue(self.asr.queue)

    def request_motion(self, action):
        if action not in self.assets.clips:
            raise ValueError('Unknown action')
        with self.lock:
            self.motion_requested = action

    def enqueue(self, wave, metadata):
        self.enqueue_stream(wave,metadata,start=True,end=True)

    def enqueue_stream(self,wave,metadata,start=False,end=False,generation=None):
        with self.lock:
            if generation is not None and generation!=self.generation:return
            generation=self.generation
            if end:wave=np.pad(wave,(0,(-len(wave))%self.chunk))
            if len(wave)%self.chunk:raise ValueError('Partial audio packet')
            for i in range(0, len(wave), self.chunk):
                info = dict(metadata, generation=generation)
                if start and i == 0:
                    info['status'] = 'start'
                if end and i + self.chunk >= len(wave):
                    info['end'] = True
                self.asr.put_audio_frame(wave[i:i+self.chunk], info)

    def notify(self, eventpoint):
        # Native HumanPlayer invokes this when its audio track sends the packet.
        if eventpoint and eventpoint.get('generation') == self.generation:
            self.callback(eventpoint)

    def get_avatar_length(self):
        return 1

    def _advance(self, packets):
        for packet in packets:
            info = packet.userdata
            if info.get('status') == 'start' and info.get('action') in self.assets.clips:
                self.motion = info['action']
                self.motion_index = 0
                self.stats['last_motion'] = self.motion
        with self.lock:
            if self.motion_requested:
                self.motion = self.motion_requested
                self.motion_index = 0
                self.stats['last_motion'] = self.motion
                self.motion_requested = None
        if self.motion:
            self.pose = (self.motion, self.motion_index)
            self.motion_index += 1
            self.stats['motion_frames'] += 1
            if self.motion_index == len(self.assets.clips[self.motion][1]):
                self.motion = None
        return self.pose

    def _infer(self, tokens, features):
        faces = np.asarray([self.assets.faces[name][i] for name, i in tokens])
        masked = faces.copy()
        masked[:, 128:] = 0
        image = np.concatenate([masked, faces], axis=3).astype(np.float32) / 255
        x = torch.from_numpy(image.transpose(0, 3, 1, 2).copy()).to(device=self.assets.device, dtype=self.assets.dtype)
        a = torch.from_numpy(np.asarray(features, dtype=np.float32)[:, None].copy()).to(device=self.assets.device, dtype=self.assets.dtype)
        started = time.perf_counter()
        with torch.inference_mode():
            pred = self.model(a, x)
        pred = (pred.float().cpu().numpy().transpose(0, 2, 3, 1) * 255).clip(0, 255).astype(np.uint8)
        self.stats['inference_seconds'] += time.perf_counter() - started
        self.stats['inference_frames'] += len(tokens)
        return pred

    def _compose(self, token, prediction):
        name, index = token
        frame = self.assets.frame(name, index).copy()
        if prediction is not None:
            y1, y2, x1, x2 = self.assets.clips[name][1][index]
            h, w = y2-y1, x2-x1
            p = cv2.resize(prediction, (w, h))
            yy, xx = np.mgrid[0:h, 0:w]
            edge = np.minimum(np.minimum(xx, w-1-xx), np.minimum(yy, h-1-yy))
            alpha = (np.clip((yy/h-.42)/.18, 0, 1)*np.clip(edge/6, 0, 1))[..., None]
            frame[y1:y2, x1:x2] = (p*alpha + frame[y1:y2, x1:x2]*(1-alpha)).astype(np.uint8)
        return frame

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
                        self.motion = None
                        self.pose = ('welcome-wave', 0)
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
                self.asr.run_step()
                features = self.asr.feat_queue.get(timeout=2)
                packets = [self.asr.output_queue.get(timeout=2) for _ in range(self.batch_size*2)]
                for p in packets:
                    if p.type == 0 and p.userdata.get('generation') != generation:
                        p.data = np.zeros(self.chunk, np.float32)
                        p.type = 1
                        p.userdata = {}
                tokens = [self._advance(packets[i*2:i*2+2]) for i in range(self.batch_size)]
                speaking = [any(p.type == 0 for p in packets[i*2:i*2+2]) for i in range(self.batch_size)]
                pred = self._infer(tokens, features) if any(speaking) else [None]*self.batch_size
                for i, token in enumerate(tokens):
                    with self.lock:
                        if generation != self.generation or quit_event.is_set():
                            break
                        self.speaking = speaking[i]
                        self.output.push_video_frame(self._compose(token, pred[i] if speaking[i] else None))
                        self.stats['video_frames'] += 1
                        self.stats['speech_frames'] += int(speaking[i])
                        for p in packets[i*2:i*2+2]:
                            self.output.push_audio_frame((p.data*32767).clip(-32768, 32767).astype(np.int16), p.userdata)
        except Exception as exc:
            self.error = type(exc).__name__
            self.callback({'error': '实时渲染中断，请重新连接展示。'})
        finally:
            self.speaking = False
            self.output.stop()


def options(sessionid=''):
    return SimpleNamespace(sessionid=sessionid, fps=25, batch_size=4, l=10, r=10,
                           customopt=[], tts='edgetts', transport='webrtc',
                           REF_FILE='', REF_TEXT='', stun='', max_session=1)
