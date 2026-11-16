"""Attach MaterialsV1 to a NEW mesh revision and select it only after saving."""
import json
from pathlib import Path
import unreal


def bind_materials():
    root = Path(__file__).resolve().parents[1]
    folder = '/Game/CharacterPreviews/girl008_preview_v1'
    source = folder + '/SK_girl008_preview_v1'
    target = folder + '/SK_girl008_textured_v1'
    if unreal.EditorAssetLibrary.does_asset_exist(target):
        raise ValueError('Textured mesh revision already exists; do not overwrite it')
    mesh = unreal.EditorAssetLibrary.duplicate_asset(source, target)
    if not mesh: raise ValueError('Could not duplicate source preview mesh')
    slots = list(mesh.get_editor_property('materials'))
    mapping = []
    for slot in slots:
        old = slot.get_editor_property('material_interface')
        mat = unreal.load_asset(folder + '/MaterialsV1/M_' + old.get_name()) if old else None
        if not mat: raise ValueError('Unmapped material slot')
        slot.set_editor_property('material_interface', mat)
        mapping.append(dict(slot=str(slot.get_editor_property('material_slot_name')), material=mat.get_path_name()))
    mesh.set_editor_property('materials', slots)
    if not unreal.EditorAssetLibrary.save_loaded_asset(mesh): raise ValueError('Could not save textured mesh')
    manifest = root / 'ue4/Saved/girl008_preview_v1-preview.json'
    spec = json.loads(manifest.read_text(encoding='utf-8'))
    spec['skeletal_mesh'] = mesh.get_path_name()
    spec['mesh_yaw'] = -90
    manifest.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf-8')
    (root / 'docs/girl008-material-slots.json').write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding='utf-8')
    unreal.log('Saved new textured mesh revision and selected it for isolated preview: ' + mesh.get_path_name())


if __name__ == '__main__': bind_materials()
