import importlib.util
import json
from pathlib import Path

import pytest

from character_contract import validate_face
from kiosk.avatars import catalog
from kiosk.config import ROOT


def importer():
    spec = importlib.util.spec_from_file_location('character_import', ROOT / 'tools/ue_import_character.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest(tmp_path):
    (tmp_path / 'mesh.fbx').write_bytes(b'path preflight placeholder')
    return dict(id='bone_preview', name='Bone preview', license_note='test only', source_fbx='mesh.fbx',
                face_driver='bones', motion_mode='reference_pose', animation_fbx={},
                face_bones={k: [dict(bone=n, rotation=[0, 0, 0], translation=[0, 0, 0])]
                            for k, n in [('jaw_open', 'jaw'), ('blink_left', 'lid_L'), ('blink_right', 'lid_R')]})


def test_reference_pose_requires_explicit_preview_and_never_enters_catalog(tmp_path):
    data = manifest(tmp_path)
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='preview'):
        importer().validate_manifest(str(path))
    checked = importer().validate_manifest(str(path), preview=True)
    assert Path(checked['source_fbx']).is_absolute()
    entry = {k: v for k, v in data.items() if k not in ('source_fbx', 'animation_fbx')}
    entry.update(kind='maya_fbx', actor_class='/Script/HoloKiosk.KioskCharacter', skeletal_mesh='/Game/Characters/mesh.mesh')
    directory = tmp_path / 'ue4/Content/Data'
    directory.mkdir(parents=True)
    (directory / 'avatars.json').write_text(json.dumps([entry]), encoding='utf-8')
    with pytest.raises(ValueError):
        catalog(tmp_path)


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), 46, True, '1'])
def test_invalid_rotations_rejected(tmp_path, bad):
    data = manifest(tmp_path)
    data['face_bones']['jaw_open'][0]['rotation'][0] = bad
    with pytest.raises(ValueError, match='rotation'):
        validate_face(data)


def test_bone_channels_cannot_overlap_or_omit_eyes(tmp_path):
    data = manifest(tmp_path)
    data['face_bones']['blink_left'][0]['bone'] = 'jaw'
    with pytest.raises(ValueError, match='duplicate'):
        validate_face(data)
    data['face_bones'].pop('blink_right')
    with pytest.raises(ValueError, match='blink_right'):
        validate_face(data)


def test_production_bone_character_requires_real_animation_mapping(tmp_path):
    data = manifest(tmp_path)
    data['motion_mode'] = 'animations'
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='Idle'):
        importer().validate_manifest(str(path), preview=True)
    for state in ('idle', 'speaking'):
        (tmp_path / (state + '.fbx')).write_bytes(b'path preflight only')
        data['animation_fbx'][state] = state + '.fbx'
    path.write_text(json.dumps(data), encoding='utf-8')
    assert importer().validate_manifest(str(path))['face_driver'] == 'bones'
