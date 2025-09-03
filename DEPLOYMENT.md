# npc-local — DEPLOYMENT

This guide covers prerequisites, CPU/GPU setup, Docker Compose workflows, logs, health checks, and common troubleshooting for **npc-local**.

> TL;DR  
> - **CPU only:** `docker compose up -d --build`  
> - **GPU (NVIDIA, Linux/WSL2):** `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build`  
> - UI at **http://localhost:8000/ui**

---

## 1) Prerequisites

- **Docker** & **Docker Compose v2** (Docker Desktop on Windows/macOS, or docker-ce on Linux).
- **Git** (optional, for cloning).
- **Ports free:** `11434` (Ollama), `8000` (FastAPI server).
- ~**20–30 GB** free disk for models and caches (Ollama models + TTS/Whisper caches).
- For **GPU acceleration** (optional):
  - **NVIDIA GPU** + recent **driver** (Windows or Linux).
  - **WSL2** on Windows with an Ubuntu distro if you want GPU compute inside Linux containers.
  - **NVIDIA Container Toolkit** installed in your Linux/WSL2 environment.
  - `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` should list your GPU.

> Apple Silicon (M-series) can run this stack on CPU; Ollama GPU acceleration uses Metal on macOS but the **server container** TTS/STT GPU paths described here are NVIDIA-only.

---

## 2) Files & Volumes (what gets persisted)

- **Ollama model cache:** Docker volume `ollama` → `/root/.ollama` in the `ollama` container.
- **Server data:** Docker volume `serverdata` → `/data` in the `npc-voice-server` container. Holds:
  - SQLite DB: `/data/npcs.db`
  - Hugging Face cache: `/data/hf`
  - General cache: `/data/.cache`
  - TTS cache: `/data/tts`
  - Per-NPC voices: `/data/voices/{id}/voice.wav`
- **Voice library mount:** `${NPC_VOICES:-./server/voices}:/app/voices:rw` (host folder of reference WAVs).

To wipe **everything** (models, DB, cached weights):
```bash
docker compose down -v
# (optional) remove local ./server/voices if you want a clean slate
```

---

## 3) CPU-only Deployment (works everywhere)

```bash
docker compose up -d --build
# tail server logs
docker compose logs -f server
# tail ollama logs
docker compose logs -f ollama
```

Health checks:
```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/gpuz
```

Open the minimal admin UI:
```
http://localhost:8000/ui
```

> First request may download models (Ollama LLM and Coqui XTTS). It can take a while depending on your connection.

---

## 4) GPU Deployment (NVIDIA, Linux/WSL2)

### 4.1 Confirm your stack sees the GPU
- Windows + WSL2:
  1) Update WSL2: `wsl --update`
  2) Ensure Docker Desktop → Settings → **Use the WSL 2 based engine** and enable your distro under **Resources → WSL Integration**.
- Inside your Linux/WSL2 shell:
  - Install **NVIDIA Container Toolkit**: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
  - Test:
    ```bash
    docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
    # Optional perf sanity check
    docker run --rm -it --gpus all nvcr.io/nvidia/k8s/cuda-sample:nbody nbody -gpu -benchmark
    ```

### 4.2 Start with GPU overlay
Use the provided overlay that requests all GPUs for both services and switches Whisper to `float16`:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

- The overlay typically contains something like:
  ```yaml
  services:
    server:
      environment:
        - WHISPER_COMPUTE=float16
      deploy:
        resources:
          reservations:
            devices:
              - driver: nvidia
                count: all
                capabilities: [gpu]
    ollama:
      deploy:
        resources:
          reservations:
            devices:
              - driver: nvidia
                count: all
                capabilities: [gpu]
  ```

> Notes
> - On some Docker Compose versions, `deploy:` works only with Swarm or requires `--compatibility`. If your Compose rejects `deploy:`, you can alternatively run the **daemon** with `--gpus all` via `docker run`, but for Compose we recommend keeping the overlay and updating Compose to a recent version.
> - The `npc-voice-server` image auto-detects GPU and sets Whisper compute accordingly. If no GPU is visible, it falls back to CPU `int8` and logs: “No GPU visible; using int8.”

---

## 5) Pre-pull models (optional but recommended)

Avoid cold-start waits by pre-pulling:

```bash
# Pull the LLM inside the ollama container
docker exec -it ollama ollama pull gpt-oss:20b

# Warm up TTS model once (downloads XTTS v2 into /data/tts)
curl -X POST http://localhost:8000/tts \
  -H "Content-Type: application/json" \
  -d '{"text":"warm up", "ssml":false, "language":"en"}'
```

---

## 6) Environment Variables (server)

Key variables already set in `docker-compose.yml`:

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_URL` | `http://ollama:11434` | How the server reaches Ollama |
| `LLM_MODEL` | `gpt-oss:20b` | Installed/pulled Ollama model tag |
| `CONTEXT_TOKENS` | `8192` | Max context window for the model |
| `LLM_MAX_TOKENS` | `120` | Max new tokens per reply |
| `LLM_THREADS` | `0` | CPU thread hint for generation (0=auto) |
| `LLM_TEMPERATURE` | `0.7` | Sampling temperature |
| `WHISPER_SIZE` | `small` | Whisper model size for STT |
| `WHISPER_COMPUTE` | `int8` | STT compute (`float16` when on GPU) |
| `TTS_LANGUAGE` | `en` | Default TTS language |
| `TTS_GLOBAL_RATE` | `1.0` | Global TTS speaking rate |
| `HF_HOME` | `/data/hf` | Hugging Face cache |
| `XDG_CACHE_HOME` | `/data/.cache` | General cache |
| `TTS_HOME` | `/data/tts` | TTS cache (Coqui) |
| `COQUI_TOS_AGREED` | `1` | Auto-accept XTTS download prompt |
| `DB_PATH` | `/data/npcs.db` | SQLite database path |
| `VOICES_STORAGE` | `/data/voices` | Per-NPC voice storage |
| `VOICES_DIR` | `/app/voices` | Mounted voice *library* path |

Override any variable by setting it in your shell or `.env` file before `docker compose up`.

---

## 7) Basic Workflow

1) **Start the stack** (CPU or GPU).  
2) Open **http://localhost:8000/ui**.  
3) Click **Create NPC**:
   - Provide **Name**, **Persona**, **Language**, **Tone**.
   - Upload a short, clean **WAV** (~3–10 seconds) under **Voice sample** or specify a **voice_ref** (e.g., `hero.wav`) that exists in your mounted voice library.
   - Optionally tick **Issue API key**.
4) Use the UI to:
   - **List** NPCs, see their **endpoints** & API key
   - **Edit** or **Delete** NPCs (edit/delete requires the NPC’s API key when present)
5) Programmatic usage:
   - POST `/npcs/{id}/reply` with a mic WAV → returns transcript, assistant text, and base64 WAV.
   - POST `/npcs/{id}/reply.wav` → direct audio/wav stream.

---

## 8) Logs & Diagnostics

- Follow logs (both containers):
  ```bash
  docker compose logs -f
  ```

- Only the server:
  ```bash
  docker compose logs -f npc-voice-server
  ```

- Only Ollama:
  ```bash
  docker compose logs -f ollama
  ```

- Shell into server:
  ```bash
  docker exec -it npc-voice-server sh
  ```

- Health checks:
  ```bash
  curl http://localhost:8000/healthz
  curl http://localhost:8000/gpuz
  ```

---

## 9) Performance Tuning

- **GPU on**: ensure your overlay is active and `gpuz` says `torch_cuda: true`.
- **Whisper size**: `WHISPER_SIZE=base` or `small` are good tradeoffs; `large-v3` is heavy.
- **LLM speed**:
  - Reduce `LLM_MAX_TOKENS` (e.g., 80–120 for short NPC replies).
  - Set `LLM_THREADS=0` (auto) or experiment with a manual value equal to physical cores.
  - Ensure your Ollama model is a **quantized** build suitable for your RAM/VRAM.
- **TTS speed**:
  - XTTS v2 runs on CPU reasonably, but GPU helps. Keep reference voices short and clean.
  - Use shorter replies (your persona can encourage brevity).

---

## 10) Troubleshooting (common issues)

### A) Coqui license prompt → container exits
**Symptom:** Logs show:
```
"You must confirm ... CPML ... [y/n]"
Aborted!
```
**Fix:** We set `COQUI_TOS_AGREED=1` in compose; ensure it’s present. For non-commercial/academic use, XTTS v2 is under CPML. See https://coqui.ai/cpml.txt

### B) `JSONDecodeError` loading XTTS `config.json`
**Cause:** Partial/corrupted model cache if the download was interrupted.  
**Fix:** The server auto-recovers by deleting the broken cache. Or manually:
```
docker exec -it npc-voice-server sh -lc 'rm -rf /data/tts/tts/tts_models--multilingual--multi-dataset--xtts_v2'
docker compose restart npc-voice-server
```

### C) `ValueError: Model is multi-speaker but no speaker is provided`
**Cause:** Attempting TTS without any configured voice.  
**Fix:** Create/Edit the NPC with either an uploaded `voice_wav` or a valid `voice_ref` file name that exists under `/app/voices`.

### D) PowerShell `curl` quoting/escaping
Use the documented PowerShell snippets; prefer `curl.exe` and `Resolve-Path` to avoid quoting pitfalls:
```powershell
curl.exe -H ("X-API-Key: {0}" -f $apiKey) `
  -F "session_id=dev1" `
  -F "lang=en" `
  -F ("file=@{0};type=audio/wav" -f (Resolve-Path $inWav).Path) `
  ("http://localhost:8000/npcs/{0}/reply.wav" -f $npcId) `
  -o npc_reply.wav
```

### E) GPU visible on host but not in container
- Confirm `docker compose version` is recent.
- Use the GPU overlay and check `docker compose logs -f npc-voice-server` for “GPU visible” during startup or `GET /gpuz` (`torch_cuda: true`).
- Verify `nvidia-smi` works **inside** a test container (`docker run --rm --gpus all nvidia/cuda:... nvidia-smi`).

### F) LLM replies are empty or very slow
- Ensure the model pulled is valid: `docker exec -it ollama ollama list`
- Pre-pull: `docker exec -it ollama ollama pull gpt-oss:20b`
- Increase `LLM_MAX_TOKENS` and/or `TEMPERATURE` slightly.
- Watch Ollama logs for load time on first request; subsequent runs are faster.

### G) “Voice file not found” for `voice_ref`
Make sure the file exists in the **mounted** library:
```
# host
ls ./server/voices
# inside container
docker exec -it npc-voice-server sh -lc 'ls -l /app/voices'
```

---

## 11) Uninstall / Reset

```bash
docker compose down -v
docker volume rm npc-local_serverdata npc-local_ollama  # names may vary; check `docker volume ls`
# Optional: remove local ./server/voices files you added
```

---

## 12) Security & Footnotes

- **API keys** are per-NPC and stored in SQLite for simplicity; treat them as secrets in your environment.
- The stack is designed for **local/offline development**; if you expose it to a network, add a reverse proxy, TLS, and auth.
- **Licenses:**  
  - LLM model license depends on the Ollama model tag you pull (`gpt-oss:20b` is an OSS-family model; check its license page).
  - **XTTS v2** is CPML (non-commercial) unless you have a commercial Coqui license.
  - **Whisper** and **faster-whisper** are open source; see their repos.
- For academic/university usage, include the **COPYRIGHT** file in this repo as provided.

---

## 13) Quick Smoke Tests

After the stack is up:

```bash
# Health
curl http://localhost:8000/healthz
curl http://localhost:8000/gpuz

# Create an NPC (multipart)
curl -X POST http://localhost:8000/npcs \
  -F "name=Arthur" \
  -F "language=en" \
  -F "tone=formal" \
  -F "persona=You are Arthur, a librarian with fading memories; be gentle and brief." \
  -F "voice_wav=@./server/voices/hero.wav;type=audio/wav" \
  -F "issue_api_key=1"

# List NPCs
curl http://localhost:8000/npcs

# Talk to NPC (WAV out)
NPC_ID=1
API_KEY="paste-key-here"
curl -H "X-API-Key: $API_KEY" \
  -F "session_id=dev1" -F "lang=en" \
  -F "file=@./sample.wav;type=audio/wav" \
  "http://localhost:8000/npcs/${NPC_ID}/reply.wav" -o npc_reply.wav
```

---

Happy building!
