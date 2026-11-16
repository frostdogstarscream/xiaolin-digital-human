"""Prepare a local Fay installation from the retained upstream source.

Creates one runtime copy; refuses to overwrite an existing configured deployment.
The upstream archive, previous experiments and application databases are retained.
"""
import hashlib
import json
import shutil
from configparser import ConfigParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'vendor/Fay-source'
TARGET=ROOT/'runtime/fay-local/app'


def prepare():
    if TARGET.exists():raise FileExistsError('Existing deployment retained: '+str(TARGET))
    ignore=shutil.ignore_patterns('.git','__pycache__','.pytest_cache','.venv','logs','samples','memory','cache_data',
                                 'system.conf','config.json','verifier.json','*.sqlite3','*.db','*.log')
    shutil.copytree(SOURCE,TARGET,ignore=ignore)
    for name in ['logs','samples','memory','cache_data']:(TARGET/name).mkdir(exist_ok=True)
    patches=[]
    changes={
        'main.py':[
            ('    __clear_samples()','    os.makedirs("samples", exist_ok=True) # local: retain audio artifacts'),
            ('    __clear_logs()','    os.makedirs("logs", exist_ok=True) # local: retain logs'),
            ('ports =[10001, 10002, 10003, 5000, 9001]','ports = [] # local launcher owns only its recorded process')],
        'core/wsa_server.py':[("host='0.0.0.0'","host='127.0.0.1'")],
        'gui/flask_server.py':[("make_server('0.0.0.0',","make_server('127.0.0.1',")],
        'faymcp/mcp_service.py':[("make_server('0.0.0.0',","make_server('127.0.0.1',")],
        'fay_booter.py':[("((\"0.0.0.0\",10001))","((\"127.0.0.1\",10001))"),
                          ('mcp_sse_enabled = True','mcp_sse_enabled = False')],
        'core/socket_bridge_service.py':[("'0.0.0.0'","'127.0.0.1'"),( '"0.0.0.0"','"127.0.0.1"')],
    }
    for file,replacements in changes.items():
        path=TARGET/file;original=path.read_text(encoding='utf-8-sig');text=original;counts=[]
        for before,after in replacements:
            counts.append(text.count(before));text=text.replace(before,after)
        if text!=original:
            path.write_text(text,encoding='utf-8')
            patches.append(dict(file=file,replacements=counts,source_sha256=hashlib.sha256((SOURCE/file).read_bytes()).hexdigest(),installed_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    # Build a fresh configuration from option names, without copying public/shared credentials.
    template=ConfigParser(interpolation=None);template.read(SOURCE/'system.conf.bak',encoding='utf-8-sig')
    config=ConfigParser(interpolation=None);config.add_section('key')
    for name in template['key']:config['key'][name]=''
    config['key'].update(asr_mode='local',local_asr_ip='127.0.0.1',local_asr_port='10100',tts_module='ms',
                         gpt_base_url='http://127.0.0.1:9/v1',gpt_model_engine='qwen-plus',
                         embedding_base_url='http://127.0.0.1:9/v1',embedding_api_model='text-embedding-v4',
                         start_mode='web',fay_url='http://127.0.0.1:5000')
    with (TARGET/'system.conf').open('w',encoding='utf-8') as stream:config.write(stream)
    data=json.loads((SOURCE/'config.json').read_text(encoding='utf-8-sig'))
    data['source']['record']['enabled']=False
    data['source']['liveRoom'].update(enabled=False,url='')
    data['source']['automatic_player_status']=False;data['source']['automatic_player_url']=''
    data['interact'].update(playSound=False,visualization=False)
    data['memory']['use_bionic_memory']=False
    (TARGET/'config.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    (TARGET/'verifier.json').write_text('{}\n',encoding='utf-8')
    mcp=TARGET/'faymcp/data';mcp.mkdir(exist_ok=True)
    (mcp/'mcp_servers.json').write_text('[]\n',encoding='utf-8')
    report=dict(source=str(SOURCE),deployment=str(TARGET),upstream_requirements_sha256=hashlib.sha256((SOURCE/'requirements.txt').read_bytes()).hexdigest(),
                patches=patches,cloud_credentials_configured=False,config_center_enabled=False,bind_host='127.0.0.1',autostart_core=False)
    (TARGET.parent/'deployment.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Prepared local Fay deployment:',TARGET)
    print('Local patch files:',len(patches))


if __name__=='__main__':prepare()
