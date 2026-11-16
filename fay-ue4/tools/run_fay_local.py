"""Launch the installed local Fay web manager without inheriting cloud credentials."""
import os
import runpy
import socket
import sys
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, 'reconfigure'): stream.reconfigure(encoding='utf-8')

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'runtime/fay-local/app'
for name in ['FAY_CONFIG_CENTER_ID','FAY_SYSTEM_CONF_JSON','LANGCHAIN_API_KEY','LANGSMITH_API_KEY',
             'OPENAI_API_KEY','EMBEDDING_API_KEY','DASHSCOPE_API_KEY']:
    os.environ.pop(name,None)
os.environ.update(LANGCHAIN_TRACING_V2='false',LANGSMITH_TRACING='false',ANONYMIZED_TELEMETRY='false',
                  HF_HUB_DISABLE_TELEMETRY='1',PYGAME_HIDE_SUPPORT_PROMPT='1',PYTHONIOENCODING='utf-8')
for file in ['main.py','system.conf','config.json']:
    if not (APP/file).is_file():raise FileNotFoundError('Fay installation is incomplete: '+file)
for port in [5000,5010,10002,10003]:
    with socket.socket() as sock:
        if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        try:sock.bind(('127.0.0.1',port))
        except OSError as exc:raise RuntimeError('Required Fay port unavailable: '+str(port)) from exc
os.chdir(APP)
sys.path.insert(0,str(APP))
sys.argv=[str(APP/'main.py')]
runpy.run_path(str(APP/'main.py'),run_name='__main__')
