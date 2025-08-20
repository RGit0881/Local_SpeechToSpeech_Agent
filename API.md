# npc-local — API Guide

Practical developer guide for using **npc-local** from scripts, apps, and game code. Pairs with **API_REFERENCE.md** (contract-level docs).

**Base URL (default):** `http://localhost:8000`  
**Auth:** Some NPC endpoints require `X-API-Key: <key>` (if created with an API key).  
**Content types:** JSON and `multipart/form-data` (for audio uploads).

---

## 0) Quick sanity checks

```bash
# server is up
curl http://localhost:8000/healthz

# GPU info (true/false does not block CPU mode)
curl http://localhost:8000/gpuz
```

Open the local UI at **http://localhost:8000/ui** to create/edit/delete NPCs and copy their endpoints/API keys.

---

## 1) Speech‑to‑Text (STT)

### 1.1 Multipart (WAV upload)
```bash
curl -X POST http://localhost:8000/stt \
  -F "file=@./sample.wav;type=audio/wav" \
  -F "lang=en"
```

**Response**
```json
{ "text": "hello how are you" }
```

### 1.2 JSON (base64 audio)
```bash
curl -X POST http://localhost:8000/stt_json \
  -H "Content-Type: application/json" \
  -d '{"audio_b64":"<BASE64-WAV>","lang":"en"}'
```

---

## 2) LLM Chat (stateless helper)

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "debug",
    "messages": [
      {"role":"user","content":"Say hi in one short sentence."}
    ]
  }'
```
**Response**
```json
{ "reply": "Hi there!" }
```

> NPC endpoints (below) are preferred for real usage because they store persona and history per session in the DB.

---

## 3) Text‑to‑Speech (TTS)

```bash
curl -X POST http://localhost:8000/tts \
  -H "Content-Type: application/json" \
  -d '{
    "text": "<prosody rate=\"0.9\">Hello there</prosody><break time=\"400ms\"/>traveler.",
    "ssml": true,
    "voice_ref": "hero.wav",
    "language": "en"
  }' | jq -r .audio_b64 | base64 --decode > out.wav
```

Supported SSML subset:
- `<break time="500ms|1s">`
- `<prosody rate="x-slow|slow|medium|fast|x-fast|1.2|0.9">`

> `voice_ref` must exist in the mounted voice library (host: `./server/voices`, container: `/app/voices`). NPC replies use the **per‑NPC** voice by default.

---

## 4) NPC Management (Create/List/Edit/Delete)

### 4.1 Create NPC
```bash
curl -X POST http://localhost:8000/npcs \
  -F "name=Arthur" \
  -F "language=en" \
  -F "tone=formal" \
  -F "persona=You are Arthur, a librarian with fading memories; be gentle and brief." \
  -F "voice_wav=@./server/voices/hero.wav;type=audio/wav" \
  -F "issue_api_key=1"
```
**Response (truncated)**
```json
{
  "id": 3,
  "name": "Arthur",
  "api_key": "d2f1...07bc",
  "voice_path": "/data/voices/3/voice.wav",
  "endpoints": {
    "reply_json": "/npcs/3/reply",
    "reply_wav": "/npcs/3/reply.wav",
    "history": "/npcs/3/history?session_id=YOUR_SESSION_ID"
  }
}
```

### 4.2 List NPCs
```bash
curl http://localhost:8000/npcs
```

### 4.3 Get NPC details
```bash
curl http://localhost:8000/npcs/3
```

### 4.4 Edit NPC (rename, persona, tone, language, rotate key, replace voice)
```bash
curl -X PATCH http://localhost:8000/npcs/3 \
  -H "X-API-Key: d2f1...07bc" \
  -F "persona=Stay calm; reply in very short lines." \
  -F "voice_wav=@./server/voices/hero.wav;type=audio/wav" \
  -F "rotate_api_key=1"
```

### 4.5 Delete NPC
```bash
curl -X DELETE http://localhost:8000/npcs/3 \
  -H "X-API-Key: d2f1...07bc"
```

---

## 5) NPC Conversation APIs

All NPC chat is **session‑scoped** and persisted. Use a stable `session_id` per player or party.

### 5.1 JSON reply (transcript + text + base64 WAV)
```bash
curl -X POST http://localhost:8000/npcs/3/reply \
  -H "X-API-Key: d2f1...07bc" \
  -F "session_id=dev1" \
  -F "lang=en" \
  -F "file=@./sample.wav;type=audio/wav" \
  -o reply.json

jq -r .audio_b64 reply.json | base64 --decode > npc_reply.wav
```

**Response**
```json
{
  "transcript": "hello how are you doing",
  "reply_text": "All right. What can I get you?",
  "audio_b64": "<BASE64-WAV>"
}
```

### 5.2 Direct WAV streaming
```bash
curl -X POST "http://localhost:8000/npcs/3/reply.wav" \
  -H "X-API-Key: d2f1...07bc" \
  -F "session_id=dev1" \
  -F "lang=en" \
  -F "file=@./sample.wav;type=audio/wav" \
  -o npc_reply.wav
```

### 5.3 History
```bash
curl "http://localhost:8000/npcs/3/history?session_id=dev1"
```

---

## 6) PowerShell examples (Windows)

```powershell
# Variables
$npcId = 3
$apiKey = "paste-api-key"
$inWav = "C:\Users\you\Downloads\sample.wav"

# JSON+audio route (saves reply.json)
curl.exe -H ("X-API-Key: {0}" -f $apiKey) `
  -F "session_id=dev1" `
  -F "lang=en" `
  -F ("file=@{0};type=audio/wav" -f (Resolve-Path $inWav).Path) `
  ("http://localhost:8000/npcs/{0}/reply" -f $npcId) `
  -o reply.json

$resp = Get-Content .\reply.json -Raw | ConvertFrom-Json
"Transcript: $($resp.transcript)"
"Reply     : $($resp.reply_text)"
[IO.File]::WriteAllBytes("npc_reply.wav",[Convert]::FromBase64String($resp.audio_b64))

# Direct WAV route
curl.exe -H ("X-API-Key: {0}" -f $apiKey) `
  -F "session_id=dev1" `
  -F "lang=en" `
  -F ("file=@{0};type=audio/wav" -f (Resolve-Path $inWav).Path) `
  ("http://localhost:8000/npcs/{0}/reply.wav" -f $npcId) `
  -o npc_reply.wav
```

> Use **`curl.exe`** explicitly in PowerShell to avoid aliasing to `Invoke-WebRequest`. Always pass a fully‑resolved path for file uploads.

---

## 7) Python (requests)

```python
import base64, requests

API = "http://localhost:8000"
NPC_ID = 3
API_KEY = "paste-key"

with open("sample.wav", "rb") as f:
    files = {"file": ("sample.wav", f, "audio/wav")}
    data = {"session_id":"dev1","lang":"en"}
    r = requests.post(f"{API}/npcs/{NPC_ID}/reply", headers={"X-API-Key": API_KEY}, files=files, data=data, timeout=120)
    r.raise_for_status()
    j = r.json()
    print("Transcript:", j["transcript"])
    print("Reply     :", j["reply_text"])
    with open("npc_reply.wav","wb") as out:
        out.write(base64.b64decode(j["audio_b64"]))
```

---

## 8) Node.js (fetch + form-data)

```js
import fs from "node:fs";
import fetch from "node-fetch";
import FormData from "form-data";

const API = "http://localhost:8000";
const NPC_ID = 3;
const API_KEY = "paste-key";

const form = new FormData();
form.append("session_id","dev1");
form.append("lang","en");
form.append("file", fs.createReadStream("./sample.wav"), { contentType: "audio/wav" });

const r = await fetch(`${API}/npcs/${NPC_ID}/reply`, {
  method: "POST",
  headers: { "X-API-Key": API_KEY },
  body: form
});

const j = await r.json();
console.log("Transcript:", j.transcript);
console.log("Reply     :", j.reply_text);
fs.writeFileSync("npc_reply.wav", Buffer.from(j.audio_b64, "base64"));
```

---

## 9) Unity (C#) — upload mic WAV and play NPC reply

> Works in Editor/Standalone. Uses `UnityWebRequest` to post a multipart form, writes the returned WAV bytes to a temp file, and then loads it as an `AudioClip`.

```csharp
using System.Collections;
using System.IO;
using UnityEngine;
using UnityEngine.Networking;

public class NpcVoiceClient : MonoBehaviour
{
    [Header("Server")]
    public string baseUrl = "http://localhost:8000";
    public int npcId = 3;
    public string apiKey = "paste-key";
    public string sessionId = "player1";

    [Header("Audio")]
    public AudioSource playbackSource;

    public IEnumerator SendWavAndPlay(byte[] wavBytes, string lang = "en")
    {
        WWWForm form = new WWWForm();
        form.AddField("session_id", sessionId);
        form.AddField("lang", lang);
        form.AddBinaryData("file", wavBytes, "input.wav", "audio/wav");

        using (UnityWebRequest req = UnityWebRequest.Post($"{baseUrl}/npcs/{npcId}/reply.wav", form))
        {
            req.SetRequestHeader("X-API-Key", apiKey);
            yield return req.SendWebRequest();

            if (req.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError($"NPC reply failed: {req.error}");
                yield break;
            }

            // Save WAV to a temp file so we can use UnityWebRequestMultimedia to decode
            string path = Path.Combine(Application.temporaryCachePath, "npc_reply.wav");
            File.WriteAllBytes(path, req.downloadHandler.data);

            using (UnityWebRequest getClip = UnityWebRequestMultimedia.GetAudioClip("file://" + path, AudioType.WAV))
            {
                yield return getClip.SendWebRequest();
                if (getClip.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogError($"Load clip failed: {getClip.error}");
                    yield break;
                }

                var clip = DownloadHandlerAudioClip.GetContent(getClip);
                playbackSource.clip = clip;
                playbackSource.Play();
            }
        }
    }
}
```

**Tip:** If you already have an in‑memory WAV (from Unity microphone), use a simple WAV encoder (there are permissive MIT utilities online) to produce bytes, then call `SendWavAndPlay(wavBytes)`.

---

## 10) Error handling

| HTTP | Meaning | Typical cause |
|---|---|---|
| 400 | Bad Request | Missing file, bad `voice_ref`, invalid params |
| 401 | Unauthorized | Missing/invalid `X-API-Key` for protected NPC |
| 404 | Not Found | NPC ID does not exist |
| 422 | Validation | Wrong content type or missing fields in form/JSON |
| 500 | Server error | Model init/XTTS/STT issues, check logs |

**Example error JSON**
```json
{"detail":"This NPC has no voice configured. Upload a voice_wav or set voice_ref."}
```

---

## 11) Performance notes

- Keep `LLM_MAX_TOKENS` moderate (80–150) for snappy replies.
- Use shorter personas and keep history bounded (`HIST_MAX_TURNS`).
- Prefer small/quantized LLM for laptops (`gpt-oss:20b` already quantized via Ollama).
- Whisper `small` is a good default; `large-v3` is slower but more accurate.
- XTTS v2 CPU works; GPU (if enabled) is faster.

---

## 12) Security reminders

- Treat API keys as secrets. The stack is intended for **local** use.
- If you expose beyond localhost, add TLS, reverse proxy, and stronger auth/rate limiting.

---

That’s it — see **API_REFERENCE.md** for the schema-level detail and **DEPLOYMENT.md** for runtime ops.
