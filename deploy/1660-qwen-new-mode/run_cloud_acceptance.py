"""Forward existing web-account credentials over pinned SSH stdin only; no target credential file."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'runtime/server-4t4/tool-libs'))
import paramiko
account=json.loads((ROOT/'runtime/server-4t4/private/web-access.json').read_text())
client=paramiko.SSHClient();client.load_host_keys(str(ROOT/'runtime/deploy-1660/candidate-192.168.10.40.txt'))
expected=client.get_host_keys()['192.168.10.40']['ssh-ed25519'];client.get_host_keys().add('192.168.10.25',expected.get_name(),expected)
client.set_missing_host_key_policy(paramiko.RejectPolicy())
client.connect('192.168.10.25',username='Admin',key_filename=str(ROOT/'runtime/deploy-1660/id_ed25519'),look_for_keys=False,allow_agent=False,timeout=15)
try:
    command='D:/XiaolinDigitalHuman/avatar-2d/.venv/Scripts/python.exe -X utf8 -u C:/Users/Admin/AppData/Local/XiaolinCloudClient/Acceptance/check_cloud_browser.py'
    incoming,outgoing,errors=client.exec_command(command,timeout=300)
    incoming.write(json.dumps(account)+'\n');incoming.flush();incoming.channel.shutdown_write()
    while True:
        line=outgoing.readline()
        if not line:break
        print(line.rstrip().replace(account['password'],'[redacted]'),flush=True)
    error=errors.read().decode('utf-8',errors='replace').replace(account['password'],'[redacted]')
    if error:print(error,flush=True)
    code=outgoing.channel.recv_exit_status()
finally:account.clear();client.close()
raise SystemExit(code)
