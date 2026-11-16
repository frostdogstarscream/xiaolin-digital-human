"""Decode all frames, sample the presenter, and retain reproducible local QC."""
import json
from pathlib import Path
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
ASSET=ROOT/'assets/presenter-v1'
SOURCE=ASSET/'source-jimeng-v1.mp4'


def save(path,array):
    ok,data=cv2.imencode('.jpg',array,[cv2.IMWRITE_JPEG_QUALITY,95])
    if not ok:raise RuntimeError('Image encoding failed')
    path.write_bytes(data.tobytes())


def inspect():
    output=ASSET/'inspection-v1';output.mkdir(exist_ok=True)
    video=cv2.VideoCapture(str(SOURCE))
    if not video.isOpened():raise RuntimeError('Cannot decode source video')
    # Read XML through Python: this OpenCV Windows build cannot open Unicode paths.
    xml=Path(cv2.data.haarcascades+'haarcascade_frontalface_default.xml').read_text(encoding='utf-8')
    storage=cv2.FileStorage(xml,cv2.FILE_STORAGE_READ|cv2.FILE_STORAGE_MEMORY)
    face_detector=cv2.CascadeClassifier()
    if not face_detector.read(storage.getFirstTopLevelNode()):raise RuntimeError('Cannot load detector')
    storage.release()
    targets=[0,4,8,12,16,20,24,29]
    samples=[];decoded=0;index=0
    while True:
        ok,frame=video.read()
        if not ok:break
        decoded+=1;seconds=video.get(cv2.CAP_PROP_POS_MSEC)/1000
        if index<len(targets) and seconds>=targets[index]:
            gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
            faces=face_detector.detectMultiScale(gray,scaleFactor=1.06,minNeighbors=5,minSize=(60,60))
            faces=[list(map(int,f)) for f in faces if f[1]<frame.shape[0]*.45]
            face=max(faces,key=lambda f:f[2]*f[3]) if faces else None
            full=frame.copy();cv2.putText(full,'t={:.2f}s'.format(seconds),(16,35),cv2.FONT_HERSHEY_SIMPLEX,.8,(255,255,255),2)
            save(output/('frame-{:02d}.jpg'.format(index)),full)
            if face:
                x,y,w,h=face;margin=round(w*.25)
                crop=frame[max(0,y-margin):y+h+margin,max(0,x-margin):x+w+margin]
                save(output/('face-{:02d}.jpg'.format(index)),crop)
            samples.append(dict(requested=targets[index],time=seconds,frame=decoded-1,face_bbox=face))
            index+=1
    video.release()
    if decoded<2 or len(samples)!=len(targets):raise RuntimeError('Incomplete frame decode')
    tiles=[]
    for i in range(len(samples)):
        raw=cv2.imdecode(np.frombuffer((output/('frame-{:02d}.jpg'.format(i))).read_bytes(),dtype=np.uint8),cv2.IMREAD_COLOR)
        tiles.append(cv2.resize(raw,(225,400)))
    save(output/'fullbody-contact-sheet.jpg',np.vstack([np.hstack(tiles[:4]),np.hstack(tiles[4:])]))
    face_tiles=[]
    for i in range(len(samples)):
        p=output/('face-{:02d}.jpg'.format(i))
        if not p.exists():continue
        raw=cv2.imdecode(np.frombuffer(p.read_bytes(),dtype=np.uint8),cv2.IMREAD_COLOR)
        raw=cv2.resize(raw,(240,240))
        cv2.putText(raw,'{:.1f}s'.format(samples[i]['time']),(8,22),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,255,255),1)
        face_tiles.append(raw)
    if len(face_tiles)==8:save(output/'face-contact-sheet.jpg',np.vstack([np.hstack(face_tiles[:4]),np.hstack(face_tiles[4:])]))
    report=dict(decoded_frames=decoded,samples=samples,face_detection='OpenCV Haar frontal detector, not identity or mouth verification',visual_review_required=True,lip_sync_verified=False)
    (output/'decode-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':inspect()
