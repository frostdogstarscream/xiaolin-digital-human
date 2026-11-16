set -eu
docker exec xiaolin-formal50-materials sh -c 'mkdir -p /formal/smile-review-20261111/libs; python -m pip install --no-deps --target /formal/smile-review-20261111/libs mediapipe==0.10.32 absl-py==2.3.1 flatbuffers==25.9.23 sounddevice==0.5.3 > /formal/smile-review-20261111/setup.log 2>&1'
docker exec xiaolin-formal50-materials python -c 'import urllib.request, pathlib; urllib.request.urlretrieve("https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task", "/formal/smile-review-20261111/face_landmarker.task")'
docker exec xiaolin-formal50-materials sh -c 'PYTHONPATH=/formal/smile-review-20261111/libs python -c "import mediapipe; print(mediapipe.__version__)"'
