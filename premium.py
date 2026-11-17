"""Premium Reels uslubi (@h6yotiy): original fon (yorug'lik dog'lari + film doni), so'zma-so'z kinetik matn,
o'zbekcha ovoz (Edge TTS, so'z vaqtlari bilan sinxron), birinchi kadrdan hook, oxirida izohga chaqiriq.
Shablon va stock video ishlatilmaydi — har bir video o'zgacha ranglar va harakat bilan yasaladi."""
from __future__ import annotations

import asyncio, json, math, os, random, re, subprocess, tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE = Path(__file__).resolve().parent
W, H, FPS = 1080, 1920, 30
FONT_Q = BASE / "fonts" / "PlayfairDisplay-Variable.ttf"
FONT_UI = BASE / "fonts" / "Montserrat-Variable.ttf"
GOLD = (244, 205, 120)
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


# ---------------- ovoz ----------------
def okina(text: str) -> str:
    """Edge ovozi o'/g' ni faqat o'zbekcha okina (U+02BB) bilan to'g'ri o'qiydi."""
    return re.sub(r"([oOgG])['\u2019\u2018\u02bc`]", "\\1\u02bb", text)


def ovoz(text: str, out: Path) -> list[dict] | None:
    try:
        import edge_tts
    except ImportError:
        return None

    async def go():
        com = edge_tts.Communicate(okina(text), os.environ.get("TTS_VOICE", "uz-UZ-MadinaNeural"),
                                   rate=os.environ.get("TTS_RATE", "-8%"), boundary="WordBoundary")
        words, audio = [], bytearray()
        async for ch in com.stream():
            if ch["type"] == "audio":
                audio += ch["data"]
            elif ch["type"] == "WordBoundary":
                words.append({"t0": ch["offset"] / 1e7, "t1": (ch["offset"] + ch["duration"]) / 1e7})
        out.write_bytes(bytes(audio))
        return words
    try:
        words = asyncio.run(go())
        return words if words and out.stat().st_size > 2000 else None
    except Exception as e:  # noqa: BLE001 — ovoz bo'lmasa ham video chiqsin
        print(f"Ovoz yaratilmadi: {type(e).__name__}")
        return None


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

    def frame(self, t: float, f: int) -> Image.Image:
        im = self.base.copy()
        for b, x, y, sp, ph, r in self.blobs:
            px = x + math.sin(t * sp * 6 + ph) * 160 - r
            py = y + math.cos(t * sp * 5 + ph) * 220 - r
            im.paste(b, (int(px), int(py)), b)
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
    y0 = H // 2 - len(lines) * lh // 2 - 60
    pos = {}
    for li, ln in enumerate(lines):
        lw = d.textlength(" ".join(words[i] for i in ln), font=fq)
        x = (W - lw) / 2
        for i in ln:
            pos[i] = (x, y0 + li * lh)
            x += d.textlength(words[i] + " ", font=fq)
    return pos, y0 + len(lines) * lh


def render(q: dict, cfg: dict, seed: int | None = None) -> Path:
    seed = seed if seed is not None else int(os.environ.get("GITHUB_RUN_NUMBER", random.randint(1, 10_000)))
    rng = random.Random(seed)
    text = q["text"].replace("\n", " ").strip()
    author = (q.get("author") or "").strip()
    words = text.split()
    tmp = Path(tempfile.mkdtemp())
    voice = tmp / "voice.mp3"
    timings = ovoz(text + (f". {author}." if author and len(author) < 40 else ""), voice)
    if timings and len(timings) >= len(words):
        times = [w["t0"] + 0.35 for w in timings[:len(words)]]
        speech_end = timings[-1]["t1"] + 0.35
    else:
        timings = None
        times = [0.6 + i * 0.32 for i in range(len(words))]
        speech_end = times[-1] + 0.8
    dur = round(min(max(speech_end + 2.4, 7.0), 15.0), 2)

    size = 104 if len(text) <= 45 else 90 if len(text) <= 80 else 74
    fq, fhook, fsmall = font(FONT_Q, size, 700), font(FONT_UI, 40, 600), font(FONT_UI, 36, 500)
    pos, bottom = layout(words, fq, W - 170)
    theme = rng.choice(THEMES)
    fon = Fon(theme, seed)
    hook = rng.choice(HOOKS).upper()
    question = rng.choice(QUESTIONS)
    channel = cfg.get("kanal_nomi") or "@h6yotiy"
    # birinchi kadr bo'sh bo'lmasin: dastlabki 2 so'z darhol ko'rinadi
    first_visible = min(2, len(words))

    out = BASE / "chiqish" / f"status_{seed}_{rng.randint(100, 999)}.mp4"
    out.parent.mkdir(exist_ok=True)
    silent = tmp / "v.mp4"
    ff = subprocess.Popen([ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                           "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", str(silent)],
                          stdin=subprocess.PIPE)
    total = int(dur * FPS)
    for f in range(total):
        t = f / FPS
        im = fon.frame(t, f)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        # hook yorlig'i
        ha = 1.0 if t < 2.6 else max(0.0, 1 - (t - 2.6) / 0.5)
        if ha > 0:
            tw = d.textlength(hook, font=fhook)
            d.rounded_rectangle([(W - tw) / 2 - 34, 300, (W + tw) / 2 + 34, 372], radius=36, fill=(255, 255, 255, int(28 * ha)),
                                outline=GOLD + (int(200 * ha),), width=2)
            d.text((W / 2, 336), hook, font=fhook, fill=GOLD + (int(255 * ha),), anchor="mm")
        # so'zlar
        cur = max((i for i, tt in enumerate(times) if t >= tt), default=-1)
        for i, w in enumerate(words):
            start = -1.0 if i < first_visible else times[i] - 0.12
            a = ease((t - start) / 0.28)
            if a <= 0:
                continue
            x, y = pos[i]
            yy = y + (1 - a) * 26
            spoken = timings is not None and i == cur and t < speech_end
            col = GOLD if spoken else (255, 255, 255)
            d.text((x + 3, yy + 4), w, font=fq, fill=(0, 0, 0, int(110 * a)))
            d.text((x, yy), w, font=fq, fill=col + (int(255 * a),))
        # muallif
        if author:
            aa = ease((t - times[-1] - 0.4) / 0.5)
            if aa > 0:
                d.line([(W / 2 - 50, bottom + 40), (W / 2 + 50, bottom + 40)], fill=GOLD + (int(220 * aa),), width=3)
                d.text((W / 2, bottom + 90), author, font=fsmall, fill=(230, 230, 235, int(255 * aa)), anchor="mm")
        # yakun: kanal va savol
        ea = ease((t - (dur - 2.0)) / 0.5)
        if ea > 0:
            d.text((W / 2, H - 430), question, font=font(FONT_UI, 44, 700), fill=(255, 255, 255, int(255 * ea)), anchor="mm")
            d.text((W / 2, H - 360), channel, font=fsmall, fill=GOLD + (int(255 * ea),), anchor="mm")
        im.paste(layer, (0, 0), layer)
        ff.stdin.write(im.tobytes())
    ff.stdin.close(); ff.wait()

    music = pick_music()
    cmd = [ffmpeg(), "-v", "error", "-y", "-i", str(silent)]
    fl, n = [], 1
    if timings:
        cmd += ["-i", str(voice)]; fl.append(f"[{n}:a]adelay=350|350,volume=1.6[vo]"); n += 1
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        fl.append(f"[{n}:a]volume={0.16 if timings else 0.5},afade=t=in:d=1,afade=t=out:st={dur - 1.5:.2f}:d=1.5[mu]"); n += 1
    if timings and music:
        fl.append("[vo][mu]amix=inputs=2:duration=longest:normalize=0,loudnorm=I=-14:TP=-1.5[a]")
    elif timings:
        fl.append("[vo]loudnorm=I=-14:TP=-1.5[a]")
    elif music:
        fl.append("[mu]loudnorm=I=-14:TP=-1.5[a]")
    if fl:
        cmd += ["-filter_complex", ";".join(fl), "-map", "0:v", "-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "copy", "-t", f"{dur}", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    print(f"Premium video: {out.name} ({dur}s, ovoz={'ha' if timings else 'yoq'}, tema={THEMES.index(theme)})")
    return out


def pick_music():
    files = sorted(BASE.glob("music*.mp3")) + sorted((BASE / "musiqalar").glob("*.mp3"))
    return random.choice(files) if files else None


def ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


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


if __name__ == "__main__":  # lokal sinov: python premium.py
    import sys
    data = json.loads((BASE / "matnlar.json").read_text(encoding="utf-8"))
    q = data[int(sys.argv[1]) if len(sys.argv) > 1 else 0]
    print(render(q, {"kanal_nomi": "@h6yotiy"}, seed=7))
