"""Persian voice-over for the demo (T-010): one WAV per narration block via Gemini TTS.

Reads the `> **N<n>** — ...` lines of docs/demo-script.fa.md (same parser as record_demo.py) and
writes out/demo/voice/N<n>.wav (24 kHz mono). `record_demo.py --assemble` then times each block
to its real audio length and mixes the voice into demo.mp4. Needs GEMINI_API_KEY in the environment, .env or ../liara/.env.

  ~/Work/liara/.venv/bin/python scripts/tts.py                          # all blocks (skips existing files)
  ~/Work/liara/.venv/bin/python scripts/tts.py --only N1 --voice Kore --out out/demo/samples/Kore --force
"""
from __future__ import annotations

import argparse, base64, io, os, re, sys, time, wave
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def narration() -> dict[str, str]:
    text = (ROOT / "docs/demo-script.fa.md").read_text()
    return {f"N{n}": t.strip() for n, t in re.findall(r"^> \*\*N(\d+)\*\* — (.+)$", text, re.M)}


def env_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    for env in (ROOT / ".env", ROOT.parent / "liara/.env"):  # the key lives with the Liara entry
        if not key and env.exists():
            m = re.search(r"^GEMINI_API_KEY=(.+)$", env.read_text(), re.M)
            key = m and m.group(1).strip().strip("'\"")
    if not key:
        sys.exit("GEMINI_API_KEY missing in .env")
    return key


# The Pro model follows this and doesn't read it aloud (gemini-3.8-flash-tts did); check() catches a slip.
STYLE = "با لحن آرام، گرم و صمیمی یک راوی فارسی‌زبان تهرانی، شمرده و طبیعی بخوان: "
SEED = 42  # without a fixed seed the same voice drifts between clips and sounds like two speakers
CHECK = ("Transcribe this audio verbatim in Persian script. Then on new lines write 'SPEAKERS: <n>' (distinct voices) "
         "and 'VOICE CHANGE: yes/no' (timbre changes mid-clip).")


def synth(c: httpx.Client, model: str, voice: str, text: str) -> bytes:
    body = {"contents": [{"parts": [{"text": STYLE + text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "seed": SEED, "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    for attempt in range(6):
        r = c.post(API.format(model=model), json=body)
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(60, 5 * 2 ** attempt))
            continue
        r.raise_for_status()
        part = r.json()["candidates"][0]["content"]["parts"][0]
        return pcm(base64.b64decode(part["inlineData"]["data"]))
    r.raise_for_status()
    raise RuntimeError(f"TTS failed: {r.status_code}")


def pcm(data: bytes) -> bytes:
    """s16le PCM, 24 kHz mono. Newer models wrap it in a WAV with a trailing C2PA chunk; treating that
    as samples put a click at the start and ~140 ms of loud noise at the end of every clip."""
    if data[:4] != b"RIFF":
        return data
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (24000, 1, 2), w.getparams()
        return w.readframes(w.getnframes())


def check(c: httpx.Client, f: Path) -> str | None:
    """Transcribe the clip; return a problem (style prompt spoken, second voice) or None."""
    data = base64.b64encode(f.read_bytes()).decode()
    r = c.post(API.format(model="gemini-3.8-flash"), json={"contents": [{"parts": [
        {"inlineData": {"mimeType": "audio/wav", "data": data}}, {"text": CHECK}]}]})
    r.raise_for_status()
    t = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    bad = [w for w in ("لحن", "راوی", "بخوان", "شمرده") if w in t]
    if bad or not re.search(r"SPEAKERS:\s*1\b", t) or re.search(r"VOICE CHANGE:\s*yes", t, re.I):
        return f"{' '.join(bad)} | {t.strip()}"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma-separated blocks, e.g. N1,N16")
    ap.add_argument("--voice", default="Charon")
    ap.add_argument("--model", default="gemini-2.5-pro-preview-tts")
    ap.add_argument("--out", default=str(ROOT / "out/demo/voice"))
    ap.add_argument("--force", action="store_true", help="regenerate existing files")
    a = ap.parse_args()
    texts = narration()
    ids = a.only.split(",") if a.only else list(texts)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=180, headers={"x-goog-api-key": env_key()}) as c:
        for n in ids:
            f = out / f"{n}.wav"
            if f.exists() and not a.force:
                continue
            audio = synth(c, a.model, a.voice, texts[n])
            with wave.open(str(f), "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000), w.writeframes(audio)
            print(f"{n}: {len(audio) / 48000:.1f} s  {f}", flush=True)
            if problem := check(c, f):
                print(f"  ⚠ {n}: {problem}", flush=True)


if __name__ == "__main__":
    main()
