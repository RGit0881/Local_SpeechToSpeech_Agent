# npc-local — Models, Performance & Licenses

This doc explains the **models** used in the pipeline, how to **swap/size** them, expected **performance**, and the **licenses** that apply.

```
Microphone (WAV)
   │
   ├──► STT — faster‑whisper (CTranslate2) → transcript
   │
   ├──► LLM — Ollama model (default: gpt-oss:20b) → reply text
   │
   └──► TTS — Coqui XTTS v2 (multi‑speaker cloning) → WAV
```

---

## 1) Speech‑to‑Text (STT)

**Default stack**
- **Engine:** [faster‑whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2 backend)
- **Model family:** OpenAI Whisper (tiny/base/small/medium/**large-v3**)
- **Env knobs**
  - `WHISPER_SIZE` — one of `tiny | base | small | medium | large-v3` (default: `small`)
  - `WHISPER_COMPUTE` — `int8` on CPU (default), `float16` on GPU
- **Characteristics**
  - Robust multilingual ASR, good accuracy from `small` upward.
  - `vad_filter=True` used to trim long silences.

**Performance guidance (rough)**
- CPU `small`: real‑time or 1–2× RT on modern laptops for short phrases.
- GPU `large-v3` w/ FP16: best accuracy; latency depends on VRAM and clip length.

**Licensing**
- Whisper models and code are **MIT‑licensed** (commercial use permitted).
- faster‑whisper is **MIT** as well.
- CTranslate2 runtime is permissively licensed (MIT).

---

## 2) Large Language Model (LLM)

**Default**
- **Runtime:** [Ollama](https://ollama.com/)
- **Model name:** `gpt-oss:20b` (loaded by the server via `OLLAMA_URL /api/chat`)
- **Env knobs**
  - `LLM_MODEL` — model tag to use (default `gpt-oss:20b`)
  - `CONTEXT_TOKENS` — prompt window (default `8192`)
  - `LLM_MAX_TOKENS` — max new tokens per reply (default `200`)
  - `LLM_TEMPERATURE` — creativity (default `0.7`)
  - `LLM_THREADS` — CPU threads (0 = auto)

> 🔁 **Swapping models**: Any chat-capable Ollama model will work
> (e.g., `llama3.1:8b-instruct`, `qwen2.5:14b-instruct`, etc.).
> Make sure to `ollama pull <model>` first, then set `LLM_MODEL` and restart the container.

**Performance guidance (rough)**
- 20B class models run **best on GPU** with ≥ 12–16 GB VRAM (quantized).
- On CPU, expect multi‑second latency per short reply.
- For snappier local iteration, try `8B–14B` instruct models.

**Licensing**
- **Code (Ollama)** is permissive, but **model weights** each have their own license.
- Always check: `ollama show <model>` → read the **license** and **modality/usage** notes.
- University / lab use **may** be fine; **commercial** redistribution may not. **You are responsible** for compliance.

---

## 3) Text‑to‑Speech (TTS)

**Default**
- **Engine:** [Coqui TTS](https://github.com/coqui-ai/TTS)
- **Model:** `tts_models/multilingual/multi-dataset/xtts_v2` (multi‑speaker, cross‑lingual cloning)
- **Env knobs**
  - `TTS_LANGUAGE` — default language (default `en`)
  - `TTS_GLOBAL_RATE` — global speed multiplier (default `1.0`)
- **SSML subset supported in server**
  - `<break time="500ms|1s">`
  - `<prosody rate="x-slow|slow|medium|fast|x-fast|1.2|0.8">`

**Voice reference is required**
- XTTS v2 is **multi‑speaker**; you **must** supply a voice sample:
  - Per‑NPC upload → stored at `/data/voices/{id}/voice.wav`.
  - Or library reference via `voice_ref` mapped under `/app/voices`.

**Performance guidance**
- CPU synthesis works but is slower; **GPU (CUDA)** speeds it up significantly.
- Sample rates are 24 kHz PCM; pipeline writes WAV (`PCM_16`).

**Licensing (important)**
- XTTS v2 weights are under **CPML** (Coqui Public Model License).
- **Non‑commercial use** allowed under CPML; **commercial use requires a paid license**.
- The container sets `COQUI_TOS_AGREED=1`; **you must ensure your use is compliant**.
- Review: https://coqui.ai/cpml.txt and contact Coqui for commercial licensing.

---

## 4) GPU vs CPU

- The server detects GPU at runtime. If not visible, it falls back to CPU:
  - STT switches to `int8` CTranslate2 compute.
  - TTS and LLM continue on CPU (slower).
- To enable GPU in Docker:
  1. Install **NVIDIA drivers**, **CUDA**, and **NVIDIA Container Toolkit**.
  2. Use the GPU override compose file:  
     `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build`
  3. Verify: `docker run --rm --gpus=all nvidia/cuda:12.5.0-base-ubuntu24.04 nvidia-smi`

---

## 5) Model Sizing & Tips

- **Whisper**: Start with `small` for speed, upgrade to `medium`/`large-v3` if accuracy is insufficient.
- **LLM**: Prefer `8B–14B` models during development. Raise to `20B+` when you’re satisfied with latency.
- **Quantization**: Ollama models are often quantized by default (e.g., `Q4_K_M`) to reduce VRAM need.
- **Threads**: If the CPU is oversubscribed, cap `LLM_THREADS` to `physical_cores` for stability.
- **Context**: Keep prompts short, use `HIST_MAX_TURNS` to limit chat memory (env in server).

---

## 6) Legal & Ethics Checklist

- ✅ **Consent for voice cloning**: Only use a speaker sample if you have **recorded it yourself** or have **explicit, written permission** from the owner. Some jurisdictions consider voice a biometric identifier.
- ✅ **Attribution**: If your lab requires it, cite Whisper, faster‑whisper, Coqui TTS, and the specific LLM.
- ✅ **Redistribution**: Do **not** redistribute proprietary weights. Point collaborators to pull from official sources.
- ✅ **University projects**: Non‑commercial **does not automatically** equal license compliance—read each model license carefully.
- ✅ **Data handling**: Audio files are stored locally under `/data/voices`. The server doesn’t exfiltrate data, but follow your IRB/IT policies.

---

## 7) Quick Switch Matrix

| Layer | Env var(s) | Common values | Notes |
|------:|------------|---------------|-------|
| STT | `WHISPER_SIZE`, `WHISPER_COMPUTE` | `small`, `medium`, `large-v3` / `int8`, `float16` | `float16` requires CUDA |
| LLM | `LLM_MODEL`, `CONTEXT_TOKENS`, `LLM_MAX_TOKENS`, `LLM_TEMPERATURE`, `LLM_THREADS` | `gpt-oss:20b`, `llama3.1:8b-instruct`, `qwen2.5:14b-instruct` | `ollama pull` first |
| TTS | `TTS_LANGUAGE`, `TTS_GLOBAL_RATE` | `en`, `es`, … / `0.8–1.4` | Provide `voice_wav` or `voice_ref` |

---

## 8) Credits

- **OpenAI Whisper** (MIT) — ASR models and tokenizer.
- **faster‑whisper** (MIT) — Efficient Whisper inference (CTranslate2).
- **Ollama** — Local model runtime with simple HTTP API.
- **Coqui TTS** — XTTS v2 multi‑speaker TTS.

