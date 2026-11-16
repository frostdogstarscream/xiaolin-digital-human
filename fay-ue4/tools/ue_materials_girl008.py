"""Build preview UE materials from inspected FBX links, retaining imported materials."""
import json
import os
import re
import sys
from pathlib import Path
import unreal

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'assets/incoming/girl008'
REPORT = json.loads((SOURCE / 'fbx-material-inspection.json').read_text(encoding='utf-8'))
FOLDER = '/Game/CharacterPreviews/girl008_preview_v1/MaterialsV1'
MESH = '/Game/CharacterPreviews/girl008_preview_v1/SK_girl008_preview_v1'
tools = unreal.AssetToolsHelpers.get_asset_tools()
edit = unreal.MaterialEditingLibrary


def constant(material, value, prop):
    node = edit.create_material_expression(material, unreal.MaterialExpressionConstant)
    node.set_editor_property('r', float(value))
    edit.connect_material_property(node, '', prop)


def color(material, values):
    node = edit.create_material_expression(material, unreal.MaterialExpressionConstant3Vector)
    node.set_editor_property('constant', unreal.LinearColor(*[float(v) for v in values[:3]], 1.0))
    edit.connect_material_property(node, '', unreal.MaterialProperty.MP_BASE_COLOR)


textures = {}
def texture(filename, linear):
    basename = filename.replace('\\', '/').split('/')[-1]
    candidates = list((SOURCE / 'maya/CG2020_mx008/sourceimages').rglob(basename))
    if len(candidates) != 1:
        raise ValueError('Texture must have exactly one local match: ' + basename)
    key = (str(candidates[0]), linear)
    if key in textures: return textures[key]
    name = 'T_' + re.sub(r'[^A-Za-z0-9_]', '_', candidates[0].stem) + ('_Linear' if linear else '_Color')
    task = unreal.AssetImportTask()
    for k, v in dict(filename=str(candidates[0]), destination_path=FOLDER + '/Textures', destination_name=name,
                     automated=True, save=True, replace_existing=False).items(): task.set_editor_property(k, v)
    tools.import_asset_tasks([task])
    paths = task.get_editor_property('imported_object_paths')
    if len(paths) != 1: raise ValueError('Texture import failed: ' + basename)
    asset = unreal.load_asset(paths[0])
    asset.set_editor_property('srgb', not linear)
    asset.set_editor_property('max_texture_size', 2048)
    textures[key] = asset
    return asset


def sample(material, filename, prop, linear=False):
    node = edit.create_material_expression(material, unreal.MaterialExpressionTextureSample)
    node.set_editor_property('texture', texture(filename, linear))
    node.set_editor_property('sampler_type', unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR if linear else unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
    edit.connect_material_property(node, 'R' if linear else 'RGB', prop)


if unreal.EditorAssetLibrary.does_directory_exist(FOLDER):
    raise ValueError('Material revision already exists; inspect it or use a new revision')
materials = {}
summary = []
for info in REPORT['material_details']:
    name = info['name'].split(':')[-1]
    mat = tools.create_asset('M_' + name, FOLDER, unreal.Material, unreal.MaterialFactoryNew())
    if not mat: raise ValueError('Material creation failed: ' + name)
    links = {t['channel']: t['files'][0] for t in info['textures'] if t['files']}
    props = info.get('properties', {})
    models = info['models']
    is_glass = name in ('pasted__Eyes_glass', 'Tear')
    is_hair = any('hair' in model.lower() for model in models)
    if is_glass:
        # A lightweight preview approximation of Arnold cornea/tear surfaces.
        mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_TRANSLUCENT)
        constant(mat, 0.025, unreal.MaterialProperty.MP_OPACITY)
        constant(mat, 0.08, unreal.MaterialProperty.MP_ROUGHNESS)
        color(mat, [1, 1, 1])
    else:
        if 'Maya|baseColor' in links:
            sample(mat, links['Maya|baseColor'], unreal.MaterialProperty.MP_BASE_COLOR)
        else:
            color(mat, props.get('Maya|baseColor', [0.025, 0.018, 0.012] if is_hair else [0.2, 0.2, 0.2]))
        if 'Maya|specularRoughness' in links:
            sample(mat, links['Maya|specularRoughness'], unreal.MaterialProperty.MP_ROUGHNESS, True)
        else:
            constant(mat, props.get('Maya|specularRoughness', [0.65])[0], unreal.MaterialProperty.MP_ROUGHNESS)
        if 'Maya|metalness' in links:
            sample(mat, links['Maya|metalness'], unreal.MaterialProperty.MP_METALLIC, True)
        else:
            constant(mat, props.get('Maya|metalness', [0])[0], unreal.MaterialProperty.MP_METALLIC)
        if 'Maya|opacity' in links:
            mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_MASKED)
            mat.set_editor_property('two_sided', True)
            mat.set_editor_property('opacity_mask_clip_value', 0.333)
            sample(mat, links['Maya|opacity'], unreal.MaterialProperty.MP_OPACITY_MASK, True)
    edit.set_material_usage(mat, unreal.MaterialUsage.MATUSAGE_SKELETAL_MESH)
    edit.recompile_material(mat)
    materials[name] = mat
    summary.append(dict(source_material=info['name'], models=models, ue_material=mat.get_path_name(),
                        linked_channels=[k for k in links if k in ('Maya|baseColor', 'Maya|specularRoughness', 'Maya|metalness', 'Maya|opacity')],
                        normal_camera_skipped='Maya|normalCamera' in links, glass_approximation=is_glass))

if not unreal.EditorAssetLibrary.save_directory(FOLDER): raise ValueError('Could not save preview materials')
sys.path.insert(0, str(ROOT / 'tools'))
from ue_bind_materials_girl008 import bind_materials
bind_materials()
(ROOT / 'docs/girl008-ue-materials-v1.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
unreal.log('Preview material reconstruction complete; original imported materials retained. Inspect rendering before acceptance.')
