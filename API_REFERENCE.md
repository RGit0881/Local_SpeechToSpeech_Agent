# npc-local — API Reference

This document describes the HTTP endpoints exposed by **npc-local** (FastAPI).  
All endpoints are served from the same base URL (default: `http://localhost:8000`).

- **Auth model:** per‑NPC *optional* API key via `X-API-Key` header. If set for an NPC, all `/npcs/{id}/...` calls must include the correct key.
- **Audio I/O:** Upload mono PCM **WAV** (16‑bit recommended). Output TTS is WAV (24 kHz).
- **Content types:** JSON for programmatic calls, `multipart/form-data` for audio uploads and form fields.
- **UI:** Minimal admin UI at `/ui` helps you create/edit/delete NPCs and test requests.

---

## Quick Index

| Group | Method | Path | Purpose |
|---|---|---|---|
| System | GET | `/healthz` | Liveness probe |
| System | GET | `/gpuz` | GPU/STT runtime info |
| Persona (legacy, in‑mem) | POST | `/persona` | Set system prompt for a **session_id** |
| Persona (legacy, in‑mem) | GET | `/persona?session_id=...` | Read session persona |
| STT | POST | `/stt` | Transcribe uploaded WAV |
| STT | POST | `/stt_json` | Transcribe base64 audio |
| Chat (in‑mem) | POST | `/chat` | Chat with in‑mem session (not DB) |
| NPCs | POST | `/npcs` | **Create** NPC (multipart) |
| NPCs | GET | `/npcs` | **List** NPCs |
| NPCs | GET | `/npcs/{npc_id}` | **Get** NPC details |
| NPCs | PATCH | `/npcs/{npc_id}` | **Edit** NPC (multipart) |
| NPCs | DELETE | `/npcs/{npc_id}` | **Delete** NPC |
| NPC sessions | GET | `/npcs/{npc_id}/history?session_id=...` | Get chat history for one session |
| NPC chat | POST | `/npcs/{npc_id}/reply` | Full loop (STT → LLM → TTS) returning JSON with base64 audio |
| NPC chat | POST | `/npcs/{npc_id}/reply.wav` | Full loop returning **WAV** stream |

> **Notes**
> - `/chat` and `/persona` operate on an in‑memory session map and are mostly for quick prototyping. Production NPCs use the `/npcs/*` routes backed by SQLite.
> - If an NPC lacks a voice, `/npcs/{id}/reply*` will respond **400** (“no voice configured”).

---

## Authentication

Some NPCs may have an API key (set at create time with `issue_api_key=1` or later via **Edit → Rotate key**). When a key is present you **must** send it:

```
X-API-Key: <the-npc-api-key>
```

Errors:
- `401 Unauthorized` — missing/invalid API key
- `404 Not Found` — NPC id does not exist

---

## System

### `GET /healthz`

Returns `{ "ok": true }` if the server is healthy.

### `GET /gpuz`

Introspection for STT/torch runtime. Example response:

```json
{
  "whisper_compute": "int8",
  "torch_cuda": true,
  "torch_devices": 1,
  "torch_name": "NVIDIA GeForce RTX 4070 Laptop GPU"
}
```

---

## Speech‑to‑Text (STT)

### `POST /stt`  (multipart)

Form fields:
- `file` — audio file (WAV preferred)
- `lang` — language hint (e.g., `en`)

Response:
```json
{ "text": "recognized transcript" }
```

### `POST /stt_json`  (application/json)

Body:
```json
{ "audio_b64": "<base64 wav>", "lang": "en" }
```

Response:
```json
{ "text": "recognized transcript" }
```

---

## In‑memory Persona & Chat (legacy helpers)

### `POST /persona`

Body (JSON):
```json
{ "session_id": "dev1", "persona": "You are a cheerful shopkeeper." }
```

### `GET /persona?session_id=dev1`

Response:
```json
{ "session_id": "dev1", "persona": "You are a cheerful shopkeeper." }
```

### `POST /chat`

Body (JSON):
```json
{
  "session_id": "debug",
  "messages": [
    { "role": "user", "content": "Say hi in one short sentence." }
  ]
}
```

Response:
```json
{ "reply": "Hi there!" }
```

> These endpoints **do not** persist to DB and are independent of `/npcs/*`.

---

## NPC Management

### `POST /npcs`  (multipart — **create**)

Fields:
- `name` *(required)* — NPC display name (slug must be unique)
- `persona` *(required)* — system prompt / roleplay instructions
- `tone` *(optional)* — extra style hints (e.g., “formal”, “noir”)
- `language` *(default:* `en`* )* — TTS language
- **Voice (choose one):**
  - `voice_wav` *(file, optional)* — upload a short clean reference WAV
  - `voice_ref` *(string, optional)* — filename under the mounted voice library (e.g., `hero.wav`)
- `issue_api_key` *(0/1)* — issue and return an API key

Response:
```json
{
  "id": 3,
  "name": "Arthur",
  "slug": "arthur",
  "language": "en",
  "tone": "formal",
  "api_key": "d2f128cc34...",
  "voice_ref": null,
  "voice_path": "/data/voices/3/voice.wav",
  "persona_preview": "You are...",
  "endpoints": {
    "reply_json": "/npcs/3/reply",
    "reply_wav": "/npcs/3/reply.wav",
    "history": "/npcs/3/history?session_id=YOUR_SESSION_ID"
  }
}
```

Errors:
- `400` — duplicate slug (name already used)
- `400` — invalid `voice_ref` (file not present in library)

### `GET /npcs`  (list)

Returns:
```json
[
  { "id": 3, "name": "Arthur", "slug": "arthur", "api_key": true },
  ...
]
```

### `GET /npcs/{npc_id}`

Returns full details (including persona and voice fields).

### `PATCH /npcs/{npc_id}`  (multipart — **edit**)

Headers:
- `X-API-Key` — required if the NPC has a key

Fields (all optional; only provided fields are changed):
- `name`, `persona`, `tone`, `language`
- `voice_wav` *(file)* — replace stored voice
- `voice_ref` *(string)* — point to another file in library
- `rotate_api_key` *(0/1)* — rotate/regenerate key

Response:
```json
{ "ok": true, "api_key": "new-or-existing-key-or-null" }
```

### `DELETE /npcs/{npc_id}`

Headers:
- `X-API-Key` — required if the NPC has a key

Deletes the NPC, its sessions, messages, and stored voice (if any).

Responses:
- `200 { "ok": true }`
- `401` if key missing/invalid
- `404` if not found

---

## NPC Conversation

### `GET /npcs/{npc_id}/history?session_id=dev1`

Returns ordered messages for that session (system, user, assistant):

```json
[
  { "role": "system", "content": "You are ...", "at": "2025-08-20T15:29:15.084372" },
  { "role": "user", "content": "Hello?" , "at": "..." },
  { "role": "assistant", "content": "Hi there.", "at": "..." }
]
```

### `POST /npcs/{npc_id}/reply`  (multipart — JSON result)

Headers:
- `X-API-Key` — required if the NPC has a key

Fields:
- `session_id` *(required)* — any string to group a conversation
- `lang` *(default:* `en`* )* — STT/TTS language code
- `file` *(required)* — input audio (WAV)

Response:
```json
{
  "transcript": "user text",
  "reply_text": "assistant text",
  "audio_b64": "<base64 wav of the spoken reply>"
}
```

### `POST /npcs/{npc_id}/reply.wav`  (multipart — WAV stream)

Same fields as above; returns `audio/wav` directly.


---

## SSML support (subset)

The TTS endpoint accepts **plain text** or **SSML‑like** markup. Supported tags:

- `<break time="500ms|1s">` — inserts silence
- `<prosody rate="x-slow|slow|medium|fast|x-fast|1.2|0.8">` … `</prosody>` — local speaking rate override

Example:
```xml
You found the relic. <break time="600ms"/> 
<prosody rate="slow">Use it wisely.</prosody>
```

> Internally all SSML is converted to multiple segments with optional pauses and rate scaling; voice and language are inherited from the NPC configuration.

---

## Error Codes

| Code | Meaning | Typical cause |
|---:|---|---|
| 400 | Bad Request | Missing fields, invalid `voice_ref`, NPC without voice |
| 401 | Unauthorized | Missing/invalid `X-API-Key` for a protected NPC |
| 404 | Not Found | NPC id or session not found |
| 422 | Unprocessable Entity | Wrong content type or form structure |
| 500 | Internal Server Error | Model init / I/O errors |

---

## Examples

### Create NPC (multipart)

```bash
curl -X POST http://localhost:8000/npcs \
  -F "name=Arthur" \
  -F "language=en" \
  -F "tone=formal" \
  -F "persona=You are Arthur, a librarian with fading memories; be gentle, brief." \
  -F "voice_wav=@./voices/arthur_ref.wav;type=audio/wav" \
  -F "issue_api_key=1"
```

### Talk to NPC and get WAV (bash)

```bash
NPC_ID=3
API_KEY="d2f128cc34..."   # from create response
IN_WAV=./sample.wav

curl -H "X-API-Key: $API_KEY" \
  -F "session_id=dev1" \
  -F "lang=en" \
  -F "file=@${IN_WAV};type=audio/wav" \
  "http://localhost:8000/npcs/${NPC_ID}/reply.wav" -o npc_reply.wav
```

### Talk to NPC and get JSON (PowerShell)

```powershell
$npcId  = 3
$apiKey = "d2f128cc34..."
$inWav  = "C:\Users\me\sample.wav"

curl.exe -H ("X-API-Key: {0}" -f $apiKey) `
  -F "session_id=dev1" `
  -F "lang=en" `
  -F ("file=@{0};type=audio/wav" -f (Resolve-Path $inWav).Path) `
  ("http://localhost:8000/npcs/{0}/reply" -f $npcId) `
  -o reply.json

$resp = Get-Content .\reply.json -Raw | ConvertFrom-Json
[IO.File]::WriteAllBytes("npc_reply.wav",[Convert]::FromBase64String($resp.audio_b64))
Start-Process .\npc_reply.wav
```

---

## Implementation Notes

- **Voice resolution:** NPC playback uses the stored per‑NPC voice at `/data/voices/{id}/voice.wav` if present; otherwise `voice_ref` under the mounted library (`/app/voices/<file>`). If neither exists, reply endpoints return **400**.
- **History window:** Replies are built with a compact slice of recent turns (configurable via `HIST_MAX_TURNS`) plus the system persona.
- **LLM options:** Controlled by env (`LLM_MODEL`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `CONTEXT_TOKENS`, `LLM_THREADS`). The server automatically falls back from `/api/chat` to `/api/generate` if needed.
- **Whisper backend:** faster‑whisper with CTranslate2. Compute type auto‑picked by entrypoint (`float16` on GPU, `int8` CPU by default).

