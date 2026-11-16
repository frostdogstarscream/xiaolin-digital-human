"""Install a local speech adapter without changing vendor sources or Fay dependencies."""
import configparser
import hashlib
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FAY=ROOT.parent/'fay-ue4/runtime/fay-local/app'


def main():
    backup=ROOT/'runtime/fay-2d-integration-backup-v1'
    backup.mkdir(parents=True,exist_ok=False)
    for name in ['core/fay_core.py','system.conf','config.json']:
        target=backup/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(FAY/name,target)
    core=FAY/'core/fay_core.py'
    text=core.read_text(encoding='utf-8')
    before="else:\n\n\n    from tts.ms_tts_sdk import Speech"
    if text.count(before)!=1:
        raise RuntimeError('Unexpected Fay TTS selector; no patch applied')
    text=text.replace(before,"elif cfg.tts_module == 'windows_sapi':\n    from tts.windows_sapi import Speech\n\n"+before)
    core.write_text(text,encoding='utf-8')
    (FAY/'tts/windows_sapi.py').write_text(
        '"""Local 2D integration speech adapter."""\nimport sys\nfrom pathlib import Path\n'
        "sys.path.insert(0,str(Path(__file__).resolve().parents[5]/'avatar-2d/service'))\n"
        'from local_sapi import Speech\n',encoding='utf-8')
    config=configparser.ConfigParser(interpolation=None)
    config.read(FAY/'system.conf',encoding='utf-8-sig')
    config['key']['tts_module']='windows_sapi'
    config['key']['gpt_base_url']='https://dashscope.aliyuncs.com/compatible-mode/v1'
    config['key']['gpt_model_engine']='qwen-plus'
    with (FAY/'system.conf').open('w',encoding='utf-8') as out:
        config.write(out)
    data=json.loads((FAY/'config.json').read_text(encoding='utf-8-sig'))
    data['source']['record']['enabled']=False
    (FAY/'config.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    (backup/'patch-manifest.json').write_text(json.dumps(dict(
        patch='Added explicit windows_sapi TTS provider; selected local offline voice; disabled automatic microphone capture for text-first integration; selected Qwen Plus endpoint without adding a key',
        core_before_sha256=hashlib.sha256((backup/'core/fay_core.py').read_bytes()).hexdigest(),
        core_after_sha256=hashlib.sha256(core.read_bytes()).hexdigest(),
        credentials_written=False),indent=2),encoding='utf-8')
    print('Prepared Fay local speech and Qwen endpoint; API key remains unconfigured.')


if __name__=='__main__':main()
