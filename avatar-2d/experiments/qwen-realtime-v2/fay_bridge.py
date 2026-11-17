"""Bridge to the local Fay core (5000), Fay MCP service (5010), and Fay human output WS (10002).

Supports:
  1. Mode A (qwen_realtime): live persona sync from Fay config.attribute + dynamic discovery
     and execution of all enabled online MCP tools from Fay MCP Center (5010).
  2. Mode B (fay_agent): full Fay cognitive flow (FunASR STT -> Fay /v1/chat/completions SSE
     subtitles -> Fay WS 10002 TTS audio/action stream + DashScope fallback TTS -> 50fps engine).
"""
import asyncio
import audioop
import base64
from collections import deque
import configparser
import inspect
import io
import json
import math
import os
from pathlib import Path
import re
import time
import uuid
import wave
import aiohttp
import websockets

ROOT = Path(__file__).resolve().parents[2]
FAY_HTTP = os.environ.get('XIAOLIN_FAY_URL', 'http://127.0.0.1:5000').rstrip('/')
FAY_MCP_HTTP = os.environ.get('XIAOLIN_FAY_MCP_URL', 'http://127.0.0.1:5010').rstrip('/')
FAY_WS_OUTPUT = os.environ.get('XIAOLIN_FAY_WS_URL', 'ws://127.0.0.1:10002')
FAY_USER = 'Avatar2D'

DEFAULT_XIAOLIN_PERSONA = {
    'name': '小霖',
    'gender': '女',
    'age': '24岁',
    'job': '智能数字人讲解员与顾问',
    'position': '专业亲切、自然温暖的女性数字人助手',
    'goal': '为用户提供清晰、准确、贴心的讲解与业务服务',
    'hobby': '科技数码、展览讲解、与人交流',
    'additional': '说话亲切自然、口语化，默认一到两句话，不超过100字，不输出JSON或控制符号。',
}

ACTION_CODE_MAP = {
    'greeting.hello': 'welcome-wave',
    'greeting.welcome': 'welcome-wave',
    'farewell.goodbye': 'goodbye-wave',
    'dialogue.confirm': 'acknowledge-nod',
    'dialogue.explain': 'explain-open-palms',
    'dialogue.recommend': 'explain-open-palms',
    'dialogue.summary': 'explain-open-palms',
    'guidance.invite': 'welcome-wave',
}
BEHAVIOR_MAP = {
    'nod': 'acknowledge-nod',
    'explain': 'explain-open-palms',
    'invite': 'welcome-wave',
    'welcome': 'welcome-wave',
    'goodbye': 'goodbye-wave',
}


def map_fay_action(action_obj):
    if isinstance(action_obj, dict):
        gesture = str(action_obj.get('gesture') or '')
        if gesture in ('welcome-wave', 'goodbye-wave', 'acknowledge-nod', 'explain-open-palms'):
            return gesture
        code = str(action_obj.get('code') or '')
        behavior = str(action_obj.get('behavior') or '')
        if code in ACTION_CODE_MAP:
            return ACTION_CODE_MAP[code]
        if behavior in BEHAVIOR_MAP:
            return BEHAVIOR_MAP[behavior]
    return 'idle'


def infer_gesture_from_text(text):
    value = str(text or '').strip()
    if not value:
        return 'idle'
    if any(word in value for word in ('再见', '拜拜', '下次见', '慢走', '告辞')):
        return 'goodbye-wave'
    if any(word in value for word in ('欢迎', '你好', '您好', '很高兴认识', '很高兴见到', '初次见面')):
        return 'welcome-wave'
    if len(value) >= 24 and any(ch in value for ch in ('，', '。', '；', '1.', '、')):
        return 'explain-open-palms'
    if any(word in value for word in ('好的', '没问题', '收到', '明白', '可以的', '当然可以')):
        return 'acknowledge-nod'
    return 'idle'


def _read_bailian_tts_config():
    path = Path(os.environ.get('FAY_SYSTEM_CONF', str(ROOT.parent / 'fay-ue4/runtime/fay-local/app/system.conf')))
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(path, encoding='utf-8-sig')
    if 'key' not in cfg:
        return {}
    key = cfg['key']
    api_key = key.get('bailian_tts_api_key', key.get('gpt_api_key', '')).strip()
    base_url = key.get('bailian_tts_base_url', '') or key.get('gpt_base_url', '')
    host = 'dashscope-intl.aliyuncs.com' if 'intl' in base_url else 'dashscope.aliyuncs.com'
    return {
        'api_key': api_key,
        'realtime_model': key.get('bailian_tts_realtime_model', 'qwen3-tts-flash-realtime').strip() or 'qwen3-tts-flash-realtime',
        'realtime_url': f'wss://{host}/api-ws/v1/realtime',
        'voice': key.get('bailian_tts_voice', 'Cherry').strip() or 'Cherry',
    }


async def fetch_persona(http, timeout_s=2.5):
    """Fetch attribute persona, full config, and liveState from Fay :5000.

    Fay /api/get-data returns JSON serialized with text/html Content-Type, so always use loads(text()).
    """
    try:
        async with http.post(f'{FAY_HTTP}/api/get-data', timeout=aiohttp.ClientTimeout(total=timeout_s)) as resp:
            if resp.status != 200:
                return {}, {}, None
            payload = json.loads(await resp.text())
            config = payload.get('config') or {}
            attr = config.get('attribute') or {}
            return (dict(attr) if isinstance(attr, dict) else {}), config, None
    except Exception:
        return {}, {}, None


async def get_fay_run_status(http, timeout_s=2.0):
    try:
        async with http.post(f'{FAY_HTTP}/api/get-run-status', timeout=aiohttp.ClientTimeout(total=timeout_s)) as resp:
            if resp.status != 200:
                return None
            payload = json.loads(await resp.text())
            return payload.get('status') is True
    except Exception:
        return None


async def ensure_default_xiaolin_persona(http):
    """Populate default Xiaolin persona only if Fay still carries placeholder 'Feifei' or empty name."""
    attr, _, _ = await fetch_persona(http)
    if not attr:
        return dict(DEFAULT_XIAOLIN_PERSONA)
    name = str(attr.get('name') or '').strip()
    additional = str(attr.get('additional') or '').strip()
    if name in ('', 'Feifei', 'Fay') and not additional:
        try:
            body = json.dumps({'config': {'attribute': DEFAULT_XIAOLIN_PERSONA}}, ensure_ascii=False)
            async with http.post(
                f'{FAY_HTTP}/api/submit',
                data={'data': body},
                timeout=aiohttp.ClientTimeout(total=3.0),
            ) as resp:
                if resp.status == 200:
                    return dict(DEFAULT_XIAOLIN_PERSONA)
        except Exception:
            pass
    return attr


def format_persona_prompt(attr):
    """Build a concise Chinese system persona prompt from Fay's attribute dictionary."""
    if not isinstance(attr, dict) or not any(str(v or '').strip() for v in attr.values()):
        attr = DEFAULT_XIAOLIN_PERSONA
    name = str(attr.get('name') or '').strip() or '小霖'
    gender = str(attr.get('gender') or '').strip()
    age = str(attr.get('age') or '').strip()
    birth = str(attr.get('birth') or '').strip()
    zodiac = str(attr.get('zodiac') or '').strip()
    constellation = str(attr.get('constellation') or '').strip()
    job = str(attr.get('job') or '').strip()
    position = str(attr.get('position') or '').strip()
    goal = str(attr.get('goal') or '').strip()
    hobby = str(attr.get('hobby') or '').strip()
    contact = str(attr.get('contact') or '').strip()
    additional = str(attr.get('additional') or '').strip()

    parts = [f'你是数字人“{name}”。']
    traits = []
    if gender:
        traits.append(f'性别：{gender}')
    if age:
        traits.append(f'年龄：{age}')
    if birth:
        traits.append(f'出生地：{birth}')
    if zodiac:
        traits.append(f'生肖：{zodiac}')
    if constellation:
        traits.append(f'星座：{constellation}')
    if job:
        traits.append(f'职业/身份：{job}')
    if position:
        traits.append(f'定位：{position}')
    if goal:
        traits.append(f'目标：{goal}')
    if hobby:
        traits.append(f'爱好：{hobby}')
    if contact:
        traits.append(f'联系方式：{contact}')
    if traits:
        parts.append('人物设定：' + '；'.join(traits) + '。')
    if additional:
        parts.append('性格与表达风格：' + additional)
    else:
        parts.append('使用中文口语自然回答，默认一到两句话，不超过100字。不输出JSON或控制标签。')
    return ''.join(parts)


_STRIP_SCHEMA_KEYS = {'$schema', '$id', '$defs', 'definitions', '$ref', 'examples', 'default', 'title'}


def _clean_schema_node(node, depth=0):
    if not isinstance(node, dict) or depth > 5:
        return {'type': 'string'}
    out = {}
    node_type = node.get('type')
    if isinstance(node_type, list):
        non_null = [t for t in node_type if t != 'null']
        node_type = non_null[0] if non_null else 'string'
    if not isinstance(node_type, str) or node_type not in ('object', 'array', 'string', 'number', 'integer', 'boolean'):
        if 'properties' in node:
            node_type = 'object'
        elif 'items' in node:
            node_type = 'array'
        else:
            node_type = 'string'
    out['type'] = node_type
    if isinstance(node.get('description'), str) and node['description'].strip():
        out['description'] = node['description'].strip()[:220]
    if isinstance(node.get('enum'), list) and node['enum']:
        out['enum'] = node['enum'][:20]
    if node_type == 'object':
        raw_props = node.get('properties') if isinstance(node.get('properties'), dict) else {}
        clean_props = {str(k): _clean_schema_node(v, depth + 1) for k, v in raw_props.items() if str(k)}
        out['properties'] = clean_props
        req = [str(r) for r in (node.get('required') or []) if str(r) in clean_props]
        if req:
            out['required'] = req
        out['additionalProperties'] = False
    elif node_type == 'array':
        items = node.get('items')
        out['items'] = _clean_schema_node(items, depth + 1) if isinstance(items, dict) else {'type': 'string'}
    for k in list(out.keys()):
        if k in _STRIP_SCHEMA_KEYS:
            out.pop(k, None)
    return out


def sanitize_tool_schema(schema):
    cleaned = _clean_schema_node(schema if isinstance(schema, dict) else {'type': 'object', 'properties': {}})
    if cleaned.get('type') != 'object':
        return {'type': 'object', 'properties': {}, 'additionalProperties': False}
    cleaned.setdefault('properties', {})
    return cleaned


def make_tool_alias(raw_name, used):
    slug = re.sub(r'[^a-zA-Z0-9_-]', '_', str(raw_name or 'tool')).strip('_') or 'tool'
    candidate = ('mcp__' + slug)[:64]
    idx = 2
    base = candidate[:58]
    while candidate in used:
        candidate = f'{base}_{idx}'
        idx += 1
    used.add(candidate)
    return candidate


async def fetch_mcp_tools(http, timeout_s=3.0):
    """Discover enabled+available online MCP tools from Fay MCP Center (:5010)."""
    try:
        async with http.get(f'{FAY_MCP_HTTP}/api/mcp/servers/online/tools', timeout=aiohttp.ClientTimeout(total=timeout_s)) as resp:
            if resp.status != 200:
                return []
            data = json.loads(await resp.text())
    except Exception:
        return []
    raw_tools = data.get('tools') or []
    used = {'coordinate_turn'}
    items = []
    for t in raw_tools:
        if not isinstance(t, dict):
            continue
        if not (t.get('enabled') and t.get('available')):
            continue
        name = str(t.get('name') or '').strip()
        server_id = t.get('server_id')
        if not name or server_id is None:
            continue
        alias = make_tool_alias(name, used)
        raw_schema = t.get('inputSchema') or t.get('input_schema') or t.get('parameters') or {}
        params = sanitize_tool_schema(raw_schema)
        items.append({
            'name': name,
            'alias': alias,
            'server_id': server_id,
            'server_name': t.get('server_name') or '',
            'description': str(t.get('description') or f'调用 MCP 工具 {name}')[:300],
            'parameters': params,
        })
    return items


def to_openai_tool_defs(mcp_tools):
    return [
        {
            'type': 'function',
            'function': {
                'name': item['alias'],
                'description': item['description'],
                'parameters': item['parameters'],
            },
        }
        for item in mcp_tools
    ]


def collect_mcp_texts(value):
    texts = []
    def walk(node):
        if isinstance(node, str):
            texts.append(node)
        elif isinstance(node, dict):
            if node.get('isError'):
                raise RuntimeError('MCP returned an error')
            for key in ('text', 'content', 'result'):
                if key in node:
                    walk(node[key])
        elif isinstance(node, list):
            for entry in node:
                walk(entry)
    walk(value)
    return texts


async def execute_mcp_tool(http, server_id, method_name, params=None, timeout_s=20.0):
    try:
        url = f'{FAY_MCP_HTTP}/api/mcp/servers/{server_id}/call'
        async with http.post(
            url,
            json={'method': method_name, 'params': params if isinstance(params, dict) else {}},
            timeout=aiohttp.ClientTimeout(total=timeout_s),
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f'MCP HTTP {resp.status}')
            called = json.loads(await resp.text())
        payload = called.get('result')
        texts = collect_mcp_texts(payload)
        ok = called.get('success') is True
        is_placeholder = method_name == 'attendance_check_in'
        if is_placeholder:
            ok = ok and any(t.strip() == 'success' for t in texts)
            msg = '占位打卡测试成功；未连接真实考勤系统。' if ok else 'MCP未返回成功，不能声称已打卡。'
        else:
            joined = '\n'.join(t.strip() for t in texts if t and t.strip())
            msg = joined or ('执行成功' if ok else 'MCP 调用未成功')
        return {
            'ok': ok,
            'status': 'success' if ok else 'failed',
            'executed': ok,
            'tool': method_name,
            'server_id': server_id,
            'placeholder': is_placeholder,
            'texts': texts,
            'result': payload,
            'message': msg,
        }
    except Exception as error:
        return {
            'ok': False,
            'status': 'failed',
            'executed': False,
            'tool': method_name,
            'server_id': server_id,
            'error_type': type(error).__name__,
            'message': f'MCP 工具调用失败：{type(error).__name__}',
        }


async def reconnect_mcp_servers(http, target_ids=None, include_autostart=True, timeout_s=5.0):
    """Ensure Fay MCP clients remain connected after Fay stop-live or startup."""
    try:
        async with http.get(f'{FAY_MCP_HTTP}/api/mcp/servers', timeout=aiohttp.ClientTimeout(total=timeout_s)) as r:
            if r.status != 200:
                return []
            servers = json.loads(await r.text())
    except Exception:
        return []
    if not isinstance(servers, list):
        return []
    want = set(target_ids or ())
    online_ids = []
    for srv in servers:
        if not isinstance(srv, dict) or srv.get('id') is None:
            continue
        sid = srv['id']
        if srv.get('status') == 'online':
            online_ids.append(sid)
            continue
        if sid in want or (include_autostart and srv.get('autostart')):
            try:
                async with http.post(
                    f'{FAY_MCP_HTTP}/api/mcp/servers/{sid}/connect',
                    timeout=aiohttp.ClientTimeout(total=timeout_s),
                ) as cr:
                    if cr.status == 200:
                        online_ids.append(sid)
            except Exception:
                pass
    return online_ids


async def ensure_fay_live(http, running: bool, timeout_s=25.0):
    """Ensure Fay core live loop (:5000 start-live/stop-live) matches target boolean."""
    current = await get_fay_run_status(http)
    if current is None:
        return False
    if bool(current) == bool(running):
        return True
    try:
        if running:
            async with http.post(f'{FAY_HTTP}/api/start-live', timeout=aiohttp.ClientTimeout(total=timeout_s)) as r:
                if r.status != 200:
                    return False
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if await get_fay_run_status(http):
                    return True
                await asyncio.sleep(0.25)
            return bool(await get_fay_run_status(http))
        else:
            prev_online = []
            try:
                async with http.get(f'{FAY_MCP_HTTP}/api/mcp/servers', timeout=aiohttp.ClientTimeout(total=3.0)) as mr:
                    if mr.status == 200:
                        prev_online = [s['id'] for s in json.loads(await mr.text()) if isinstance(s, dict) and s.get('status') == 'online']
            except Exception:
                pass
            try:
                async with http.post(f'{FAY_HTTP}/to-stop-talking', json={'username': FAY_USER}, timeout=aiohttp.ClientTimeout(total=3.0)) as r:
                    await r.read()
            except Exception:
                pass
            async with http.post(f'{FAY_HTTP}/api/stop-live', timeout=aiohttp.ClientTimeout(total=timeout_s)) as r:
                ok = r.status == 200
            # fay_booter.stop() disconnects MCP clients; immediately restore online & autostart MCP servers for Mode A.
            if ok:
                await reconnect_mcp_servers(http, target_ids=prev_online, include_autostart=True)
            return ok
    except Exception:
        return False


async def interrupt_fay(http):
    for route, body in (('/to-stop-talking', {'username': FAY_USER}), ('/api/execution-cancel', {})):
        try:
            async with http.post(f'{FAY_HTTP}{route}', json=body, timeout=aiohttp.ClientTimeout(total=3.0)) as r:
                await r.read()
        except Exception:
            pass


class FayVoiceBuffer:
    """16kHz int16 mono server-side VAD for Mode B (Fay brain)."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.preroll = deque(maxlen=4)
        self.parts = []
        self.active = False
        self.onset_streak = 0
        self.seconds = 0.0
        self.silence = 0.0
        self.speech = 0.0

    def feed(self, pcm):
        """Feed 16kHz int16 PCM chunk. Returns (speech_started: bool, utterance_pcm: bytes | None)."""
        if not pcm or len(pcm) % 2:
            return False, None
        duration = (len(pcm) // 2) / 16000.0
        rms = audioop.rms(pcm, 2)
        if not self.active:
            if rms >= 520:
                self.onset_streak += 1
            else:
                self.onset_streak = 0
                self.preroll.append(pcm)
                return False, None
            self.preroll.append(pcm)
            if self.onset_streak >= 3:
                self.active = True
                self.parts = list(self.preroll)
                self.preroll.clear()
                self.seconds = sum(len(p) for p in self.parts) / 32000.0
                self.speech = self.seconds
                self.silence = 0.0
                return True, None
            return False, None

        self.parts.append(pcm)
        self.seconds += duration
        if rms >= 340:
            self.silence = 0.0
            self.speech += duration
        else:
            self.silence += duration

        if self.seconds >= 12.0 or self.silence >= 0.55:
            result = b''.join(self.parts) if self.speech >= 0.25 else None
            self.reset()
            return False, result
        return False, None


def decode_audio_to_pcm16k(raw_bytes, filename=''):
    """Decode WAV or MP3/compressed bytes into 16kHz mono int16 little-endian PCM."""
    if not raw_bytes:
        return b''
    if raw_bytes[:4] == b'RIFF' and raw_bytes[8:12] == b'WAVE':
        with wave.open(io.BytesIO(raw_bytes), 'rb') as wf:
            ch = wf.getnchannels()
            sw = wf.getsampwidth()
            sr = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
        if sw != 2:
            frames = audioop.lin2lin(frames, sw, 2)
        if ch == 2:
            frames = audioop.tomono(frames, 2, 0.5, 0.5)
        elif ch > 2:
            import numpy as np
            arr = np.frombuffer(frames, dtype='<i2').reshape(-1, ch)
            frames = arr[:, 0].astype('<i2').tobytes()
        if sr != 16000:
            frames, _ = audioop.ratecv(frames, 2, 1, sr, 16000, None)
        return frames

    # Compressed formats (e.g., MP3 from edge-tts) decoded via PyAV
    import av
    resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
    out = bytearray()
    with av.open(io.BytesIO(raw_bytes)) as container:
        for frame in container.decode(audio=0):
            for resampled in resampler.resample(frame):
                out.extend(resampled.to_ndarray().tobytes())
        for resampled in resampler.resample(None):
            out.extend(resampled.to_ndarray().tobytes())
    return bytes(out)


async def synthesize_fallback_pcm16k(text):
    """Synthesize reply via DashScope Realtime TTS when Fay core WS 10002 emits no audio."""
    cfg = _read_bailian_tts_config()
    api_key = cfg.get('api_key')
    if not api_key or not str(text or '').strip():
        return b''
    out_chunks = bytearray()
    rate_state = None
    url = f"{cfg['realtime_url']}?model={cfg['realtime_model']}"
    hdr_kw = 'additional_headers' if 'additional_headers' in inspect.signature(websockets.connect).parameters else 'extra_headers'
    try:
        async with websockets.connect(
            url,
            **{hdr_kw: {'Authorization': 'Bearer ' + api_key}},
            open_timeout=10,
            close_timeout=2,
            max_size=4 * 1024 * 1024,
        ) as sock:
            async def send(kind, **data):
                await sock.send(json.dumps({'event_id': 'evt_' + uuid.uuid4().hex, 'type': kind, **data}, ensure_ascii=False))

            created = json.loads(await asyncio.wait_for(sock.recv(), timeout=12))
            if created.get('type') != 'session.created':
                return b''
            await send('session.update', session={
                'mode': 'commit',
                'voice': cfg['voice'],
                'language_type': 'Chinese',
                'response_format': 'pcm',
                'sample_rate': 24000,
            })
            while True:
                ev = json.loads(await asyncio.wait_for(sock.recv(), timeout=12))
                if ev.get('type') == 'session.updated':
                    break
                if ev.get('type') == 'error':
                    return b''
            await send('input_text_buffer.append', text=str(text).strip()[:600])
            await send('input_text_buffer.commit')
            deadline = time.monotonic() + 45.0
            while time.monotonic() < deadline:
                ev = json.loads(await asyncio.wait_for(sock.recv(), timeout=20))
                kind = ev.get('type')
                if kind == 'response.audio.delta':
                    raw24 = base64.b64decode(ev.get('delta', ''), validate=True)
                    if raw24 and len(raw24) % 2 == 0:
                        converted, rate_state = audioop.ratecv(raw24, 2, 1, 24000, 16000, rate_state)
                        out_chunks.extend(converted)
                elif kind in ('response.done', 'error'):
                    break
            try:
                await send('session.finish')
            except Exception:
                pass
    except Exception:
        return b''
    return bytes(out_chunks)


class FayTurnRunner:
    """Connects to Fay WS 10002 output + SSE /v1/chat/completions for Mode B execution."""

    def __init__(self, http):
        self.http = http
        self.ws_task = None
        self.ws_connected = False
        self.active_turn_id = None
        self.audio_queue = asyncio.Queue(maxsize=64)
        self.running = False

    def start(self):
        if self.running:
            return
        self.running = True
        self.ws_task = asyncio.create_task(self._ws_loop())

    async def stop(self):
        self.running = False
        if self.ws_task:
            self.ws_task.cancel()
            await asyncio.gather(self.ws_task, return_exceptions=True)
            self.ws_task = None
        self.ws_connected = False

    def _drain_queue(self):
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _ws_loop(self):
        while self.running:
            try:
                async with self.http.ws_connect(FAY_WS_OUTPUT, heartbeat=15) as ws:
                    await ws.send_json({'Username': FAY_USER, 'Output': True})
                    self.ws_connected = True
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        try:
                            payload = json.loads(msg.data)
                        except (ValueError, TypeError):
                            continue
                        if payload.get('Topic') != 'human' or payload.get('Username') != FAY_USER:
                            continue
                        data = payload.get('Data') or {}
                        if data.get('Key') != 'audio':
                            continue
                        if not self.active_turn_id:
                            continue
                        item = {
                            'turn_id': self.active_turn_id,
                            'value': str(data.get('Value') or ''),
                            'http_value': str(data.get('HttpValue') or ''),
                            'text': str(data.get('Text') or ''),
                            'action': data.get('Action'),
                            'is_first': bool(data.get('IsFirst')),
                            'is_end': bool(data.get('IsEnd')),
                        }
                        try:
                            self.audio_queue.put_nowait(item)
                        except asyncio.QueueFull:
                            pass
            except asyncio.CancelledError:
                raise
            except Exception:
                self.ws_connected = False
                await asyncio.sleep(2.0)
            self.ws_connected = False

    async def run_turn(self, session, turn, text):
        """Execute one Mode B turn through Fay /v1/chat/completions + WS 10002 audio + fallback TTS."""
        self.start()
        self._drain_queue()
        self.active_turn_id = turn['id']
        turn_id = turn['id']
        response_id = 'fay_' + uuid.uuid4().hex
        session.response = response_id
        session.idle.clear()
        job = {
            'id': response_id,
            'generation': session.p.generation,
            'created_at': time.monotonic(),
            'pending': b'',
            'rate_state': None,
            'started': False,
            'audio_bytes': 0,
            'delta_count': 0,
            'text': '',
            'turn': turn,
            'calls': [],
        }
        session.jobs[response_id] = job
        if len(session.jobs) > 128:
            for k in list(session.jobs)[:-64]:
                session.jobs.pop(k, None)
        await session.emit('response_started', response_id=response_id)

        chat_done = asyncio.Event()
        seen_end_signal = False
        reply_parts = []
        audio_started = False
        gesture_planned = False

        async def pump_pcm_bytes(pcm16k, action_obj=None, text_hint=''):
            nonlocal audio_started, gesture_planned
            if not pcm16k or turn.get('cancelled') or session.turn is not turn:
                return
            if 'first_pcm_at' not in job:
                job['first_pcm_at'] = time.monotonic()
            if not gesture_planned and session.gateway.settings.enabled('gestures'):
                g = map_fay_action(action_obj)
                if g == 'idle':
                    g = 'welcome-wave' if turn.get('wake_first') else infer_gesture_from_text(text_hint or ''.join(reply_parts))
                session.plan_gesture(g)
                gesture_planned = True
            audio_started = True
            job['audio_bytes'] += len(pcm16k)
            job['pending'] += pcm16k
            count = max(0, (len(job['pending']) - 1) // 640) * 640
            if count:
                session.enqueue(job, job['pending'][:count], end=False)
                job['pending'] = job['pending'][count:]
                job['delta_count'] += 1
                await session.emit('audio_progress', response_id=response_id, seconds=job['audio_bytes'] / 32000.0)

        async def fetch_sse():
            try:
                live_ok = await ensure_fay_live(self.http, True)
                if not live_ok:
                    raise RuntimeError('Fay 核心服务当前未就绪，请检查 Fay 后台状态')
                req_body = {
                    'model': 'fay',
                    'user': FAY_USER,
                    'stream': True,
                    'messages': [{'role': 'user', 'content': text}],
                    'avatar_context': session.actions.context(turn['epoch']),
                }
                async with self.http.post(
                    f'{FAY_HTTP}/v1/chat/completions',
                    json=req_body,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f'Fay 问答返回 HTTP {resp.status}')
                    async for raw_line in resp.content:
                        if turn.get('cancelled') or session.turn is not turn:
                            return
                        line = raw_line.decode('utf-8', errors='replace').strip()
                        if not line.startswith('data:'):
                            continue
                        payload = line[5:].strip()
                        if payload == '[DONE]':
                            break
                        try:
                            chunk = json.loads(payload)
                        except ValueError:
                            continue
                        if isinstance(chunk, dict) and chunk.get('error'):
                            raise RuntimeError(str(chunk['error'])[:200])
                        for choice in chunk.get('choices', []):
                            delta = (choice.get('delta') or {}).get('content')
                            if delta:
                                reply_parts.append(delta)
                                job['text'] += delta
                                await session.emit('assistant_delta', response_id=response_id, text=delta)
                full_text = ''.join(reply_parts)
                if full_text.strip():
                    job['text'] = full_text
                    await session.emit('assistant_text', response_id=response_id, text=full_text)
            finally:
                chat_done.set()

        async def consume_ws_audio():
            nonlocal seen_end_signal
            # Wait for WS audio chunks during SSE streaming and for a short grace window after chat_done.
            post_done_deadline = None
            while not (turn.get('cancelled') or session.turn is not turn):
                if chat_done.is_set() and post_done_deadline is None:
                    post_done_deadline = time.monotonic() + (8.0 if audio_started else 1.8)
                if seen_end_signal and self.audio_queue.empty():
                    break
                if post_done_deadline is not None and time.monotonic() >= post_done_deadline and self.audio_queue.empty():
                    break
                try:
                    item = await asyncio.wait_for(self.audio_queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                if item.get('turn_id') != turn_id:
                    continue
                if item.get('is_end'):
                    seen_end_signal = True
                val = item.get('value') or item.get('http_value') or ''
                fname = os.path.basename(val.replace('\\', '/')) if val else ''
                if fname:
                    try:
                        async with self.http.get(f'{FAY_HTTP}/audio/{fname}', timeout=aiohttp.ClientTimeout(total=15)) as aresp:
                            if aresp.status == 200:
                                raw_audio = await aresp.read()
                                pcm = decode_audio_to_pcm16k(raw_audio, fname)
                                if pcm:
                                    if chat_done.is_set():
                                        post_done_deadline = time.monotonic() + 10.0
                                    await pump_pcm_bytes(pcm, item.get('action'), item.get('text') or '')
                    except Exception:
                        pass
                if seen_end_signal and self.audio_queue.empty():
                    break

        sse_task = asyncio.create_task(fetch_sse())
        ws_audio_task = asyncio.create_task(consume_ws_audio())
        try:
            await sse_task
            await ws_audio_task
            if not turn.get('cancelled') and session.turn is turn:
                full_text = ''.join(reply_parts).strip()
                if full_text and not audio_started:
                    fallback_pcm = await synthesize_fallback_pcm16k(full_text)
                    if fallback_pcm and not turn.get('cancelled') and session.turn is turn:
                        await pump_pcm_bytes(fallback_pcm, None, full_text)
                if job['audio_bytes']:
                    session.finish_audio(job)
                await session.emit(
                    'response_done',
                    response_id=response_id,
                    status='completed',
                    audio_seconds=job['audio_bytes'] / 32000.0,
                    input_to_pcm_ms=(job.get('first_pcm_at', job['created_at']) - (session.last_input_at or job['created_at'])) * 1000.0,
                )
                if not job['audio_bytes']:
                    turn['completed'] = True
                    turn['answer'] = full_text
                    await session.emit('playback_done', response_id=response_id)
        except asyncio.CancelledError:
            sse_task.cancel()
            ws_audio_task.cancel()
            raise
        except Exception as exc:
            sse_task.cancel()
            ws_audio_task.cancel()
            session.clear_local()
            await session.emit('error', message='Fay 认知回复失败：' + str(exc)[:220])
        finally:
            if self.active_turn_id == turn_id:
                self.active_turn_id = None
            session.idle.set()
            session.wake_activity = time.monotonic()
