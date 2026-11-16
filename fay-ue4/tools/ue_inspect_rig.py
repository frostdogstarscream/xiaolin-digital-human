"""Read mesh reference transforms directly, without creating an editor Actor."""
import json
from pathlib import Path
import unreal
root=Path(__file__).resolve().parents[1]
mesh=unreal.load_asset('/Game/CharacterPreviews/girl008_preview_v1/SK_girl008_textured_v1')
text=unreal.KioskRigTools.reference_rig_json(mesh)
report=json.loads(text)
if len(report['bones']) < 100 or max(b['position'][2] for b in report['bones']) < 100:
    raise ValueError('Invalid reference skeleton data')
(root/'docs/girl008-ue-reference-rig.json').write_text(text,encoding='utf-8')
unreal.log('Reference rig exported: {} bones'.format(len(report['bones'])))
