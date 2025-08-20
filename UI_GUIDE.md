# npc-local — UI Guide

The server ships a tiny web UI at **`/ui`** to help you **create**, **edit**, **delete** NPCs and copy their **endpoints** for testing.

> Base URL defaults to `http://localhost:8000`. If you change ports or run on another host, adjust the URLs accordingly.

---

## 1) Opening the UI

- Start containers:  
  `docker compose up -d`  
  or with GPU:  
  `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build`
- Visit: **http://localhost:8000/ui**

If you see an empty list, you haven’t created any NPCs yet.

---

## 2) Create an NPC

The **Create NPC** form includes:

- **Name** — Display name (unique by slug).
- **Language** — Default TTS language (e.g., `en`).
- **Tone** — Free‑form notes (e.g., `"sarcastic, terse"`).
- **Persona/System Prompt** — The *system* message that defines behavior/roleplay.
- **Voice sample (upload)** — A **WAV** file of the voice to clone (preferred).
- **…or library filename (voice_ref)** — A file name available under the mounted **/app/voices** folder.
- **Issue API key?** — If checked, server issues an **X‑API‑Key** for protected access.

Click **Create**. The **result JSON** includes:
- **`id`**, **`api_key`** (if generated)
- **`endpoints.reply_json`**, **`endpoints.reply_wav`**, **`endpoints.history`**
- **`voice_path`** (if uploaded) or **`voice_ref`**

> You must provide either an **uploaded voice WAV** or a **voice_ref**. XTTS v2 is multi‑speaker and needs a reference voice.

---

## 3) Manage NPCs

On the right side, the UI shows **Your NPCs** with actions:

- **Copy JSON / Copy WAV** — Copies `curl` commands to your clipboard (including `X-API-Key` if present).
- **Edit** — Opens an inline editor:
  - Change `name`, `persona`, `tone`, `language`
  - Upload a new **voice WAV** or switch **voice_ref**
  - **Rotate API key** (generates a new one)
- **Delete** — Permanently removes the NPC and its per‑NPC voice folder. If the NPC has an API key, deletion requires that key.

> Where files live: uploaded voices are stored under `/data/voices/{npc_id}/voice.wav` in the **`serverdata`** volume.

---

## 4) Testing From the UI

Under each NPC row the UI shows **Endpoints**. Examples you can paste into a terminal:

**Windows PowerShell (JSON response)**
```powershell
$apiKey = "PASTE_IF_PRESENT"
$npcId  = 3
$inWav  = "C:\path\to\sample.wav"
curl.exe -H ("X-API-Key: {0}" -f $apiKey) `
  -F "session_id=dev1" `
  -F "lang=en" `
  -F ("file=@{0};type=audio/wav" -f (Resolve-Path $inWav).Path) `
  ("http://localhost:8000/npcs/{0}/reply" -f $npcId) `
  -o reply.json
Get-Content .\reply.json -Raw | ConvertFrom-Json | Format-List
```

**Windows PowerShell (WAV stream)**
```powershell
curl.exe -H ("X-API-Key: {0}" -f $apiKey) `
  -F "session_id=dev1" `
  -F "lang=en" `
  -F ("file=@{0};type=audio/wav" -f (Resolve-Path $inWav).Path) `
  ("http://localhost:8000/npcs/{0}/reply.wav" -f $npcId) `
  -o npc_reply.wav
Start-Process .\npc_reply.wav
```

**macOS/Linux (JSON)**
```bash
NPC_ID=3 API_KEY=PASTE_IF_PRESENT IN_WAV=~/sample.wav
curl -H "X-API-Key: ${API_KEY}" \
  -F "session_id=dev1" \
  -F "lang=en" \
  -F "file=@${IN_WAV};type=audio/wav" \
  "http://localhost:8000/npcs/${NPC_ID}/reply" | jq .
```

**macOS/Linux (WAV)**
```bash
curl -H "X-API-Key: ${API_KEY}" \
  -F "session_id=dev1" \
  -F "lang=en" \
  -F "file=@${IN_WAV};type=audio/wav" \
  "http://localhost:8000/npcs/${NPC_ID}/reply.wav" -o npc_reply.wav
```

**History**
```bash
curl "http://localhost:8000/npcs/${NPC_ID}/history?session_id=dev1"
```

---

## 5) Troubleshooting in UI

- **401 Unauthorized** when deleting/editing: the NPC has an API key — paste it in the UI prompt.
- **400 This NPC has no voice configured**: upload a **voice WAV** or set a valid **voice_ref**.
- **Slow replies**: try a smaller LLM (e.g., `llama3.1:8b-instruct`), ensure GPU is enabled, or reduce `LLM_MAX_TOKENS`.
- **No audio / very short WAV**: inspect container logs (`docker compose logs -f server`) — TTS might have failed to load or voice file path is wrong.

---

## 6) Notes for Teams

- Everyone can run the stack **fully locally**. No cloud calls.
- Each teammate can create their own **NPCs** with different personas and voices.
- Use **distinct `session_id`s** per player instance to keep histories separate.
- If you mount a shared `./server/voices` library, all teammates can reference the same filenames via `voice_ref`.

Happy building!
