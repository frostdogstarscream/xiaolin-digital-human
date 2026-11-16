"""Existing approved webpage credentials -> pinned SSH -> same-user protected named pipe."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'runtime/server-4t4/tool-libs'))
import paramiko
account=json.loads((ROOT/'runtime/server-4t4/private/web-access.json').read_text())
client=paramiko.SSHClient();client.load_host_keys(str(ROOT/'runtime/deploy-1660/candidate-192.168.10.40.txt'))
key=client.get_host_keys()['192.168.10.40']['ssh-ed25519'];client.get_host_keys().add('192.168.10.25',key.get_name(),key);client.set_missing_host_key_policy(paramiko.RejectPolicy())
client.connect('192.168.10.25',username='Admin',key_filename=str(ROOT/'runtime/deploy-1660/id_ed25519'),look_for_keys=False,allow_agent=False,timeout=15)
try:
    command='D:/XiaolinDigitalHuman/avatar-2d/.venv/Scripts/python.exe -X utf8 -c "import sys; f=open(r\'\\\\.\\pipe\\XiaolinCloudClient-Credential-Install\',\'wb\'); f.write(sys.stdin.buffer.readline()); f.flush(); f.close(); print(\'Credential delivered to protected current-user saver\')"'
    incoming,outgoing,errors=client.exec_command(command,timeout=20)
    incoming.write(json.dumps(account)+'\n');incoming.flush();incoming.channel.shutdown_write()
    output=outgoing.read().decode('utf-8',errors='replace');error=errors.read().decode('utf-8',errors='replace');code=outgoing.channel.recv_exit_status()
    print(output.replace(account['password'],'[redacted]'),end='')
    if error:print(error.replace(account['password'],'[redacted]'))
finally:account.clear();client.close()
raise SystemExit(code)
