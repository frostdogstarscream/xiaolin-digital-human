from pathlib import Path
import subprocess
p=Path('/opt/xiaolin/musetalk/20261111-original/service/server.py')
s=p.read_text().replace('    from cloud_runtime import configure_rtc',"    import os\n    os.environ['XIAOLIN_TURN_SECRET_FILE']='/config/turn-secret'\n    from cloud_runtime import configure_rtc")
p.write_text(s)
subprocess.run(['docker','restart','xiaolin-musetalk-original'],check=True)
