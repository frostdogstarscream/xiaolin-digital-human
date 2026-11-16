"""Transport lossless RGB clips instead of 8.5 GB of decoded caches."""
import json,subprocess,hashlib,zipfile
from pathlib import Path
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[2];ASSET=ROOT/'assets/presenter-v2-1080';OUT=ROOT/'outputs/presenter-v2-1080'
FFMPEG=ROOT.parent/'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'
profile=json.loads((ASSET/'profile.json').read_text(encoding='utf-8'));cache=OUT/'delivery-cache';cache.mkdir(exist_ok=True)
records=[]
for item in [profile['idle'],*profile['actions']]:
    directory=ROOT/item['avatar_dir'];target=cache/(item['id']+'-rgb.mp4');marker=target.with_suffix('.json')
    if marker.exists():records.append(json.loads(marker.read_text()));continue
    subprocess.run([str(FFMPEG),'-hide_banner','-v','error','-nostdin','-y','-framerate','25','-i',str(directory/'full_imgs/%08d.png'),
        '-an','-c:v','libx264rgb','-crf','0','-preset','veryfast','-g','25','-threads','4','-pix_fmt','bgr24','-movflags','+faststart',str(target)],check=True)
    original=np.load(directory/'frames.npy',mmap_mode='r');cap=cv2.VideoCapture(str(target));count=0
    while True:
        ok,frame=cap.read()
        if not ok:break
        assert count<len(original) and np.array_equal(original[count],frame),(item['id'],count,'RGB transport must be lossless')
        count+=1
    cap.release();original._mmap.close();del original
    assert count==item['frames']
    record=dict(id=item['id'],file=target.name,frames=count,all_frames_pixel_exact=True,bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    marker.write_text(json.dumps(record,indent=2));records.append(record);print(json.dumps(record),flush=True)
(cache/'manifest.json').write_text(json.dumps(records,indent=2))
target=OUT/'presenter-v2-1080-delivery.zip'
with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
    for path in cache.iterdir():archive.write(path,'transport/'+path.name)
    archive.write(ASSET/'profile.json','avatar-2d/assets/presenter-v2-1080/profile.json')
    archive.write(ASSET/'aligned-contact-sheet.jpg','avatar-2d/assets/presenter-v2-1080/aligned-contact-sheet.jpg')
    archive.write(ROOT/'assets/calibration-speech-16k-v1.wav','avatar-2d/assets/calibration-speech-16k-v1.wav')
    archive.write(ROOT/'tools/windows_runtime.py','avatar-2d/tools/windows_runtime.py')
    for path in Path(__file__).parent.glob('*.py'):archive.write(path,'avatar-2d/experiments/presenter-v2-1080/'+path.name)
    for path in Path(__file__).parent.glob('*.js'):archive.write(path,'avatar-2d/experiments/presenter-v2-1080/'+path.name)
    for path in Path(__file__).parent.glob('*Preview.cmd'):archive.write(path,'avatar-2d/experiments/presenter-v2-1080/'+path.name)
    for path in [ASSET/'prepared/idle-loop-seam.mp4',OUT/'idle-seam-contact-sheet.jpg',OUT/'验收记录.txt']:
        if path.exists():archive.write(path,'avatar-2d/'+path.relative_to(ROOT).as_posix())
    for item in [profile['idle'],*profile['actions']]:
        directory=ROOT/item['avatar_dir']
        for name in ['coords.json','prepared.json']:archive.write(directory/name,'avatar-2d/'+item['avatar_dir']+'/'+name)
        archive.write(ROOT/item['video'],'avatar-2d/'+item['video'])
        output=OUT/item['id']
        for name in ['speaking-1080p.mp4','face-before-after.jpg','report.json']:archive.write(output/name,'avatar-2d/outputs/presenter-v2-1080/'+item['id']+'/'+name)
    for path in OUT.glob('*.json'):archive.write(path,'avatar-2d/outputs/presenter-v2-1080/'+path.name)
print(json.dumps(dict(archive=str(target),bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest())),flush=True)
