
# SPDX-License-Identifier: MIT
# Copyright (c) 2025 <Reza Jari>

FROM pytorch/pytorch:2.3.1-cuda12.1-cudnn8-runtime

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY server/requirements.txt .
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -r requirements.txt

# App code
COPY server/ /app/

# Agree to Coqui CPML to avoid interactive prompt
ENV COQUI_TOS_AGREED=1

# Cache dirs (mounted as volume by compose)
ENV HF_HOME=/data/hf \
    XDG_CACHE_HOME=/data/.cache \
    TTS_HOME=/data/tts

# Add an entrypoint that picks CPU/GPU for Whisper at runtime
COPY server/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
