"""Create matched videos from original pose frames and frozen audio."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

root=Path('/eval/inputs');root.mkdir(exist_ok=True)
avatars=Path('/avatars')
source=avatars/'presenter_v1__welcome-wave/full_imgs/00000000.png'
shutil.copy2(source,root/'reference.png')
fixtures=json.loads(Path('/fixtures/manifest.json').read_text())['fixtures']
records=[]
for item in fixtures:
    audio=Path('/fixtures')/Path(item['file']).name
    assert hashlib.sha256(audio.read_bytes()).hexdigest()==item['sha256']
    shutil.copy2(audio,root/audio.name)
    frames=round(item['seconds']*25)
    for action in ['idle','explain-open-palms']:
        output=root/f"{action}-{item['id']}.mp4"
        command=['ffmpeg','-v','error','-nostdin','-y']
        if action=='idle':command+=['-loop','1','-framerate','25','-i',str(source)]
        else:command+=['-framerate','25','-i',str(avatars/f'presenter_v1__{action}/full_imgs/%08d.png'),
                       '-vf',f"tpad=stop_mode=clone:stop_duration={item['seconds']}"]
        command+=['-frames:v',str(frames),'-an','-c:v','libx264','-preset','veryfast','-threads','2',
                  '-crf','18','-pix_fmt','yuv420p',str(output)]
        subprocess.run(command,check=True)
        records.append({'file':output.name,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
                        'frames':frames,'fps':25,'audio_file':audio.name,'audio_sha256':item['sha256'],
                        'pose':action})
(root/'manifest.json').write_text(json.dumps({'reference_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                                             'videos':records},indent=2))
print('MATCHED_INPUTS_READY',flush=True)
