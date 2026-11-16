from pathlib import Path
import cv2
import numpy as np

root = Path('/formal/smile-other-actions-20261111/acknowledge-nod')
capture = cv2.VideoCapture(str(root / 'AC-audible-comparison-50fps.mp4'))
rows = []
for seconds in [4.1, 4.4, 4.7]:
    capture.set(cv2.CAP_PROP_POS_FRAMES, round(seconds * 50))
    ok, frame = capture.read()
    assert ok
    rows.append(frame[:520])
capture.release()
cv2.imencode('.jpg', np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tofile(str(root / 'nod-peak-check.jpg'))
