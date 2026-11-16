import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'service'))
from engine import load_assets
assets=load_assets('musetalk')
print('READY',assets.device,'load/prep seconds',assets.ready_seconds,flush=True)
