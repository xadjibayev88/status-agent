#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Har bir mp3 uchun .srt (subtitr) yasaydi: [vokalni ajratish] + Whisper.
Allaqachon .srt bor qo'shiqlarga tegmaydi (qo'lda tuzatganingiz saqlanadi).
Qayta yasash uchun eski .srt ni o'chiring.

Muhit o'zgaruvchilari (GitHub workflow beradi):
  WHISPER_TIL    til kodi: uz, ru, en, tr ... (bo'sh = avtomatik)
  WHISPER_MODEL  large-v3 | medium | small
  VOKAL          1 = avval vokalni ajratish (aniqroq), 0 = o'chirish
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
EXTS = ("*.mp3", "*.m4a", "*.wav")


def log(msg):
    print(msg, flush=True)


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


# ---------- SRT yasash (Whisper'siz sinab ko'rsa bo'ladigan qism) ----------
def srt_vaqt(t):
    ms = max(0, int(round(t * 1000)))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def words_to_cues(words, max_chars=38, max_gap=0.8, max_dur=5.0):
    """words: [(boshlanish, tugash, so'z)] -> [(boshlanish, tugash, matn)]"""
    cues, cur = [], []

    def flush():
        if cur:
            text = " ".join(w[2] for w in cur).strip()
            if text:
                cues.append([cur[0][0], cur[-1][1], text])
            cur.clear()

    for w in words:
        if not w[2].strip():
            continue
        if cur:
            gap = w[0] - cur[-1][1]
            joined = " ".join(x[2] for x in cur + [w])
            if gap > max_gap or len(joined) > max_chars or (w[1] - cur[0][0]) > max_dur:
                flush()
        cur.append(w)
    flush()

    # Whisper ba'zan bir xil gapni takrorlab yuboradi: 3 martadan ko'pini tashlaymiz
    out = []
    for c in cues:
        if len(out) >= 3 and all(o[2] == c[2] for o in out[-3:]):
            continue
        out.append(c)
    # qator tugashi: oxirgi so'zdan biroz keyin, lekin keyingisiga tegmasdan
    for i, c in enumerate(out):
        end = c[1] + 0.25
        if i + 1 < len(out):
            end = min(end, out[i + 1][0] - 0.05)
        c[1] = max(end, c[0] + 0.3)
    return out


def srt_matn(cues):
    parts = []
    for i, (a, b, text) in enumerate(cues, 1):
        parts.append(f"{i}\n{srt_vaqt(a)} --> {srt_vaqt(b)}\n{text}\n")
    return "\n".join(parts)


# ---------- vokalni ajratish (ixtiyoriy) ----------
def vokal_ajrat(src, tmp):
    try:
        wav = tmp / "in.wav"
        subprocess.run([ffmpeg_exe(), "-y", "-v", "error", "-i", str(src),
                        "-ac", "2", "-ar", "44100", str(wav)], check=True)
        subprocess.run([sys.executable, "-m", "demucs", "--two-stems=vocals",
                        "-n", "htdemucs", "-d", "cpu", "-o", str(tmp / "sep"), str(wav)],
                       check=True)
        v = tmp / "sep" / "htdemucs" / "in" / "vocals.wav"
        if v.exists():
            log("  Vokal ajratildi")
            return v
    except Exception as e:
        log(f"  Vokal ajratilmadi, asl musiqa ishlatiladi ({e})")
    return None


# ---------- Whisper ----------
def transcribe(model, audio, til):
    segs, info = model.transcribe(
        str(audio), language=til or None, word_timestamps=True,
        vad_filter=True, beam_size=5, condition_on_previous_text=False)
    log(f"  Til: {info.language} (ishonch {info.language_probability:.2f})")
    words = []
    for sg in segs:
        if sg.no_speech_prob > 0.7 and sg.avg_logprob < -1.2:
            continue
        for w in (sg.words or []):
            words.append((w.start, w.end, w.word.strip()))
    return words


def main():
    til = os.environ.get("WHISPER_TIL", "").strip()
    model_name = os.environ.get("WHISPER_MODEL", "large-v3").strip() or "large-v3"
    vokal = os.environ.get("VOKAL", "1") == "1"

    songs = []
    for folder in (BASE, BASE / "musiqalar"):
        for e in EXTS:
            songs += [p for p in sorted(folder.glob(e)) if not p.with_suffix(".srt").exists()]
    if not songs:
        log("Yangi qo'shiq yo'q (hammasida .srt bor).")
        return
    log(f"{len(songs)} ta qo'shiq uchun subtitr yasaladi. Model: {model_name}, til: {til or 'avto'}")

    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device="cpu", compute_type="int8")

    for song in songs:
        log(f"\n>>> {song.name}")
        tmp = Path(tempfile.mkdtemp())
        try:
            audio = vokal_ajrat(song, tmp) if vokal else None
            words = transcribe(model, audio or song, til)
            cues = words_to_cues(words)
            if not cues:
                log("  Hech narsa topilmadi, o'tkazib yuborildi.")
                continue
            song.with_suffix(".srt").write_text(srt_matn(cues), encoding="utf-8")
            log(f"  ✅ {song.with_suffix('.srt').name}: {len(cues)} qator")
        except Exception as e:
            log(f"  ❌ Xato: {e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
