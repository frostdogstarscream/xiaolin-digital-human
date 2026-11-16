"""Run in Maya's Python Script Editor; does not save or overwrite the Maya scene.

    import sys
    sys.path.insert(0, r'D:\Code\3D数字人\fay-ue4\tools')
    import maya_export
    maya_export.export_selected(r'D:\Models\Reception\character.fbx')

Select the skeleton root AND skinned mesh group before calling. The report is
written alongside the FBX. For animations, pass bake=True, start=1, end=120.
"""
import json
import os


def inspect_selected():
    import maya.cmds as cmds
    selected = cmds.ls(selection=True, long=True) or []
    nodes = set(selected)
    for root in selected:
        nodes.update(cmds.listRelatives(root, allDescendents=True, fullPath=True) or [])
    meshes = [n for n in nodes if cmds.nodeType(n) == 'mesh' and not cmds.getAttr(n + '.intermediateObject')]
    joints = [n for n in nodes if cmds.nodeType(n) == 'joint']
    roots = [j for j in joints if not any(p in nodes and cmds.nodeType(p) == 'joint' for p in (cmds.listRelatives(j, parent=True, fullPath=True) or []))]
    errors, warnings, blends = [], [], {}
    if not meshes: errors.append('Select at least one skinned mesh.')
    if len(roots) != 1: errors.append('Select exactly one export skeleton root; found %d.' % len(roots))
    if cmds.currentUnit(query=True, linear=True) != 'cm': errors.append('Use a centimetre export scene. Do not rescale an already bound rig blindly.')
    triangles = 0
    for mesh in meshes:
        history = cmds.listHistory(mesh) or []
        skins = cmds.ls(history, type='skinCluster') or []
        if not skins: errors.append('Mesh has no skinCluster: ' + mesh)
        for skin in skins:
            influences = cmds.skinCluster(skin, query=True, influence=True) or []
            missing = [j for j in influences if not any(x in nodes for x in (cmds.ls(j, long=True) or []))]
            if missing: errors.append('Skin influences omitted from selection: ' + ', '.join(missing))
        triangles += cmds.polyEvaluate(mesh, triangle=True)
        for node in cmds.ls(history, type='blendShape') or []:
            aliases = (cmds.aliasAttr(node, query=True) or [])[0::2]
            blends[node] = aliases
    if not blends: errors.append('No blendShape deformers found. Add jaw-open and left/right blink targets before production use.')
    if triangles > 80000: warnings.append('Over 80k triangles: evaluate LOD reduction on the target GTX 1660.')
    textures = []
    for file_node in cmds.ls(type='file') or []:
        path = cmds.getAttr(file_node + '.fileTextureName') or ''
        textures.append(path)
        if path and '<UDIM>' not in path and not os.path.isfile(path): warnings.append('Missing texture: ' + path)
    return {'selection': selected, 'mesh_count': len(meshes), 'joint_count': len(joints),
            'skeleton_roots': roots, 'triangles': triangles, 'blend_shapes': blends,
            'textures': textures, 'errors': errors, 'warnings': warnings, 'fbx_version': '2018'}


def export_selected(destination, bake=False, start=None, end=None):
    import maya.cmds as cmds
    import maya.mel as mel
    report = inspect_selected()
    destination = os.path.abspath(destination)
    if not destination.lower().endswith('.fbx'): raise ValueError('Destination must end in .fbx')
    if os.path.exists(destination): raise ValueError('Destination already exists; choose a new filename.')
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination + '.report.json', 'w', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    if report['errors']: raise ValueError('\n'.join(report['errors']))
    if not cmds.pluginInfo('fbxmaya', query=True, loaded=True): cmds.loadPlugin('fbxmaya')
    mel.eval('FBXResetExport;')
    mel.eval('FBXExportFileVersion -v "FBX201800";')
    mel.eval('FBXExportSkins -v true;')
    mel.eval('FBXExportShapes -v true;')
    mel.eval('FBXExportInputConnections -v false;')
    mel.eval('FBXExportEmbeddedTextures -v false;')
    mel.eval('FBXExportBakeComplexAnimation -v %s;' % ('true' if bake else 'false'))
    if bake:
        first = float(start if start is not None else cmds.playbackOptions(query=True, minTime=True))
        last = float(end if end is not None else cmds.playbackOptions(query=True, maxTime=True))
        if last < first: raise ValueError('Animation end precedes start')
        mel.eval('FBXExportBakeComplexStart -v %s;' % first)
        mel.eval('FBXExportBakeComplexEnd -v %s;' % last)
        mel.eval('FBXExportBakeComplexStep -v 1;')
    # MEL string quoting; reject quotes rather than interpolate executable source.
    if '"' in destination or '\n' in destination: raise ValueError('Unsupported output filename')
    mel.eval('FBXExport -f "%s" -s;' % destination.replace('\\', '/'))
    return report
