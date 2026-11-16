"""UE4.27 Editor Python: import_character(manifest_path).

Creates a NEW /Game/Characters/<id> folder; never overwrites an existing asset.
The installed catalog is updated only after mesh/animation/morph validation.
"""
import json
import os
import re
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from character_contract import validate_face, validate_motion


def validate_manifest(path, preview=False):
    with open(path, encoding='utf-8-sig') as stream: spec = json.load(stream)
    if not re.fullmatch(r'[a-z0-9_-]{1,60}', spec.get('id', '')): raise ValueError('Invalid character id')
    if not spec.get('name') or not spec.get('license_note'): raise ValueError('Name and license_note are required')
    validate_face(spec)
    validate_motion(spec, 'animation_fbx', preview)
    animations = spec.get('animation_fbx', {})
    if any(k not in ('idle', 'speaking', 'listening', 'thinking', 'welcome', 'point') for k in animations): raise ValueError('Unknown animation state')
    if not isinstance(spec.get('mesh_scale', 1), (int, float)) or not 0 < spec.get('mesh_scale', 1) <= 100: raise ValueError('Invalid mesh_scale')
    if not isinstance(spec.get('mesh_yaw', 0), (int, float)) or not -180 <= spec.get('mesh_yaw', 0) <= 180: raise ValueError('Invalid mesh_yaw')
    base = os.path.dirname(os.path.abspath(path))
    def resolve(value):
        result = os.path.abspath(os.path.join(base, value))
        if not result.lower().endswith('.fbx') or not os.path.isfile(result): raise ValueError('FBX file missing: ' + result)
        return result
    spec['source_fbx'] = resolve(spec['source_fbx'])
    spec['animation_fbx'] = {k: resolve(v) for k, v in animations.items()}
    return spec


def import_character(manifest_path, preview=False):
    import unreal
    spec = validate_manifest(manifest_path, preview)
    folder = ('/Game/CharacterPreviews/' if preview else '/Game/Characters/') + spec['id']
    if unreal.EditorAssetLibrary.does_directory_exist(folder):
        raise ValueError('Destination already exists. Use a new id, or inspect and remove a failed import explicitly: ' + folder)
    tasks = unreal.AssetToolsHelpers.get_asset_tools()
    options = unreal.FbxImportUI()
    options.set_editor_property('import_as_skeletal', True)
    options.set_editor_property('import_mesh', True)
    options.set_editor_property('import_animations', False)
    options.set_editor_property('import_materials', True)
    options.set_editor_property('import_textures', True)
    options.set_editor_property('automated_import_should_detect_type', False)
    options.set_editor_property('mesh_type_to_import', unreal.FBXImportType.FBXIT_SKELETAL_MESH)
    options.skeletal_mesh_import_data.set_editor_property('import_morph_targets', True)
    def run_task(filename, name, opts, expected_class):
        task = unreal.AssetImportTask()
        for key, value in {'filename': filename, 'destination_path': folder, 'destination_name': name,
                           'automated': True, 'save': True, 'replace_existing': False, 'options': opts}.items():
            task.set_editor_property(key, value)
        tasks.import_asset_tasks([task])
        assets = [unreal.load_asset(p) for p in task.get_editor_property('imported_object_paths')]
        matched = [a for a in assets if isinstance(a, expected_class)]
        if len(matched) != 1: raise ValueError('Expected exactly one imported ' + expected_class.__name__)
        return matched[0]
    mesh = run_task(spec['source_fbx'], 'SK_' + spec['id'], options, unreal.SkeletalMesh)
    if spec.get('face_driver', 'morph') == 'bones':
        probe = unreal.SkeletalMeshComponent()
        probe.set_skeletal_mesh(mesh)
        missing = {b['bone'] for bindings in spec['face_bones'].values() for b in bindings if probe.get_bone_index(b['bone']) < 0}
    else:
        morph_names = {str(m.get_name()) for m in mesh.get_editor_property('morph_targets')}
        missing = set(spec['morphs'].values()) - morph_names
    if missing: raise ValueError('Imported face mappings missing: ' + ', '.join(sorted(missing)))
    animation_paths = {}
    for state, source in spec['animation_fbx'].items():
        anim_options = unreal.FbxImportUI()
        for key, value in {'import_as_skeletal': True, 'import_mesh': False, 'import_animations': True,
                           'automated_import_should_detect_type': False,
                           'mesh_type_to_import': unreal.FBXImportType.FBXIT_ANIMATION,
                           'skeleton': mesh.get_editor_property('skeleton')}.items():
            anim_options.set_editor_property(key, value)
        animation = run_task(source, 'A_' + state, anim_options, unreal.AnimSequence)
        animation_paths[state] = animation.get_path_name()
    entry = {key: spec[key] for key in ('id', 'name', 'license_note')}
    entry.update(morphs=spec.get('morphs', {}), face_driver=spec.get('face_driver', 'morph'),
                 face_bones=spec.get('face_bones', {}), motion_mode=spec.get('motion_mode', 'animations'))
    entry.update(kind='maya_fbx', engine='4.27.2', actor_class='/Script/HoloKiosk.KioskCharacter',
                 skeletal_mesh=mesh.get_path_name(), animations=animation_paths,
                 mesh_yaw=spec.get('mesh_yaw', 0), mesh_scale=spec.get('mesh_scale', 1))
    unreal.EditorAssetLibrary.save_directory(folder)
    if preview:
        # Never expose an uncalibrated/reference-pose character in the live catalog.
        path = os.path.join(unreal.Paths.project_saved_dir(), spec['id'] + '-preview.json')
        with open(path, 'w', encoding='utf-8') as stream: json.dump(entry, stream, ensure_ascii=False, indent=2)
        unreal.log('Preview only, NOT registered: ' + path)
        return entry
    path = os.path.join(unreal.Paths.project_content_dir(), 'Data', 'avatars.json')
    with open(path, encoding='utf-8') as stream: catalog = json.load(stream)
    if any(a['id'] == entry['id'] for a in catalog): raise ValueError('Character id already registered')
    catalog.append(entry)
    with open(path + '.tmp', 'w', encoding='utf-8') as stream: json.dump(catalog, stream, ensure_ascii=False, indent=2)
    os.replace(path + '.tmp', path)
    unreal.EditorAssetLibrary.save_directory(folder)
    unreal.log('Character registered. Inspect materials/LODs in Editor, then rebuild the packaged client: ' + entry['id'])
    return entry
