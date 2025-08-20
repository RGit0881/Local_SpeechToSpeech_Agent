# npc-local — Local AI NPC Server (STT → LLM → TTS)
© 2025 Reza jari. Code licensed under MIT. Third-party models/assets retain their own licenses.

A self-hosted voice NPC pipeline for games/prototypes. Each teammate runs it locally (no cloud costs).  
You speak in (WAV) → Whisper transcribes → LLM replies (Ollama) → Coqui TTS speaks back (XTTS v2).

**Stack**
- **LLM**: `gpt-oss:20b` via **Ollama**
- **STT**: **faster-whisper** (CT2 backend; CPU/GPU)
- **TTS**: **Coqui TTS** `xtts_v2` (speaker cloning)
- **API/UI**: FastAPI + lightweight HTML admin UI
- **DB**: SQLite (NPCs, sessions, messages, API keys)
- **Containers**: Docker Compose (CPU by default, GPU overlay available)

> ⚠️ Licensing: Coqui XTTS v2 model is CPML (non-commercial) unless you have a commercial license. Details in the NOTICE doc (generated later).

---

## 1) Requirements

- Docker Desktop (Windows/macOS) or Docker Engine (Linux)
- (Optional, for acceleration) NVIDIA GPU with drivers + NVIDIA Container Toolkit
- Ports: `11434` (Ollama), `8000` (server)

---

## 2) Repo layout

```
npc-local/
├─ docker-compose.yml
├─ docker-compose.gpu.yml          # overlay for GPU
├─ server/
│  ├─ Dockerfile
│  ├─ main.py
│  ├─ db.py
│  ├─ requirements.txt
│  └─ ui/
│     └─ index.html                # minimal admin UI
└─ ...
```

---

## 3) First run

### CPU (default)

```bash
docker compose up -d --build
docker compose logs -f
```

### GPU (overlay)

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
docker compose logs -f
```

**Verify GPU**
- Host: `nvidia-smi`
- Sample: `docker run --rm --gpus=all nvcr.io/nvidia/k8s/cuda-sample:nbody nbody -gpu -benchmark`
- App: `GET http://localhost:8000/gpuz`

---

## 4) One-time LLM pull

```bash
docker exec -it ollama ollama pull gpt-oss:20b
```

(You can swap models later; any chat-capable Ollama model will work.)

---

## 5) Open the UI

Visit: `http://localhost:8000/ui`

**Create NPC**
- **Name**: e.g., “Arthur”
- **Language**: e.g., `en`
- **Tone**: optional flavor (“formal”, “noir”, “sarcastic”)
- **Persona**: the system prompt / roleplay guide
- **Voice**:
  - Upload **voice_wav** (a short clean WAV sample), **or**
  - Provide **voice_ref** (a filename present in the mounted library)
- **Issue API key?**: check to protect that NPC’s endpoints

> Mount your voice library into the server with `NPC_VOICES` or the default `./server/voices`:
>
> In `docker-compose.yml`:
> ```yaml
> volumes:
>   - serverdata:/data
>   - ${NPC_VOICES:-./server/voices}:/app/voices:rw
> ```

---

## 6) Quick sanity checks

**Health**
```
GET http://localhost:8000/healthz         → { "ok": true }
GET http://localhost:8000/gpuz            → GPU/Whisper info
GET http://localhost:8000/npcs            → list NPCs
```

**Create → Edit → Test in UI**
- Create an NPC
- Click **Edit** → use **Quick Test** to upload a short input WAV and a session id (e.g., `dev1`)
- Play the returned audio, check history

---

## 7) Minimal command-line test

### Linux/macOS (bash)

```bash
NPC_ID=1
API_KEY=      # fill if your NPC has one
IN_WAV=./sample.wav

curl -H "X-API-Key: $API_KEY"   -F "session_id=dev1"   -F "lang=en"   -F "file=@${IN_WAV};type=audio/wav"   "http://localhost:8000/npcs/${NPC_ID}/reply.wav" -o npc_reply.wav
```

### Windows (PowerShell)

```powershell
$npcId  = 1
$apiKey = ""   # paste if required
$inWav  = "C:\path	o\sample.wav"

curl.exe -H ("X-API-Key: {0}" -f $apiKey) `
  -F "session_id=dev1" `
  -F "lang=en" `
  -F ("file=@{0};type=audio/wav" -f (Resolve-Path $inWav).Path) `
  ("http://localhost:8000/npcs/{0}/reply.wav" -f $npcId) `
  -o npc_reply.wav
```

---

## 8) Stopping / cleaning

```bash
# stop containers, keep volumes (DB/voices/cache)
docker compose down

# stop + delete volumes (fresh start)
docker compose down -v
```

---

## 9) Environment (server) — defaults

Set in `docker-compose.yml` under `services.server.environment`:

| Var | Default | Purpose |
|---|---:|---|
| `OLLAMA_URL` | `http://ollama:11434` | Ollama endpoint |
| `LLM_MODEL` | `gpt-oss:20b` | Ollama model |
| `CONTEXT_TOKENS` | `8192` | LLM context window |
| `LLM_MAX_TOKENS` | `120` | Max reply tokens |
| `LLM_TEMPERATURE` | `0.7` | Creativity |
| `LLM_THREADS` | `0` | 0=auto |
| `WHISPER_SIZE` | `small` | tiny/base/small/medium/large-v3 |
| `WHISPER_COMPUTE` | `int8` | `float16` if GPU, `int8` CPU |
| `TTS_LANGUAGE` | `en` | XTTS language |
| `TTS_GLOBAL_RATE` | `1.0` | Global speech rate |
| `DB_PATH` | `/data/npcs.db` | SQLite path |
| `VOICES_STORAGE` | `/data/voices` | per-NPC voice store |
| `VOICES_DIR` | `/app/voices` | mounted voice library |
| `COQUI_TOS_AGREED` | `1` | required for XTTS v2 |
| `HF_HOME`/`XDG_CACHE_HOME`/`TTS_HOME` | under `/data` | model caches |

---

## 10) What’s persisted?

- DB: `/data/npcs.db`
- Per-NPC voice: `/data/voices/<id>/voice.wav`
- Caches: `/data/tts`, `/data/.cache`, `/data/hf`

(Stored in the `serverdata` Docker volume.)
