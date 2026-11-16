FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SDL_AUDIODRIVER=dummy HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libgomp1 libglib2.0-0 libgl1 libportaudio2 portaudio19-dev gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-*.txt /build/

FROM base AS presenter
RUN pip install --no-cache-dir torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1 --index-url https://download.pytorch.org/whl/cu128
RUN pip install --no-cache-dir -r /build/requirements-presenter.txt && pip check

FROM base AS asr
RUN pip install --no-cache-dir torch==2.9.1 torchaudio==2.9.1 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r /build/requirements-asr.txt && pip check

FROM base AS fay
RUN pip install --no-cache-dir torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r /build/requirements-fay.txt && pip check
