"""Retain the five supplied v2 clips and inspect them without changing live assets."""
import hashlib,json,shutil,subprocess
from pathlib import Path
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'assets/presenter-v2-1080'
FFBIN=ROOT.parent/'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin'
IDS=['1528','1769','7299','7502','3912']
def save(path,image):
    ok,data=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,95]);assert ok
    path.write_bytes(data.tobytes())
def main():
    DEST.mkdir(exist_ok=True);reports=[]
    for key in IDS:
        source,=list((Path.home()/'Downloads').glob(f'jimeng-2026-11-10-{key}-*.mp4'))
        folder=DEST/('incoming-'+key);folder.mkdir(exist_ok=True)
        target=folder/'source.mp4';digest=hashlib.sha256(source.read_bytes()).hexdigest()
        if target.exists():assert hashlib.sha256(target.read_bytes()).hexdigest()==digest
        else:shutil.copy2(source,target)
        probe=subprocess.run([str(FFBIN/'ffprobe.exe'),'-v','error','-show_streams','-show_format','-of','json',str(target)],capture_output=True,encoding='utf-8',check=True)
        metadata=json.loads(probe.stdout);(folder/'source-ffprobe.json').write_text(probe.stdout,encoding='utf-8')
        stream=next(s for s in metadata['streams'] if s['codec_type']=='video')
        capture=cv2.VideoCapture(str(target));expected=int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        indices=np.linspace(0,expected-1,12).round().astype(int).tolist();tiles=[];heads=[];samples=[];count=0
        while True:
            ok,frame=capture.read()
            if not ok:break
            if count in indices:
                seconds=capture.get(cv2.CAP_PROP_POS_MSEC)/1000
                save(folder/f'frame-{count:05d}.jpg',frame)
                tile=cv2.resize(frame,(180,320));cv2.putText(tile,f'{key} {seconds:.2f}s',(5,20),cv2.FONT_HERSHEY_SIMPLEX,.48,(0,255,255),1,cv2.LINE_AA);tiles.append(tile)
                h,w=frame.shape[:2];crop=frame[int(h*.01):int(h*.25),int(w*.28):int(w*.72)]
                head=cv2.resize(crop,(220,260));cv2.putText(head,f'{seconds:.2f}s',(5,20),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,255,255),1,cv2.LINE_AA);heads.append(head)
                samples.append(dict(frame=count,seconds=seconds))
            count+=1
        capture.release();assert count==expected and len(tiles)==12
        subprocess.run([str(FFBIN/'ffmpeg.exe'),'-hide_banner','-v','error','-xerror','-threads','2','-i',str(target),'-map','0:v:0','-map','0:a?','-f','null','-'],check=True)
        save(folder/'fullbody-contact-sheet.jpg',np.vstack([np.hstack(tiles[:6]),np.hstack(tiles[6:])]))
        save(folder/'head-contact-sheet.jpg',np.vstack([np.hstack(heads[:6]),np.hstack(heads[6:])]))
        report=dict(source_id=key,original_path=str(source),sha256=digest,bytes=target.stat().st_size,
            width=stream['width'],height=stream['height'],fps=stream['avg_frame_rate'],frames=count,
            seconds=float(stream.get('duration',metadata['format']['duration'])),audio_present=any(s['codec_type']=='audio' for s in metadata['streams']),
            strict_decode_passed=True,samples=samples,status='AWAITING_VISUAL_CLASSIFICATION')
        (folder/'inspection.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');reports.append(report)
        print(json.dumps({k:v for k,v in report.items() if k not in ('original_path','samples')},ensure_ascii=True),flush=True)
    (DEST/'import-report.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
