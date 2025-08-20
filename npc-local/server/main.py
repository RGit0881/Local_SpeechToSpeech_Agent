# server/main.py
import os, io, re, base64, tempfile, shutil, datetime
from typing import List, Dict, Optional, Tuple

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import numpy as np
import soundfile as sf
from faster_whisper import WhisperModel
from TTS.api import TTS
import requests
from slugify import slugify

# NEW: DB
from sqlalchemy.orm import Session
from db import init_db, SessionLocal, NPC, ChatSession, Message, new_api_key

KEEP_ALIVE = os.getenv("LLM_KEEP_ALIVE", "-1")  # keep model warm (-1 forever, "5m", etc)
# ── Config ──────────────────────────────────────────────────────────────────
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-oss:20b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

CTX = int(os.getenv("CONTEXT_TOKENS", "8192"))
LLM_TEMP     = float(os.getenv("LLM_TEMPERATURE", "0.7"))
LLM_THREADS  = int(os.getenv("LLM_THREADS", "0"))      # 0 = auto
LLM_MAXTOK   = int(os.getenv("LLM_MAX_TOKENS", "200")) # never 0

HIST_MAX_TURNS = int(os.getenv("HIST_MAX_TURNS", "10"))

WHISPER_SIZE = os.getenv("WHISPER_SIZE", "small")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")

TTS_LANGUAGE = os.getenv("TTS_LANGUAGE", "en")
TTS_GLOBAL_RATE = float(os.getenv("TTS_GLOBAL_RATE", "1.0"))

# VOICES: user-mountable library + per-NPC storage
VOICES_DIR = os.getenv("VOICES_DIR", os.path.join(os.path.dirname(__file__), "voices"))
VOICES_STORAGE = os.getenv("VOICES_STORAGE", "/data/voices")  # per-NPC saved voices

# ── Models (lazy/robust) ────────────────────────────────────────────────────
whisper = WhisperModel(WHISPER_SIZE, device="auto", compute_type=WHISPER_COMPUTE)
_tts = None

def get_tts():
    global _tts
    if _tts is None:
        os.environ.setdefault("COQUI_TOS_AGREED", "1")
        try:
            import torch
            use_gpu = torch.cuda.is_available()
        except Exception:
            use_gpu = False
        try:
            _tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", gpu=use_gpu)
        except Exception:
            base = os.getenv("TTS_HOME", "/root/.local/share/tts")
            broken = os.path.join(base, "tts", "tts_models--multilingual--multi-dataset--xtts_v2")
            shutil.rmtree(broken, ignore_errors=True)
            _tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", gpu=use_gpu)
    return _tts

# ── Sessions (in-mem; still used for quick chat), DB stores long-term ───────
sessions: Dict[str, List[Dict[str, str]]] = {}

def prune_history(hist: List[Dict[str,str]]) -> List[Dict[str,str]]:
    if not hist:
        return hist
    system = hist[0] if hist and hist[0].get("role") == "system" else None
    turns = [m for m in hist if m.get("role") != "system"]
    if HIST_MAX_TURNS > 0:
        turns = turns[-(HIST_MAX_TURNS * 2):]
    return ([system] + turns) if system else turns

# ── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(title="Local NPC Voice Server", version="3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)

# optional ultra-simple UI (Step 5 will drop a tiny index.html)
if os.path.isdir(os.path.join(os.path.dirname(__file__), "ui")):
    app.mount("/ui", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "ui"), html=True), name="ui")

# NEW: DB startup
@app.on_event("startup")
def _startup():
    init_db()

# ── Helpers ─────────────────────────────────────────────────────────────────
def stt_transcribe(audio_bytes: bytes, lang_hint: Optional[str]) -> str:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        tmp.write(audio_bytes); tmp.flush()
        segments, _ = whisper.transcribe(tmp.name, language=lang_hint, vad_filter=True, without_timestamps=True)
        return "".join(seg.text for seg in segments).strip()

def _messages_to_prompt(messages: List[Dict[str, str]]) -> str:
    """Simple ChatML-ish prompt as a fallback for /api/generate."""
    out = []
    for m in messages:
        role = m.get("role","user")
        content = m.get("content","")
        out.append(f"<|im_start|>{role}\n{content}\n<|im_end|>")
    out.append("<|im_start|>assistant\n")  # leave assistant open
    return "\n".join(out)

def ollama_chat(messages: List[Dict[str, str]]) -> str:
    # primary: /api/chat
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "num_ctx": CTX,
            "num_predict": max(8, LLM_MAXTOK),
            "temperature": LLM_TEMP,
            "num_thread": LLM_THREADS,
            "keep_alive": KEEP_ALIVE,
        }
    }
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=180)
        r.raise_for_status()
        data = r.json()
        text = (data.get("message") or {}).get("content") or data.get("response") or ""
        if text and text.strip():
            return text
    except Exception as e:
        print(f"[ollama_chat] /api/chat error: {e}")

    # fallback: /api/generate with a concatenated prompt (some models behave better)
    prompt = _messages_to_prompt(messages)
    gen_payload = {
        "model": LLM_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_ctx": CTX,
            "num_predict": max(8, LLM_MAXTOK),
            "temperature": LLM_TEMP,
            "num_thread": LLM_THREADS,
        }
    }
    try:
        r2 = requests.post(f"{OLLAMA_URL}/api/generate", json=gen_payload, timeout=180)
        r2.raise_for_status()
        data2 = r2.json()
        text2 = data2.get("response","")
        if text2 and text2.strip():
            return text2
    except Exception as e:
        print(f"[ollama_chat] /api/generate error: {e}")

    # last resort so TTS isn't silent
    return "Okay."


def ssml_to_parts(text_or_ssml: str) -> List[Tuple[str, float, int]]:
    text = text_or_ssml
    parts, current, rate_stack = [], [], [TTS_GLOBAL_RATE]
    tokens = re.split(r'(<break[^>]*>|<prosody[^>]*>|</prosody>)', text)
    def flush(p=0):
        if current:
            parts.append(("".join(current), rate_stack[-1], p)); current.clear()
    for tok in tokens:
        if tok.startswith("<break"):
            m = re.search(r'time="([^"]+)"', tok); ms = 0
            if m:
                val = m.group(1).lower()
                ms = int(float(val[:-2])) if val.endswith("ms") else (int(float(val[:-1])*1000) if val.endswith("s") else 0)
            flush(ms)
        elif tok.startswith("<prosody"):
            m = re.search(r'rate="([^"]+)"', tok)
            mapped = rate_stack[-1]
            if m:
                v = m.group(1).lower()
                mapped = {"x-slow":0.6,"slow":0.8,"medium":1.0,"fast":1.2,"x-fast":1.4}.get(v, mapped)
                if mapped == rate_stack[-1]:
                    try: mapped = float(v)
                    except: pass
            rate_stack.append(mapped)
        elif tok == "</prosody>":
            if len(rate_stack) > 1: rate_stack.pop()
        else:
            current.append(tok)
    flush()
    return parts

def resolve_voice_file_from_library(voice_ref: Optional[str]) -> Optional[str]:
    if not voice_ref: return None
    path = voice_ref if os.path.isabs(voice_ref) else os.path.join(VOICES_DIR, voice_ref)
    if not os.path.exists(path):
        raise HTTPException(400, f"Voice file not found: {path}")
    return path

def npc_saved_voice_path(npc_id: int) -> str:
    os.makedirs(os.path.join(VOICES_STORAGE, str(npc_id)), exist_ok=True)
    return os.path.join(VOICES_STORAGE, str(npc_id), "voice.wav")

def synthesize_ssml(text_or_ssml: str, speaker_wav: str, language: str="en") -> bytes:
    tts = get_tts()
    parts = ssml_to_parts(text_or_ssml)
    waves, sr = [], 24000
    for plain, rate, pause_ms in parts:
        if plain.strip():
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as fout:
                tts.tts_to_file(text=plain, file_path=fout.name, speaker_wav=speaker_wav, language=language, speed=rate)
                audio, sr = sf.read(fout.name, dtype="float32")
                waves.append(audio)
        if pause_ms > 0:
            waves.append(np.zeros(int((pause_ms/1000.0)*sr), dtype="float32"))
    if not waves:
        waves = [np.zeros(int(0.2*sr), dtype="float32")]
    audio = np.concatenate(waves)
    with io.BytesIO() as buf:
        sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
        return buf.getvalue()

def b64wav(wav_bytes: bytes) -> str:
    return base64.b64encode(wav_bytes).decode("ascii")

# NEW: DB helpers / deps
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def require_npc(db: Session, npc_id: int) -> NPC:
    npc = db.get(NPC, npc_id)
    if not npc: raise HTTPException(404, "NPC not found")
    return npc

def check_api_key(npc: NPC, x_api_key: Optional[str]):
    if npc.api_key and x_api_key != npc.api_key:
        raise HTTPException(401, "Invalid or missing API key")

def get_or_create_session(db: Session, npc: NPC, session_id: str) -> ChatSession:
    s = db.query(ChatSession).filter_by(npc_id=npc.id, session_id=session_id).first()
    if s: return s
    s = ChatSession(npc_id=npc.id, session_id=session_id)
    db.add(s); db.commit(); db.refresh(s)
    # ensure system message exists in persistent history
    db.add(Message(chat_session_id=s.id, role="system", content=npc.persona))
    db.commit()
    return s

# ── Schemas ─────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    session_id: str
    messages: List[Dict[str,str]]

class TTSRequest(BaseModel):
    text: str
    ssml: bool = True
    voice_ref: Optional[str] = None
    language: str = TTS_LANGUAGE

class PersonaRequest(BaseModel):
    session_id: str
    persona: str

class STTBase64Request(BaseModel):
    audio_b64: str
    lang: str = "en"

# ── Base routes kept ────────────────────────────────────────────────────────
@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/gpuz")
def gpuz():
    info = {"whisper_compute": os.getenv("WHISPER_COMPUTE", "int8")}
    try:
        import torch
        info.update({
            "torch_cuda": torch.cuda.is_available(),
            "torch_devices": torch.cuda.device_count() if torch.cuda.is_available() else 0,
            "torch_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        })
    except Exception as e:
        info["torch_error"] = str(e)
    return info

# Personas (legacy, session-scoped, in-memory)
@app.post("/persona")
def set_persona(req: PersonaRequest):
    s = sessions.setdefault(req.session_id, [])
    if s and s[0].get("role") == "system": s[0]["content"] = req.persona
    else: s.insert(0, {"role":"system", "content": req.persona})
    return {"ok": True}

@app.get("/persona")
def get_persona(session_id: str):
    s = sessions.get(session_id, [])
    sysmsg = s[0]["content"] if s and s[0].get("role") == "system" else None
    return {"session_id": session_id, "persona": sysmsg}

@app.post("/stt")
async def stt_endpoint(file: UploadFile = File(...), lang: str = Form(default="en")):
    audio_bytes = await file.read()
    return {"text": stt_transcribe(audio_bytes, lang_hint=lang)}

@app.post("/stt_json")
async def stt_json(req: STTBase64Request):
    return {"text": stt_transcribe(base64.b64decode(req.audio_b64), lang_hint=req.lang)}

@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    s = sessions.setdefault(req.session_id, [])
    s.extend(req.messages)
    s[:] = prune_history(s)
    reply = ollama_chat(s)
    s.append({"role":"assistant","content":reply})
    return {"reply": reply}

# ── NPC MANAGEMENT ──────────────────────────────────────────────────────────
@app.post("/npcs")
async def create_npc(
    name: str = Form(...),
    persona: str = Form(...),          # system prompt / roleplay
    tone: Optional[str] = Form(None),  # notes like "sarcastic, short replies"
    language: str = Form("en"),
    voice_ref: Optional[str] = Form(None),   # filename under /app/voices
    voice_wav: Optional[UploadFile] = File(None),  # uploaded voice sample
    issue_api_key: int = Form(0),
    db: Session = Depends(get_db)
):
    slug = slugify(name)
    if db.query(NPC).filter_by(slug=slug).first():
        raise HTTPException(400, "Name already used (slug exists). Pick another name.")
    npc = NPC(name=name, slug=slug, persona=persona, tone=tone, language=language)
    if issue_api_key: npc.api_key = new_api_key()

    # prefer uploaded voice; else store library reference
    if voice_wav is not None:
        os.makedirs(VOICES_STORAGE, exist_ok=True)
        db.add(npc); db.commit(); db.refresh(npc)
        out = npc_saved_voice_path(npc.id)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f: f.write(await voice_wav.read())
        npc.voice_path = out
    elif voice_ref:
        npc.voice_ref = voice_ref

    db.add(npc); db.commit(); db.refresh(npc)
    base = f"/npcs/{npc.id}"
    return {
        "id": npc.id, "name": npc.name, "slug": npc.slug, "language": npc.language, "tone": npc.tone,
        "api_key": npc.api_key, "voice_ref": npc.voice_ref, "voice_path": npc.voice_path,
        "persona_preview": npc.persona[:180],
        "endpoints": {
            "reply_json": f"{base}/reply",
            "reply_wav": f"{base}/reply.wav",
            "history": f"{base}/history?session_id=YOUR_SESSION_ID"
        }
    }

@app.get("/npcs")
def list_npcs(db: Session = Depends(get_db)):
    rows = db.query(NPC).order_by(NPC.created_at.desc()).all()
    return [{"id": r.id, "name": r.name, "slug": r.slug, "api_key": bool(r.api_key)} for r in rows]

@app.get("/npcs/{npc_id}")
def get_npc(npc_id: int, db: Session = Depends(get_db)):
    npc = require_npc(db, npc_id)
    return {
        "id": npc.id, "name": npc.name, "slug": npc.slug, "language": npc.language, "tone": npc.tone,
        "voice_ref": npc.voice_ref, "voice_path": npc.voice_path,
        "has_api_key": bool(npc.api_key), "persona": npc.persona
    }

@app.patch("/npcs/{npc_id}")
async def patch_npc(
    npc_id: int,
    name: Optional[str] = Form(None),
    persona: Optional[str] = Form(None),
    tone: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    voice_ref: Optional[str] = Form(None),
    voice_wav: Optional[UploadFile] = File(None),
    rotate_api_key: int = Form(0),
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")
):
    npc = require_npc(db, npc_id); check_api_key(npc, x_api_key)
    if name: npc.name, npc.slug = name, slugify(name)
    if persona is not None: npc.persona = persona
    if tone is not None: npc.tone = tone
    if language is not None: npc.language = language
    if rotate_api_key: npc.api_key = new_api_key()

    if voice_wav is not None:
        out = npc_saved_voice_path(npc.id)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f: f.write(await voice_wav.read())
        npc.voice_path = out
    elif voice_ref is not None:
        npc.voice_ref = voice_ref

    db.add(npc); db.commit(); db.refresh(npc)
    return {"ok": True, "api_key": npc.api_key}

# ── NPC chat/reply endpoints ────────────────────────────────────────────────
def build_messages_for_npc(npc: NPC, db: Session, session_id: str, user_text: str) -> List[Dict[str,str]]:
    chat = get_or_create_session(db, npc, session_id)
    db.add(Message(chat_session_id=chat.id, role="user", content=user_text)); db.commit()

    # last N*2 turns (we keep system outside the table here)
    q = db.query(Message).filter_by(chat_session_id=chat.id) \
         .order_by(Message.created_at.desc()).limit(HIST_MAX_TURNS*2)
    msgs = list(reversed(q.all()))

    system = npc.persona
    if npc.tone:
        system = f"{npc.persona}\n\nSpeak in a {npc.tone} tone."
    messages = [{"role":"system","content": system}]
    messages += [{"role":m.role, "content":m.content} for m in msgs if m.role in ("user","assistant")]
    return messages


def resolve_npc_voice(npc: NPC) -> str:
    # Prefer per-NPC saved voice; else refer to library reference
    if npc.voice_path and os.path.exists(npc.voice_path): return npc.voice_path
    if npc.voice_ref: return resolve_voice_file_from_library(npc.voice_ref)
    raise HTTPException(400, "This NPC has no voice configured. Upload a voice_wav or set voice_ref.")

@app.get("/npcs/{npc_id}/history")
def get_history(npc_id: int, session_id: str, db: Session = Depends(get_db)):
    npc = require_npc(db, npc_id)
    chat = get_or_create_session(db, npc, session_id)
    msgs = db.query(Message).filter_by(chat_session_id=chat.id).order_by(Message.created_at.asc()).all()
    return [{"role": m.role, "content": m.content, "at": m.created_at.isoformat()} for m in msgs]

@app.post("/npcs/{npc_id}/reply")
async def npc_reply_json(
    npc_id: int,
    session_id: str = Form(...),
    lang: str = Form("en"),
    file: UploadFile = File(...),
    persona_override: Optional[str] = Form(None),
    voice_ref: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")
):
    npc = require_npc(db, npc_id); check_api_key(npc, x_api_key)

    user_text = stt_transcribe(await file.read(), lang_hint=lang)
    # messages with persona/tone; override if given
    if persona_override:
        fake = NPC(id=npc.id, persona=persona_override, tone=npc.tone, language=npc.language,
                   voice_ref=npc.voice_ref, voice_path=npc.voice_path)
        messages = build_messages_for_npc(fake, db, session_id, user_text)
    else:
        messages = build_messages_for_npc(npc, db, session_id, user_text)

    assistant = ollama_chat(messages)
    chat = db.query(ChatSession).filter_by(npc_id=npc.id, session_id=session_id).first()
    db.add(Message(chat_session_id=chat.id, role="assistant", content=assistant)); db.commit()

    # voice resolution: per-call library override wins, else NPC saved voice/ref
    voice_path = resolve_voice_file_from_library(voice_ref) if voice_ref else resolve_npc_voice(npc)
    wav = synthesize_ssml(assistant, speaker_wav=voice_path, language=lang or npc.language)
    return {"transcript": user_text, "reply_text": assistant, "audio_b64": b64wav(wav)}

@app.post("/npcs/{npc_id}/reply.wav")
async def npc_reply_wav(
    npc_id: int,
    session_id: str = Form(...),
    lang: str = Form("en"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")
):
    npc = require_npc(db, npc_id); check_api_key(npc, x_api_key)

    user_text = stt_transcribe(await file.read(), lang_hint=lang)
    if not user_text.strip():
        user_text = "(silence)"
    messages = build_messages_for_npc(npc, db, session_id, user_text)
    assistant = ollama_chat(messages)
    chat = db.query(ChatSession).filter_by(npc_id=npc.id, session_id=session_id).first()
    db.add(Message(chat_session_id=chat.id, role="assistant", content=assistant)); db.commit()

    voice_path = resolve_npc_voice(npc)
    wav = synthesize_ssml(assistant, speaker_wav=voice_path, language=lang or npc.language)
    return StreamingResponse(io.BytesIO(wav), media_type="audio/wav")

@app.delete("/npcs/{npc_id}")
def delete_npc(
    npc_id: int,
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    npc = require_npc(db, npc_id)
    check_api_key(npc, x_api_key)

    # remove voice file/folder if present
    try:
        if npc.voice_path and os.path.exists(npc.voice_path):
            os.remove(npc.voice_path)
            # try removing the npc voice dir if empty
            try: os.rmdir(os.path.dirname(npc.voice_path))
            except: pass
    except: pass

    # delete chat history
    sessions = db.query(ChatSession).filter_by(npc_id=npc.id).all()
    for s in sessions:
        db.query(Message).filter_by(chat_session_id=s.id).delete(synchronize_session=False)
        db.delete(s)

    db.delete(npc)
    db.commit()
    return {"ok": True}
