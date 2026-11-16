"""Run with UE4Editor-Cmd -run=pythonscript -script=<this file>."""
import os
import unreal

level = '/Game/Kiosk/Stage'
if not os.path.isfile(os.path.join(unreal.Paths.project_content_dir(), 'Kiosk', 'Stage.umap')):
    if not unreal.EditorLevelLibrary.new_level(level): raise RuntimeError('Could not create stage map')
    if not unreal.EditorLevelLibrary.save_current_level(): raise RuntimeError('Could not save stage map')
# The runtime GameMode creates the camera, simple lights and character. No sky,
# ground plane or editor grid is part of the packaged display.
audio = os.path.abspath(os.path.join(unreal.Paths.project_dir(), '..', 'assets', 'service_unavailable.wav'))
if os.path.isfile(audio) and not unreal.EditorAssetLibrary.does_asset_exist('/Game/Kiosk/ServiceUnavailable'):
    task = unreal.AssetImportTask()
    for key, value in {'filename': audio, 'destination_path': '/Game/Kiosk', 'destination_name': 'ServiceUnavailable',
                       'automated': True, 'save': True, 'replace_existing': False}.items(): task.set_editor_property(key, value)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
unreal.log('Kiosk map prepared; no production character has been fabricated.')
