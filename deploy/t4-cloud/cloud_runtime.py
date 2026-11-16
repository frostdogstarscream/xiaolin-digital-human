"""Optional cloud settings shared by the Linux presentation and speech processes."""
import base64
import hashlib
import hmac
import os
import shutil
import time
from pathlib import Path


def allowed_origins(port):
    origins = {f'http://127.0.0.1:{port}', f'http://localhost:{port}'}
    public = os.environ.get('XIAOLIN_PUBLIC_ORIGIN', '').rstrip('/')
    if public:
        origins.add(public)
    return origins


def ffmpeg_path(root):
    configured = os.environ.get('XIAOLIN_FFMPEG')
    if configured:
        return Path(configured)
    if os.name == 'nt':
        return root.parent / 'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'
    executable = shutil.which('ffmpeg')
    if not executable:
        raise RuntimeError('FFmpeg is unavailable')
    return Path(executable)


def ice_servers():
    host = os.environ.get('XIAOLIN_TURN_HOST')
    if not host:
        return []
    secret = Path(os.environ['XIAOLIN_TURN_SECRET_FILE']).read_bytes().strip()
    port = int(os.environ.get('XIAOLIN_TURN_PORT', '3478'))
    username = f'{int(time.time()) + 3600}:xiaolin'
    credential = base64.b64encode(hmac.new(secret, username.encode(), hashlib.sha1).digest()).decode()
    transports = os.environ.get('XIAOLIN_TURN_TRANSPORTS', 'udp,tcp').split(',')
    if not transports or any(t not in ('udp','tcp') for t in transports):
        raise RuntimeError('Invalid TURN transport configuration')
    return [{'urls': [f'stun:{host}:{port}']},
            {'urls': [f'turn:{host}:{port}?transport={transport}' for transport in transports],
             'username': username, 'credential': credential}]


def configure_rtc():
    if not os.environ.get('XIAOLIN_TURN_HOST'):
        return
    from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer
    from aiortc import rtcicetransport
    from aioice import ice
    import asyncio
    import socket
    from server import rtc_manager
    if getattr(rtc_manager.RTCPeerConnection, '_xiaolin_cloud', False):
        return

    class BoundedIceConnection(ice.Connection):
        async def get_component_candidates(self, component, addresses, timeout=5):
            loop = asyncio.get_running_loop()
            candidates = []
            protocols = []
            bind_ip = os.environ.get('XIAOLIN_BIND_IP')
            if bind_ip:
                addresses = [address for address in addresses if address == bind_ip]
            for address in addresses:
                protocol = None
                minimum = int(os.environ.get('XIAOLIN_ICE_MIN_PORT', '49210'))
                maximum = int(os.environ.get('XIAOLIN_ICE_MAX_PORT', '49259'))
                for port in range(minimum, maximum + 1):
                    try:
                        transport, protocol = await loop.create_datagram_endpoint(
                            lambda: ice.StunProtocol(self), local_addr=(address, port))
                        break
                    except OSError:
                        continue
                if protocol is None:
                    raise RuntimeError('The cloud ICE UDP port pool is exhausted')
                transport.get_extra_info('socket').setsockopt(
                    socket.SOL_SOCKET, socket.SO_RCVBUF, ice.turn.UDP_SOCKET_BUFFER_SIZE)
                protocol.local_candidate = ice.Candidate(
                    foundation=ice.candidate_foundation('host', 'udp', address),
                    component=component, transport='udp', priority=ice.candidate_priority(component, 'host'),
                    host=address, port=transport.get_extra_info('sockname')[1], type='host')
                protocols.append(protocol)
                candidates.append(protocol.local_candidate)
            self._protocols += protocols
            tasks = [asyncio.create_task(ice.server_reflexive_candidate(protocol, self.stun_server))
                     for protocol in protocols if self.stun_server and ':' not in protocol.local_candidate.host]
            # Reuse native TURN gathering, transport lifetime and candidate handling.
            candidates += await super().get_component_candidates(component, [], timeout)
            if tasks:
                done, pending = await asyncio.wait(tasks, timeout=timeout)
                for task in done:
                    if not task.cancelled() and task.exception() is None:
                        candidates.append(task.result()[0])
                for task in pending:
                    task.cancel()
            return candidates

    rtcicetransport.Connection = BoundedIceConnection

    class CloudPeerConnection(RTCPeerConnection):
        _xiaolin_cloud = True

        def __init__(self, configuration=None):
            servers = [RTCIceServer(**item) for item in ice_servers()]
            super().__init__(RTCConfiguration(iceServers=servers))

    # Only the pinned RTC manager uses this factory; vendor files stay intact.
    rtc_manager.RTCPeerConnection = CloudPeerConnection
