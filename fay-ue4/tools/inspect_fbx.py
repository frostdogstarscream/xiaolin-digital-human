"""Read binary FBX structure without executing scene scripts or changing assets.

This is a structural preflight, not an Autodesk/Unreal import validation.
Usage: python tools/inspect_fbx.py model.fbx --output report.json
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import zlib


def inspect(path):
    data = Path(path).read_bytes()
    if not data.startswith(b'Kaydara FBX Binary  \x00\x1a\x00'):
        raise ValueError('Only binary FBX is supported')
    version = struct.unpack_from('<I', data, 23)[0]
    wide = version >= 7500
    header_size = 25 if wide else 13
    header_format = '<QQQB' if wide else '<IIIB'

    def prop(pos):
        code = chr(data[pos]); pos += 1
        scalar = {'Y': 'h', 'C': '?', 'I': 'i', 'F': 'f', 'D': 'd', 'L': 'q'}
        if code in scalar:
            fmt = '<' + scalar[code]
            return struct.unpack_from(fmt, data, pos)[0], pos + struct.calcsize(fmt)
        if code in ('S', 'R'):
            size = struct.unpack_from('<I', data, pos)[0]; pos += 4
            raw = data[pos:pos + size]
            return (raw.decode('utf-8', 'replace') if code == 'S' else {'bytes': size}), pos + size
        if code in 'fdlibc':
            count, encoding, size = struct.unpack_from('<III', data, pos); pos += 12
            raw = data[pos:pos + size]
            if encoding == 1: raw = zlib.decompress(raw)
            elif encoding != 0: raise ValueError('Unknown array encoding')
            fmt = {'f': 'f', 'd': 'd', 'l': 'q', 'i': 'i', 'b': 'b', 'c': 'b'}[code]
            assert len(raw) == count * struct.calcsize('<' + fmt)
            return {'count': count, 'values': raw, 'format': fmt}, pos + size
        raise ValueError('Unknown FBX property type: ' + code)

    def node(pos):
        end, count, size, name_size = struct.unpack_from(header_format, data, pos)
        if not end: return None, pos + header_size
        if not pos < end <= len(data): raise ValueError('Invalid FBX node offset')
        pos += header_size
        name = data[pos:pos + name_size].decode('utf-8'); pos += name_size
        start = pos; props = []
        for _ in range(count):
            value, pos = prop(pos); props.append(value)
        if pos - start != size: raise ValueError('FBX property size mismatch')
        children = []
        while pos < end:
            child, pos = node(pos)
            if child is None: break
            children.append(child)
        if pos != end: raise ValueError('FBX child boundary mismatch')
        return {'name': name, 'props': props, 'children': children}, end

    roots = []; pos = 27
    while pos + header_size <= len(data):
        item, pos = node(pos)
        if item is None: break
        roots.append(item)
    def walk(nodes):
        for n in nodes:
            yield n
            yield from walk(n['children'])
    all_nodes = list(walk(roots))
    objects = next((n['children'] for n in roots if n['name'] == 'Objects'), [])
    by_id = {n['props'][0]: n for n in objects if n['props']}
    connections = next((n['children'] for n in roots if n['name'] == 'Connections'), [])
    geometry_names = {}
    for c in connections:
        if len(c['props']) >= 3:
            target = by_id.get(c['props'][2])
            if target and target['name'] == 'Model':
                geometry_names[c['props'][1]] = target['props'][1].split('\x00')[0]
    counts = Counter(n['name'] + ':' + str(n['props'][2] if len(n['props']) > 2 else '') for n in objects)
    meshes = []
    for n in objects:
        if n['name'] != 'Geometry' or n['props'][2] != 'Mesh': continue
        fields = {x['name']: x['props'] for x in n['children']}
        verts = fields.get('Vertices', [{'count': 0}])[0]['count'] // 3
        arr = fields.get('PolygonVertexIndex', [])
        polygons = triangles = size = 0
        if arr:
            for (index,) in struct.iter_unpack('<i', arr[0]['values']):
                size += 1
                if index < 0:
                    polygons += 1; triangles += max(0, size - 2); size = 0
        meshes.append({'name': n['props'][1].split('\x00')[0] or geometry_names.get(n['props'][0], ''), 'vertices': verts,
                       'polygons': polygons, 'triangles_by_polygon_fan': triangles})
    def names(kind, subtype=None):
        return [n['props'][1].split('\x00')[0] for n in objects if n['name'] == kind and
                (subtype is None or len(n['props']) > 2 and n['props'][2] == subtype)]
    # A bone also connects to deformers; only Model -> Model edges are hierarchy.
    parents = {c['props'][1]: c['props'][2] for c in connections if len(c['props']) >= 3 and c['props'][0] == 'OO'
               and by_id.get(c['props'][1], {}).get('name') == 'Model'
               and by_id.get(c['props'][2], {}).get('name') == 'Model'}
    joint_details = []
    for n in objects:
        if n['name'] != 'Model' or len(n['props']) < 3 or n['props'][2] != 'LimbNode': continue
        parent = by_id.get(parents.get(n['props'][0]))
        properties = {p['props'][0]: p['props'][4:] for p in walk(n['children']) if p['name'] == 'P' and len(p['props']) >= 5}
        joint_details.append({'name': n['props'][1].split('\x00')[0],
                              'parent': parent['props'][1].split('\x00')[0] if parent else None,
                              'fbx_properties': properties})
    material_details = []
    for n in objects:
        if n['name'] != 'Material': continue
        textures_for_material = []
        for c in connections:
            if len(c['props']) < 3 or c['props'][2] != n['props'][0]: continue
            source = by_id.get(c['props'][1], {})
            if source.get('name') != 'Texture': continue
            textures_for_material.append({'channel': c['props'][3] if len(c['props']) > 3 else '',
                                          'files': [x['props'][0] for x in source['children'] if x['name'] in ('FileName', 'RelativeFilename') and x['props']]})
        material_details.append({'name': n['props'][1].split('\x00')[0],
                                 'properties': {p['props'][0]: p['props'][4:] for p in walk(n['children']) if p['name'] == 'P' and len(p['props']) >= 5 and p['props'][0] in ('Maya|baseColor', 'Maya|specularRoughness', 'Maya|metalness', 'Maya|opacity')},
                                 'models': [by_id[c['props'][2]]['props'][1].split('\x00')[0] for c in connections if len(c['props']) >= 3 and c['props'][1] == n['props'][0] and by_id.get(c['props'][2], {}).get('name') == 'Model'],
                                 'textures': textures_for_material})
    textures = sorted({n['props'][0] for n in all_nodes if n['name'] in ('FileName', 'RelativeFilename', 'Filename') and n['props'] and isinstance(n['props'][0], str)})
    globals_ = next((n for n in roots if n['name'] == 'GlobalSettings'), {'children': []})
    settings = {n['props'][0]: n['props'][4:] for n in walk(globals_['children']) if n['name'] == 'P' and len(n['props']) >= 5}
    key_counts = []; time_min = time_max = None; varying_curves = 0
    for n in objects:
        if n['name'] != 'AnimationCurve': continue
        fields = {x['name']: x['props'] for x in n['children']}
        times = fields.get('KeyTime', [])
        values = fields.get('KeyValueFloat', [])
        if times:
            t = [v[0] for v in struct.iter_unpack('<q', times[0]['values'])]
            key_counts.append(len(t))
            if t:
                time_min = min(t) if time_min is None else min(time_min, min(t))
                time_max = max(t) if time_max is None else max(time_max, max(t))
        if values:
            v = [x[0] for x in struct.iter_unpack('<f', values[0]['values'])]
            if v and max(v) - min(v) > 1e-6: varying_curves += 1
    return {'file': str(Path(path).resolve()), 'sha256': hashlib.sha256(data).hexdigest(),
            'bytes': len(data), 'fbx_version': version, 'object_counts': dict(sorted(counts.items())),
            'meshes': meshes, 'total_vertices': sum(m['vertices'] for m in meshes),
            'total_triangles_by_polygon_fan': sum(m['triangles_by_polygon_fan'] for m in meshes),
            'skeleton_joints': names('Model', 'LimbNode'), 'blend_shape_channels': names('Deformer', 'BlendShapeChannel'),
            'joint_details': joint_details,
            'material_details': material_details,
            'animation_stacks': names('AnimationStack'), 'texture_paths': textures, 'global_settings': settings,
            'animation_curve_stats': {'key_counts': dict(Counter(key_counts)), 'varying_curves': varying_curves,
                                      'min_key_time_ticks': time_min, 'max_key_time_ticks': time_max},
            'limitations': 'Structural read only; does not validate skin weights, rig behavior, materials or rendered appearance.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('fbx'); parser.add_argument('--output', required=True)
    args = parser.parse_args()
    report = inspect(args.fbx)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('fbx_version', 'object_counts', 'total_vertices', 'total_triangles_by_polygon_fan', 'blend_shape_channels', 'animation_stacks')}, ensure_ascii=False, indent=2))
