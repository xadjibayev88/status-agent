"""Premium Reels uslubi (@h6yotiy): original fon (yorug'lik dog'lari + chang zarralari + film doni), matn boshidan ko'rinib,
aytilayotgan so'z oltin rangda yonadi, o'zbekcha ovoz (Edge TTS), birinchi kadrdan hook, oxirida izohga chaqiriq.

Muhim qoidalar (2026-11-18 tuzatish):
- Video davomiyligi FAQAT haqiqiy ovoz uzunligidan hisoblanadi (ovoz oxirigacha to'liq eshitiladi, kesilmaydi).
- So'z vaqtlari ovoz xizmati qaytargan chegaralardan (so'z yoki gap) belgilar bo'yicha interpolyatsiya qilinadi:
  chegaralar kam yoki umuman bo'lmasa ham ovoz o'chib ketmaydi, matn ovoz bilan sinxron qoladi.
- Matn birinchi kadrdan xira ko'rinib turadi (bo'sh kadr yo'q), muqova kadri matn to'liq ochilgan paytdan olinadi.
"""
from __future__ import annotations

import asyncio, json, math, os, random, re, subprocess, tempfile, time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE = Path(__file__).resolve().parent
W, H, FPS = 1080, 1920, 30
FONT_Q = BASE / "fonts" / "PlayfairDisplay-Variable.ttf"
FONT_UI = BASE / "fonts" / "Montserrat-Variable.ttf"
GOLD = (244, 205, 120)
WHITE = (255, 255, 255)
THEMES = [  # (asos, dog' 1, dog' 2, dog' 3)
    ((10, 12, 28), (70, 60, 160), (180, 90, 140), (40, 110, 170)),     # tungi binafsha
    ((22, 10, 12), (190, 80, 50), (230, 150, 70), (120, 30, 60)),       # quyosh botishi
    ((6, 18, 16), (30, 130, 110), (90, 170, 120), (20, 70, 110)),       # zumrad
    ((16, 8, 22), (130, 50, 150), (220, 110, 170), (60, 40, 130)),      # olxo'ri
    ((14, 12, 10), (150, 110, 50), (200, 160, 90), (90, 60, 40)),       # tilla ko'mir
]
HOOKS = ["Buni kimgadir yuboring", "Bu gap sizga kerak edi", "Oxirigacha o'qing", "Kimnidir eslatdimi?",
         "Saqlab qo'ying", "Yuragingizga yaqin bo'lsa"]
QUESTIONS = ["Kimga yuborgan bo'lardingiz?", "Rozimisiz? Izohda yozing", "Kimni eslatdi? Belgilang",
             "Sizda ham shunday bo'lganmi?"]

VOICE_LEAD = 0.5       # ovoz boshlanishidan oldingi tinchlik (hook ko'rinsin)
OUTRO = 3.6            # ovoz tugagach: muallif + savol + kanal
MIN_DUR, MAX_DUR = 14.0, 40.0
GHOST = 0.30           # hali aytilmagan so'zlar ko'rinishi (0..1)

COVER_S = 4.0          # render() oxirida yangilanadi: agent.py Instagram muqovasi uchun o'qiydi


def font(path: Path, size: int, weight: int):
    f = ImageFont.truetype(str(path), size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def lerp_col(a, b, k: float):
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


def ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def media_duration(path: Path) -> float:
    """Haqiqiy davomiylik: faylni oxirigacha dekodlab o'lchaymiz (mp3 sarlavhasi noaniq bo'lishi mumkin)."""
    r = subprocess.run([ffmpeg(), "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr or "")
    if not m:
        r = subprocess.run([ffmpeg(), "-i", str(path)], capture_output=True, text=True)
        m = re.findall(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr or "")
    if not m:
        return 0.0
    h, mi, s = m[-1]
    return int(h) * 3600 + int(mi) * 60 + float(s)


def has_stream(path: Path, kind: str) -> bool:
    r = subprocess.run([ffmpeg(), "-i", str(path)], capture_output=True, text=True)
    return f" {kind}:" in (r.stderr or "")


# ---------------- ovoz ----------------
def okina(text: str) -> str:
    """Edge ovozi o'/g' ni faqat o'zbekcha okina (U+02BB) bilan to'g'ri o'qiydi."""
    return re.sub(r"([oOgG])['\u2019\u2018\u02bc`]", "\\1\u02bb", text)


def ovoz(text: str, out: Path) -> dict | None:
    """Ovoz yaratadi. Qaytaradi: {"dur": haqiqiy soniya, "bounds": [(t0, t1, matn)]} yoki None.
    Chegaralar (WordBoundary/SentenceBoundary) bo'lmasa ham ovoz saqlanadi."""
    try:
        import edge_tts
    except ImportError:
        return None
    voices = [os.environ.get("TTS_VOICE", "uz-UZ-MadinaNeural")] * 2 + ["uz-UZ-SardorNeural"]
    rate = os.environ.get("TTS_RATE", "-8%")

    async def go(voice, boundary):
        com = edge_tts.Communicate(okina(text), voice, rate=rate, boundary=boundary)
        bounds, audio = [], bytearray()
        async for ch in com.stream():
            if ch["type"] == "audio":
                audio += ch["data"]
            elif ch["type"] in ("WordBoundary", "SentenceBoundary"):
                bounds.append((ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7, ch.get("text", "")))
        return bytes(audio), bounds

    for n, voice in enumerate(voices, 1):
        try:
            audio, bounds = asyncio.run(go(voice, "WordBoundary"))
            if len(audio) < 2000:
                raise RuntimeError("ovoz bo'sh qaytdi")
            out.write_bytes(audio)
            dur = media_duration(out)
            if dur < 0.8:
                raise RuntimeError(f"ovoz juda qisqa ({dur:.2f}s)")
            print(f"Ovoz tayyor: {dur:.2f}s, chegaralar: {len(bounds)} ({voice}, urinish {n})")
            return {"dur": dur, "bounds": bounds}
        except Exception as e:  # noqa: BLE001 — ovoz bo'lmasa ham video chiqsin
            print(f"Ovoz urinishi {n}/{len(voices)} muvaffaqiyatsiz: {type(e).__name__}: {e}")
            time.sleep(2 * n)
    return None


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", "", okina(s).lower())


def align(tokens: list[str], voice: dict) -> list[tuple[float, float]]:
    """Har bir so'z uchun (boshlanish, tugash) soniyasi — ovoz fayliga nisbatan.
    Chegaralar bo'yicha belgi-vaqt xaritasi tuziladi va so'zlar shu xaritadan olinadi."""
    dur = voice["dur"]
    lens = [max(1, len(_norm(t))) for t in tokens]
    starts, c = [], 0
    for L in lens:
        starts.append(c); c += L
    total_w = c

    segs = []  # (belgi_boshi, belgi_oxiri, t0, t1)
    cc = 0
    for t0, t1, txt in voice["bounds"]:
        L = len(_norm(txt))
        if L:
            segs.append((cc, cc + L, t0, max(t1, t0 + 0.05)))
            cc += L
    if not segs or cc < total_w * 0.5:   # chegaralar yetarli emas: butun ovozga tekis taqsimlaymiz
        lead = min(0.12, dur * 0.05)
        segs = [(0, total_w, lead, max(lead + 0.5, dur - 0.12))]
        cc = total_w
    scale = cc / total_w

    def time_of(pos: float) -> float:
        p = pos * scale
        for a, b, t0, t1 in segs:
            if p <= b:
                return t0 + (t1 - t0) * max(0.0, min(1.0, (p - a) / max(b - a, 1)))
        return segs[-1][3]

    res = []
    for i, L in enumerate(lens):
        t0, t1 = time_of(starts[i]), time_of(starts[i] + L)
        res.append((t0, max(t1, t0 + 0.18)))
    return res


# ---------------- fon ----------------
class Fon:
    def __init__(self, theme, seed):
        rng = random.Random(seed)
        self.base = Image.new("RGB", (W, H), theme[0])
        self.blobs = []
        for col in theme[1:]:
            core = rng.randint(260, 420)
            r = core * 2                                   # chekka bilan: xiralik kesilib qolmasin
            b = Image.new("RGBA", (r * 2, r * 2), col + (0,))
            ImageDraw.Draw(b).ellipse([r - core, r - core, r + core, r + core], fill=col + (200,))
            b = b.filter(ImageFilter.GaussianBlur(core * 0.55))
            self.blobs.append((b, rng.uniform(0, W), rng.uniform(200, H - 200), rng.uniform(0.05, 0.12), rng.uniform(0, 6.28), r))
        yy, xx = np.mgrid[0:H, 0:W]
        d = np.sqrt(((xx - W / 2) / (W * 0.75)) ** 2 + ((yy - H / 2) / (H * 0.62)) ** 2)
        self.vig = Image.fromarray((np.clip(d - 0.35, 0, 1) * 230).astype(np.uint8), "L")
        nrng = np.random.default_rng(seed)
        self.grain = [Image.fromarray(nrng.integers(0, 255, (H // 2, W // 2), dtype=np.uint8), "L").resize((W, H)) for _ in range(3)]
        # suzib yuruvchi yorug' zarralar (bokeh): sekin yuqoriga ko'tariladi
        glow = lerp_col(theme[2], (255, 255, 255), 0.55)
        self.dust = []
        for _ in range(18):
            rad = rng.randint(5, 16)
            s = Image.new("RGBA", (rad * 8, rad * 8), glow + (0,))
            ImageDraw.Draw(s).ellipse([rad * 3, rad * 3, rad * 5, rad * 5], fill=glow + (255,))
            s = s.filter(ImageFilter.GaussianBlur(rad * 0.7))
            self.dust.append((s, rng.uniform(0, W), rng.uniform(0, H), rng.uniform(14, 42), rng.uniform(0, 6.28),
                              rng.uniform(0.25, 0.7), rad * 4))

    def frame(self, t: float, f: int) -> Image.Image:
        im = self.base.copy()
        for b, x, y, sp, ph, r in self.blobs:
            px = x + math.sin(t * sp * 6 + ph) * 160 - r
            py = y + math.cos(t * sp * 5 + ph) * 220 - r
            im.paste(b, (int(px), int(py)), b)
        for s, x, y, speed, ph, op, half in self.dust:
            px = x + math.sin(t * 0.6 + ph) * 40
            py = (y - t * speed) % (H + 200) - 100
            tw = 0.55 + 0.45 * math.sin(t * 1.4 + ph)
            a = s.copy()
            a.putalpha(a.getchannel("A").point(lambda v, k=op * tw: int(v * k)))
            im.paste(a, (int(px - half), int(py - half)), a)
        im = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), im, self.vig)
        return Image.blend(im, Image.merge("RGB", [self.grain[f % 3]] * 3), 0.045)


# ---------------- matn joylashuvi ----------------
def layout(words: list[str], fq, maxw: int):
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    lines, cur = [], []
    for i, w in enumerate(words):
        test = " ".join(words[j] for j in cur + [i])
        if cur and d.textlength(test, font=fq) > maxw:
            lines.append(cur); cur = [i]
        else:
            cur.append(i)
    if cur:
        lines.append(cur)
    lh = int(fq.size * 1.28)
    widest_word = max((d.textlength(w, font=fq) for w in words), default=0)
    return lines, lh, widest_word


def place(words, lines, lh, fq):
    """Matn bloki Instagram interfeysi chetlariga tegmaydigan, yorliqdan pastda markazlangan joylashuv."""
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    block = len(lines) * lh
    y0 = max(470, int(H * 0.46 - block / 2))
    pos = {}
    for li, ln in enumerate(lines):
        lw = d.textlength(" ".join(words[i] for i in ln), font=fq)
        x = (W - lw) / 2
        for i in ln:
            pos[i] = (x, y0 + li * lh)
            x += d.textlength(words[i] + " ", font=fq)
    return pos, y0 + block


def render(q: dict, cfg: dict, seed: int | None = None) -> Path:
    global COVER_S
    seed = seed if seed is not None else int(os.environ.get("GITHUB_RUN_NUMBER", random.randint(1, 10_000)))
    rng = random.Random(seed)
    text = q["text"].replace("\n", " ").strip()
    author = (q.get("author") or "").strip()
    words = text.split()
    author_words = author.split() if author and len(author) < 40 else []
    tmp = Path(tempfile.mkdtemp())
    voice_file = tmp / "voice.mp3"

    spoken = text if text[-1] in ".!?…" else text + "."
    if author_words:
        spoken += " " + " ".join(author_words) + "."
    voice = ovoz(spoken, voice_file)

    tokens = words + author_words
    if voice:
        tm = align(tokens, voice)
        times = [VOICE_LEAD + a for a, _ in tm[:len(words)]]
        ends = [VOICE_LEAD + b for _, b in tm[:len(words)]]
        author_t = VOICE_LEAD + tm[len(words)][0] if author_words else None
        speech_end = VOICE_LEAD + voice["dur"]            # ovozning haqiqiy oxiri (muallif ham ichida)
        quote_end = ends[-1]
    else:
        times = [0.9 + i * 0.34 for i in range(len(words))]
        ends = [t + 0.34 for t in times]
        quote_end = ends[-1]
        author_t = quote_end + 0.3 if author_words else None
        speech_end = quote_end + 1.0
    dur = round(min(max(speech_end + OUTRO, MIN_DUR), MAX_DUR), 2)
    cta_t = speech_end + 0.3
    COVER_S = round(min(max(quote_end + 0.6, 2.5), dur - 2.0), 2)   # matn to'liq ko'ringan kadr

    # shrift: 5 qatordan oshmasin va eng uzun so'z ekranga sig'sin
    fq = None
    for size in (112, 104, 96, 88, 80, 72, 64, 56):
        fq = font(FONT_Q, size, 700)
        lines, lh, widest = layout(words, fq, W - 170)
        if len(lines) <= 5 and widest <= W - 120:
            break
    pos, bottom = place(words, lines, lh, fq)
    fhook, fsmall, fq2 = font(FONT_UI, 40, 600), font(FONT_UI, 36, 500), font(FONT_UI, 44, 700)

    theme = rng.choice(THEMES)
    fon = Fon(theme, seed)
    hook = rng.choice(HOOKS).upper()
    question = rng.choice(QUESTIONS)
    channel = cfg.get("kanal_nomi") or "@h6yotiy"

    out = BASE / "chiqish" / f"status_{seed}_{rng.randint(100, 999)}.mp4"
    out.parent.mkdir(exist_ok=True)
    silent = tmp / "v.mp4"
    ff = subprocess.Popen([ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                           "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", str(silent)],
                          stdin=subprocess.PIPE)
    total = int(dur * FPS)
    black = Image.new("RGB", (W, H), (0, 0, 0))
    for f in range(total):
        t = f / FPS
        im = fon.frame(t, f)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        # hook yorlig'i (birinchi kadrdan)
        ha = 0.7 + 0.3 * ease(t / 0.25) if t < 2.8 else max(0.0, 1 - (t - 2.8) / 0.5)
        if ha > 0:
            tw = d.textlength(hook, font=fhook)
            d.rounded_rectangle([(W - tw) / 2 - 34, 300, (W + tw) / 2 + 34, 372], radius=36, fill=(255, 255, 255, int(28 * ha)),
                                outline=GOLD + (int(200 * ha),), width=2)
            d.text((W / 2, 336), hook, font=fhook, fill=GOLD + (int(255 * ha),), anchor="mm")
        # so'zlar: boshidan xira ko'rinadi, aytilganda oq bo'ladi, aytilayotgan so'z oltin rangda yonib so'nadi
        intro = 0.85 + 0.15 * ease(t / 0.5)               # birinchi kadrdan ko'rinadi (bo'sh kadr yo'q)
        for i, w in enumerate(words):
            x, y = pos[i]
            reveal = ease((t - (times[i] - 0.08)) / 0.28)
            a = (GHOST + (1 - GHOST) * reveal) * intro
            gold = 0.0
            if t >= times[i]:
                gold = max(0.0, 1 - (t - times[i]) / max(ends[i] - times[i], 0.35)) if voice else (1.0 if t < ends[i] else 0.0)
            col = lerp_col(WHITE, GOLD, gold)
            yy = y + (1 - reveal) * 12
            d.text((x + 3, yy + 4), w, font=fq, fill=(0, 0, 0, int(120 * a)))
            d.text((x, yy), w, font=fq, fill=col + (int(255 * a),))
        # muallif
        if author:
            aa = ease((t - (author_t if author_t is not None else quote_end + 0.3)) / 0.5)
            if aa > 0:
                d.line([(W / 2 - 50, bottom + 40), (W / 2 + 50, bottom + 40)], fill=GOLD + (int(220 * aa),), width=3)
                d.text((W / 2, bottom + 90), author, font=fsmall, fill=(230, 230, 235, int(255 * aa)), anchor="mm")
        # yakun: savol va kanal (ovoz tugashi bilan)
        ea = ease((t - cta_t) / 0.5)
        if ea > 0:
            d.text((W / 2, H - 430), question, font=fq2, fill=(255, 255, 255, int(255 * ea)), anchor="mm")
            d.text((W / 2, H - 360), channel, font=fsmall, fill=GOLD + (int(255 * ea),), anchor="mm")
        im.paste(layer, (0, 0), layer)
        fade = max(0.0, (t - (dur - 0.6)) / 0.6)          # oxirida yumshoq so'nish
        if fade > 0:
            im = Image.blend(im, black, min(fade, 1.0))
        ff.stdin.write(im.tobytes())
    ff.stdin.close(); ff.wait()
    if ff.returncode != 0 or not silent.exists():
        raise RuntimeError("Video kadrlarini yozishda xato (ffmpeg)")

    music = pick_music()
    cmd = [ffmpeg(), "-v", "error", "-y", "-i", str(silent)]
    fl, n = [], 1
    if voice:
        cmd += ["-i", str(voice_file)]
        fl.append(f"[{n}:a]adelay={int(VOICE_LEAD * 1000)}|{int(VOICE_LEAD * 1000)},volume=1.6[vo]"); n += 1
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        if voice:   # ovoz paytida musiqa past, ovoz tugagach asta ko'tariladi
            vol = f"volume='if(lt(t,{speech_end:.2f}),0.15,0.15+0.2*min(1,(t-{speech_end:.2f})/1.2))':eval=frame"
        else:
            vol = "volume=0.5"
        fl.append(f"[{n}:a]atrim=duration={dur},{vol},afade=t=in:d=1,afade=t=out:st={dur - 1.8:.2f}:d=1.8[mu]"); n += 1
    if voice and music:
        fl.append("[vo][mu]amix=inputs=2:duration=longest:normalize=0,loudnorm=I=-14:TP=-1.5[a]")
    elif voice:
        fl.append("[vo]loudnorm=I=-14:TP=-1.5[a]")
    elif music:
        fl.append("[mu]loudnorm=I=-14:TP=-1.5[a]")
    if fl:
        cmd += ["-filter_complex", ";".join(fl), "-map", "0:v", "-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "copy", "-t", f"{dur}", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)

    got = media_duration(out)
    if abs(got - dur) > 1.0 or got < MIN_DUR - 1.0:
        raise RuntimeError(f"Video davomiyligi noto'g'ri: kutilgan {dur}s, chiqdi {got:.2f}s")
    if (voice or music) and not has_stream(out, "Audio"):
        raise RuntimeError("Videoda ovoz yo'q")
    print(f"Premium video: {out.name} ({got:.1f}s, ovoz={'ha' if voice else 'yoq'}, muqova={COVER_S}s, tema={THEMES.index(theme)})")
    return out


def pick_music():
    files = sorted(BASE.glob("music*.mp3")) + sorted((BASE / "musiqalar").glob("*.mp3"))
    return random.choice(files) if files else None


def caption(q: dict, cfg: dict) -> str:
    """Birinchi qator — hook, keyin iqtibos, savol va 4 ta aniq heshteg (spamga o'xshamasin)."""
    rng = random.Random(q["text"])
    first = rng.choice(["Bu gapni o'qib, kimni esladingiz? 👇", "Shu so'zlar bugun kimga kerak? 🤍",
                        "Rozimisiz yoki yo'q? Izohda yozing 👇", "Saqlab qo'ying — bir kun kerak bo'ladi 🔖"])
    s = first + "\n\n«" + q["text"].replace("\n", " ") + "»"
    if q.get("author"):
        s += f"\n— {q['author']}"
    s += "\n\nYoqqan bo'lsa, shu odamga yuboring 💌\n" + (cfg.get("kanal_nomi") or "@h6yotiy")
    s += "\n\n#hayotiy #statuslar #iqtiboslar #ozbekcha"
    return s[:2200]


if __name__ == "__main__":  # lokal sinov: python premium.py [matn raqami]
    import sys
    data = json.loads((BASE / "matnlar.json").read_text(encoding="utf-8"))
    q = data[int(sys.argv[1]) if len(sys.argv) > 1 else 0]
    print(render(q, {"kanal_nomi": "@h6yotiy"}, seed=7))
