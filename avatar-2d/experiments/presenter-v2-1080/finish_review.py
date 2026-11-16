"""Create a hard-cut loop seam sample and consolidate measured evidence."""
import json, subprocess, hashlib, zipfile
from pathlib import Path
import cv2

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs/presenter-v2-1080'
ASSET = ROOT / 'assets/presenter-v2-1080'
FFMPEG = ROOT.parent / 'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'
seam = ASSET / 'prepared/idle-loop-seam.mp4'
subprocess.run([str(FFMPEG), '-hide_banner', '-v', 'error', '-nostdin', '-y',
    '-ss', '28', '-t', '2', '-i', str(ASSET / 'prepared/idle.mp4'),
    '-t', '2', '-i', str(ASSET / 'prepared/idle.mp4'), '-filter_complex',
    '[0:v]setpts=PTS-STARTPTS[x];[1:v]setpts=PTS-STARTPTS[y];[x][y]concat=n=2:v=1:a=0[v]',
    '-map', '[v]', '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '15',
    '-threads', '4', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(seam)], check=True)
cap = cv2.VideoCapture(str(seam))
assert cap.get(cv2.CAP_PROP_FRAME_COUNT) == 100
assert (cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) == (1080,1920)
images = []
for index in (47,48,49,50,51,52):
    cap.set(cv2.CAP_PROP_POS_FRAMES,index)
    ok, frame = cap.read(); assert ok
    image = cv2.resize(frame,(270,480))
    cv2.putText(image, str(index), (12,28),cv2.FONT_HERSHEY_SIMPLEX,.7,(0,220,255),2)
    images.append(image)
cap.release()
import numpy as np
ok, encoded = cv2.imencode('.jpg', np.concatenate(images,axis=1)); assert ok
(OUT/'idle-seam-contact-sheet.jpg').write_bytes(encoded.tobytes())
raw = (OUT/'browser-review.log').read_text(encoding='utf-8')
browser = json.loads(raw.split('### Result',1)[1].split('### Ran',1)[0].strip())
(OUT/'browser-review-report.json').write_text(json.dumps(browser,indent=2),encoding='utf-8')
archive = OUT/'presenter-v2-1080-delivery.zip'
with zipfile.ZipFile(archive,'a',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as package:
    existing = set(package.namelist())
    paths = [seam,OUT/'browser-review-report.json',OUT/'idle-seam-contact-sheet.jpg']
    paths += list(Path(__file__).parent.glob('*Preview.cmd'))
    paths += [Path(__file__).parent/'preview_control.py',Path(__file__)]
    for path in paths:
        name = 'avatar-2d/'+path.relative_to(ROOT).as_posix()
        if name not in existing:
            package.write(path,name)
with zipfile.ZipFile(archive,'r') as package:
    assert package.testzip() is None
digest = hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()
(OUT/'delivery-sha256.txt').write_text(digest+'  '+archive.name+'\n')
print(json.dumps({'seam_frames':100,'archive_bytes':archive.stat().st_size,'sha256':digest}))
