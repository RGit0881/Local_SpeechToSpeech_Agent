import os, io, base64, tempfile, re
from typing import List, Dict, Optional
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel
from TTS.api import TTS
import requests

# ── Config ──────────────────────────────────────────────────────────────────
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-oss:20b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
CTX = int(os.getenv("CONTEXT_TOKENS", "8192"))  # safe default for laptops

WHISPER_SIZE = os.getenv("WHISPER_SIZE", "small")      # tiny/base/small/medium/large-v3
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8") # float16 on GPU, int8 on CPU

TTS_LANGUAGE = os.getenv("TTS_LANGUAGE", "en")
TTS_GLOBAL_RATE = float(os.getenv("TTS_GLOBAL_RATE", "1.0"))

# ── Model init (one-time) ───────────────────────────────────────────────────
# ── Model init (one-time) ───────────────────────────────────────────────────
whisper = WhisperModel(WHISPER_SIZE, device="auto", compute_type=WHISPER_COMPUTE)
_tts = None

def get_tts():
    """Lazy init TTS so startup never fails; retry if cache was partial."""
    global _tts
    if _tts is None:
        os.environ.setdefault("COQUI_TOS_AGREED", "1")
        try:
            _tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2")
        except Exception as e:
            # if cache was corrupted, wipe it and try once more
            base = os.getenv("TTS_HOME", "/root/.local/share/tts")
            broken = os.path.join(base, "tts", "tts_models--multilingual--multi-dataset--xtts_v2")
            try:
                import shutil
                shutil.rmtree(broken, ignore_errors=True)
            except Exception:
                pass
            _tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2")
    return _tts


# simple in-memory chat sessions
sessions: Dict[str, List[Dict[str, str]]] = {}

# ── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(title="Local NPC Voice Server", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)

# ── Helpers ─────────────────────────────────────────────────────────────────
def stt_transcribe(audio_bytes: bytes, lang_hint: Optional[str]) -> str:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        tmp.write(audio_bytes); tmp.flush()
        segments, info = whisper.transcribe(tmp.name, language=lang_hint)
        return "".join(seg.text for seg in segments).strip()

def ollama_chat(messages: List[Dict[str, str]]) -> str:
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"num_ctx": CTX}
    }
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=180)
    r.raise_for_status()
    data = r.json()
    return (data.get("message") or {}).get("content") or data.get("response") or ""

def ssml_to_parts(text_or_ssml: str):
    """
    SSML subset:
      - <break time="500ms|1s">
      - <prosody rate="0.8|1.2|slow|fast|x-slow|x-fast">
    Returns list of (text, rate, pause_ms)
    """
    text = text_or_ssml
    parts, current, rate_stack = [], [], [TTS_GLOBAL_RATE]
    tokens = re.split(r'(<break[^>]*>|<prosody[^>]*>|</prosody>)', text)

    def flush(pause_ms=0):
        if current:
            parts.append(("".join(current), rate_stack[-1], pause_ms))
            current.clear()

    for tok in tokens:
        if tok.startswith("<break"):
            m = re.search(r'time="([^"]+)"', tok)
            ms = 0
            if m:
                val = m.group(1).lower()
                if val.endswith("ms"): ms = int(float(val[:-2]))
                elif val.endswith("s"): ms = int(float(val[:-1]) * 1000)
            flush(ms)
        elif tok.startswith("<prosody"):
            m = re.search(r'rate="([^"]+)"', tok)
            if m:
                val = m.group(1).lower()
                mapped = rate_stack[-1]
                if val in {"x-slow","slow","medium","fast","x-fast"}:
                    mapped = {"x-slow":0.6,"slow":0.8,"medium":1.0,"fast":1.2,"x-fast":1.4}[val]
                else:
                    try: mapped = float(val)
                    except: pass
                rate_stack.append(mapped)
            else:
                rate_stack.append(rate_stack[-1])
        elif tok == "</prosody>":
            if len(rate_stack) > 1: rate_stack.pop()
        else:
            current.append(tok)
    flush()
    return parts

def synthesize_ssml(text_or_ssml: str, speaker_wav: Optional[str], language: str="en") -> bytes:
    tts = get_tts() 
    parts = ssml_to_parts(text_or_ssml)
    waves, sr = [], 24000
    for plain, rate, pause_ms in parts:
        if plain.strip():
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as fout:
                tts.tts_to_file(text=plain, file_path=fout.name,
                                speaker_wav=speaker_wav, language=language, speed=rate)
                audio, sr = sf.read(fout.name, dtype="float32")
                waves.append(audio)
        if pause_ms > 0:
            waves.append(np.zeros(int((pause_ms/1000.0)*sr), dtype="float32"))
    if not waves: waves = [np.zeros(int(0.2*sr), dtype="float32")]
    audio = np.concatenate(waves)
    with io.BytesIO() as buf:
        sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
        return buf.getvalue()

def b64wav(wav_bytes: bytes) -> str:
    return base64.b64encode(wav_bytes).decode("ascii")

# ── Schemas ─────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    session_id: str
    messages: List[Dict[str,str]]

class TTSRequest(BaseModel):
    text: str
    ssml: bool = True
    voice_ref: Optional[str] = None
    language: str = TTS_LANGUAGE

# ── Routes ──────────────────────────────────────────────────────────────────
@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.post("/stt")
async def stt_endpoint(file: UploadFile = File(...), lang: str = Form(default="en")):
    audio_bytes = await file.read()
    text = stt_transcribe(audio_bytes, lang_hint=lang)
    return {"text": text}

@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    s = sessions.setdefault(req.session_id, [])
    s.extend(req.messages)
    reply = ollama_chat(s)
    s.append({"role":"assistant","content":reply})
    return {"reply": reply}

@app.post("/tts")
async def tts_endpoint(payload: TTSRequest):
    voice_path = None
    if payload.voice_ref:
        voice_path = payload.voice_ref
        if not os.path.isabs(voice_path):
            voice_path = os.path.join(os.path.dirname(__file__), "voices", voice_path)
    wav = synthesize_ssml(payload.text, speaker_wav=voice_path, language=payload.language)
    return {"audio_b64": b64wav(wav)}

@app.post("/npc/reply")
async def npc_reply(session_id: str = Form(...), lang: str = Form("en"),
                    file: UploadFile = File(...), voice_ref: Optional[str] = Form(None)):
    audio_bytes = await file.read()
    user_text = stt_transcribe(audio_bytes, lang_hint=lang)

    hist = sessions.setdefault(session_id, [])
    if not hist or hist[0].get("role") != "system":
        hist.insert(0, {"role":"system",
                        "content":"You are an in-game NPC. Reply briefly, vividly, and in character."})
    hist.append({"role":"user","content":user_text})
    assistant = ollama_chat(hist)
    hist.append({"role":"assistant","content":assistant})

    voice_path = None
    if voice_ref:
        voice_path = voice_ref if os.path.isabs(voice_ref) \
                    else os.path.join(os.path.dirname(__file__), "voices", voice_ref)

    wav = synthesize_ssml(assistant, speaker_wav=voice_path, language=lang)
    return {"transcript": user_text, "reply_text": assistant, "audio_b64": b64wav(wav)}
