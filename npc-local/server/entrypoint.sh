#!/usr/bin/env bash
set -e

# Default to CPU-friendly; flip to GPU if visible
export WHISPER_COMPUTE=${WHISPER_COMPUTE:-int8}

HAS_GPU=0
if command -v nvidia-smi >/dev/null 2>&1; then
  if nvidia-smi -L >/dev/null 2>&1; then
    HAS_GPU=1
  fi
fi
if [ "${FORCE_CPU:-0}" = "1" ]; then HAS_GPU=0; fi

if [ "$HAS_GPU" = "1" ]; then
  echo "[entrypoint] NVIDIA GPU detected. Installing GPU CTranslate2 & using float16."
  # GPU wheel for faster-whisper (CTranslate2 with CUDA). First run downloads once.
  pip install --no-cache-dir --upgrade ctranslate2 -f https://opennmt.net/ctranslate2/whl/cu121
  export WHISPER_COMPUTE=${WHISPER_COMPUTE_OVERRIDE:-float16}
else
  echo "[entrypoint] No GPU visible. Installing CPU CTranslate2 & using int8."
  pip install --no-cache-dir --upgrade ctranslate2
  export WHISPER_COMPUTE=${WHISPER_COMPUTE_OVERRIDE:-int8}
fi

# Optional: tune LLM threads/predict/context via envs; fine on CPU/GPU
export CONTEXT_TOKENS=${CONTEXT_TOKENS:-8192}
export LLM_MAX_TOKENS=${LLM_MAX_TOKENS:-120}
export LLM_THREADS=${LLM_THREADS:-0} # 0=auto in Ollama

# Boot the API
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-1}
