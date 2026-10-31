#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instagram status-video agenti.

  python agent.py          -> doimiy ishlaydi, jadval bo'yicha o'zi joylaydi
  python agent.py --test   -> bitta video yasaydi (chiqish/ papkada), joylamaydi
  python agent.py --now    -> bitta video yasab, darhol joylaydi
"""
import argparse
import base64
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

BASE = Path(__file__).resolve().parent
W, H = 1080, 1920
for _d in ("fonts", "fon_videolar", "musiqalar", "chiqish"):
    (BASE / _d).mkdir(exist_ok=True)

SERIF_SYS = [
    "C:/Windows/Fonts/georgia.ttf",
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
]
SANS_SYS = [
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# ---------- yordamchi: json, config, holat ----------
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def apply_env(cfg):
    """GitHub Secrets / muhit o'zgaruvchilari config.json dan ustun turadi."""
    for env, key in (("IG_ACCESS_TOKEN", "access_token"),
                     ("PEXELS_API_KEY", "pexels_api_key"),
                     ("PIXABAY_API_KEY", "pixabay_api_key"),
                     ("CLOUDINARY_URL", "cloudinary_url"),
                     ("VIDEO_REPO", "video_repo"),
                     ("VIDEO_REPO_TOKEN", "video_repo_token"),
                     ("KANAL_NOMI", "kanal_nomi")):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    return cfg


def load_cfg():
    p = BASE / "config.json"
    if not p.exists():
        p = BASE / "config.example.json"
    if not p.exists():
        sys.exit("config.json topilmadi.")
    return apply_env(load_json(p, {}))


def load_state():
    st = load_json(BASE / "holat.json", {})
    st.setdefault("ishlatilgan", [])
    st.setdefault("bajarilgan", [])
    st.setdefault("urinish", {})
    return st


def save_state(st):
    save_json(BASE / "holat.json", st)


# ---------- matn tanlash ----------
def tanla_matn(st):
    try:
        baza = load_json(BASE / "matnlar.json", [])
    except json.JSONDecodeError:
        # nusxa olishda boshidagi "[" yoki oxiridagi "]" tushib qolgan bo'lsa, tuzatamiz
        s = (BASE / "matnlar.json").read_text(encoding="utf-8").strip().rstrip(",")
        if not s.startswith("["):
            s = "[" + s
        if not s.endswith("]"):
            s = s.rstrip(",") + "]"
        baza = json.loads(s)
        log("matnlar.json biroz buzilgan edi, avtomatik tuzatildi")
    if not baza:
        sys.exit("matnlar.json bo'sh.")
    run = os.environ.get("GITHUB_RUN_NUMBER")
    if run:  # bulutda holat saqlanmaydi: aralashtirilgan tartibda ketma-ket olamiz
        order = list(range(len(baza)))
        random.Random(2026).shuffle(order)
        return baza[order[int(run) % len(baza)]]
    used = set(st["ishlatilgan"])
    yangi = [q for q in baza if q["text"] not in used]
    if not yangi:  # hammasi ishlatilgan bo'lsa, qaytadan boshlaymiz
        st["ishlatilgan"] = []
        yangi = baza
    return random.choice(yangi)


# ---------- shrift va matn rasmi ----------
def find_font(keywords, system_list):
    cands = []
    for ext in ("*.ttf", "*.otf"):
        cands += sorted((BASE / "fonts").glob(ext))
    for kw in keywords:
        for p in cands:
            if kw in p.name.lower():
                return str(p)
    for p in system_list:
        if os.path.exists(p):
            return p
    return str(cands[0]) if cands else None


def load_font(path, size):
    try:
        if path:
            return ImageFont.truetype(path, size)
        return ImageFont.load_default(size)
    except Exception:
        return ImageFont.load_default()


def wrap(draw, text, font, maxw):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for w in para.split():
            t = (cur + " " + w).strip()
            if draw.textlength(t, font=font) <= maxw:
                cur = t
            else:
                if cur:
                    lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def scrim_yasa(y0, y1, out, alpha=64, blur=150):
    """Faqat matn orqasida yumshoq qorayish: yorqin fonda ham o'qilsin, kadr esa yorqin qolsin."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle([0, max(0, y0), W, min(H, y1)], fill=(0, 0, 0, alpha))
    img.filter(ImageFilter.GaussianBlur(blur)).save(out)


def strip_yasa(text, font, fill, h, out):
    """Bitta qator uchun shaffof tasma (soya bilan). Matn tasma ichida pad dan boshlanadi."""
    pad = 14
    img = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    sh = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((W // 2 + 3, pad + 4), text, font=font,
                            fill=(0, 0, 0, 200), anchor="ma")
    sh = sh.filter(ImageFilter.GaussianBlur(6))
    img = Image.alpha_composite(img, sh)
    ImageDraw.Draw(img).text((W // 2, pad), text, font=font, fill=fill, anchor="ma")
    img.save(out)
    return pad


def katlamlar_yasa(q, cfg):
    """Har qator alohida paydo bo'ladi. Qaytaradi: [(png, y, boshlanish)], davomiylik."""
    qpath = find_font(["semibold", "cormorant", "playfair", "garamond"], SERIF_SYS)
    ipath = find_font(["italic"], SERIF_SYS) or qpath
    spath = find_font(["montserrat"], SANS_SYS)
    probe = ImageDraw.Draw(Image.new("RGBA", (W, H)))
    size = 88
    while True:
        font = load_font(qpath, size)
        lines = wrap(probe, q["text"], font, W - 220)
        if len(lines) <= 6 or size <= 48:
            break
        size -= 4
    lh = int(size * 1.22)
    author = q.get("author")
    mark_h = 110
    total = mark_h + len(lines) * lh + (110 if author else 0)
    y = int(H * 0.45 - total / 2)
    out = BASE / "chiqish"
    layers = []
    scrim_yasa(y - 220, y + total + 220, out / "_scrim.png", alpha=96, blur=160)
    layers.append((out / "_scrim.png", 0, 0.2, None, 0.8))

    def add(name, text, f, fill, yy, h, start):
        path = out / f"_{name}.png"
        pad = strip_yasa(text, f, fill, h, path)
        layers.append((path, yy - pad, start, None, 0.9))

    add("mark", "\u201c", load_font(qpath, 150), "#F5F0E69A", y - 25, 210, 0.6)
    t0 = 1.3
    for i, ln in enumerate(lines):
        add(f"l{i}", ln, font, "#F5F0E6", y + mark_h + i * lh, lh + 30, t0 + i * 1.0)
    t_end = t0 + len(lines) * 1.0
    yy = y + mark_h + len(lines) * lh
    last = t_end
    if author:
        rule = Image.new("RGBA", (W, 20), (0, 0, 0, 0))
        ImageDraw.Draw(rule).rectangle([W // 2 - 45, 8, W // 2 + 45, 10], fill="#D9D5CCB4")
        rp = out / "_rule.png"
        rule.save(rp)
        layers.append((rp, yy + 18, t_end + 0.2, None, 0.9))
        add("author", author, load_font(ipath, 46), "#E8D9B5", yy + 40, 80, t_end + 0.7)
        last = t_end + 0.7
    handle = cfg.get("kanal_nomi", "")
    if handle:
        add("handle", handle, load_font(spath, 30), "#FFFFFF9A", H - 360, 64, 2.0)
    dur = last + 0.9 + 6 + len(q["text"]) * 0.03 + random.uniform(0, 3)
    dur = round(max(10.0, min(30.0, dur)), 1)
    return layers, dur


# ---------- fon: Pexels (bepul) / o'zingizning videolar / gradient ----------
def gradient_fon(out):
    pal = [((20, 24, 40), (70, 50, 90)), ((15, 32, 39), (32, 58, 67)),
           ((38, 20, 30), (88, 50, 60)), ((12, 12, 20), (40, 44, 70))]
    a, b = random.choice(pal)
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for yy in range(H):
        t = yy / (H - 1)
        d.line([(0, yy), (W, yy)], fill=tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)))
    img.save(out)
    return out


BRIGHT_QUERIES = [
    "mountain landscape", "waterfall", "green forest sunlight", "tropical beach aerial",
    "blue lake mountains", "flower field", "sunrise mountains", "autumn forest",
    "river valley aerial", "snow mountains", "green meadow", "ocean waves beach",
    "cherry blossom", "golden sunset sea", "countryside aerial", "rice terraces",
    "canyon aerial", "lavender field", "island aerial", "jungle waterfall",
    "spring forest", "clouds mountains aerial", "palm trees beach", "summer field wind",
]


def mavzular(cfg):
    return cfg.get("fon_mavzu") or BRIGHT_QUERIES


def parlaqlik(path):
    """Videoning o'rtacha yorqinligi (0..255). Past bo'lsa, qorong'u deb o'tkazib yuboramiz."""
    out = BASE / "chiqish"
    try:
        subprocess.run([ffmpeg_exe(), "-y", "-v", "error", "-i", str(path), "-t", "8",
                        "-vf", "fps=0.4,scale=64:-1", str(out / "_b%d.png")], timeout=120)
    except Exception:
        return 255.0
    vals = []
    for i in range(1, 6):
        f = out / f"_b{i}.png"
        if f.exists():
            vals.append(ImageStat.Stat(Image.open(f).convert("L")).mean[0])
            f.unlink()
    return sum(vals) / len(vals) if vals else 255.0


def pexels_video(cfg, key, exclude=()):
    import requests
    q = random.choice(mavzular(cfg))
    r = requests.get("https://api.pexels.com/videos/search",
                     headers={"Authorization": key},
                     params={"query": q, "orientation": "portrait",
                             "size": "medium", "per_page": 20}, timeout=30)
    r.raise_for_status()
    vids = r.json().get("videos", [])
    random.shuffle(vids)
    for v in vids:
        if v.get("duration", 0) < 6 or f"pexels_{v['id']}.mp4" in exclude:
            continue
        files = [f for f in v.get("video_files", [])
                 if f.get("file_type") == "video/mp4"
                 and f.get("height", 0) >= f.get("width", 0)
                 and 700 <= f.get("width", 0) <= 1100]
        if not files:
            continue
        f = max(files, key=lambda x: x["width"])
        path = BASE / "fon_videolar" / f"pexels_{v['id']}.mp4"
        if not path.exists():
            with requests.get(f["link"], stream=True, timeout=120) as resp:
                resp.raise_for_status()
                with open(path, "wb") as fh:
                    for chunk in resp.iter_content(1 << 20):
                        fh.write(chunk)
        log(f"Fon video: Pexels '{q}' ({path.name})")
        return path
    return None


def pixabay_variant(h):
    """Eng mos o'lcham: kengligi 1280-2560, hajmi 40 MB gacha (4K og'ir, o'tkazib yuboramiz)."""
    best = None
    for k in ("large", "medium", "small"):
        f = (h.get("videos") or {}).get(k) or {}
        w_, size = f.get("width", 0), f.get("size", 0)
        if not f.get("url") or not (1280 <= w_ <= 2560) or (size and size > 40 * 1024 * 1024):
            continue
        if best is None or w_ > best.get("width", 0):
            best = f
    if best is None:  # mos kelmasa, mavjudlaridan eng kichigini olamiz
        for k in ("medium", "small", "tiny"):
            f = (h.get("videos") or {}).get(k) or {}
            if f.get("url"):
                return f
    return best


def pixabay_video(cfg, key, exclude=()):
    import requests
    q = random.choice(mavzular(cfg))
    r = requests.get("https://pixabay.com/api/videos/", timeout=30,
                     params={"key": key, "q": q, "category": "nature", "order": "popular",
                             "per_page": 50, "page": random.randint(1, 3),
                             "safesearch": "true", "min_width": 1280})
    r.raise_for_status()
    hits = [h for h in r.json().get("hits", []) if h.get("duration", 0) >= 6]
    random.shuffle(hits)
    # vertikal (portret) videolarni afzal ko'ramiz, bo'lmasa istalgani (markazdan kesiladi)
    def vert(h):
        f = pixabay_variant(h) or {}
        return 0 if f.get("height", 0) > f.get("width", 1) else 1
    hits.sort(key=vert)
    for h in hits:
        f = pixabay_variant(h)
        if not f or not f.get("url") or f"pixabay_{h['id']}.mp4" in exclude:
            continue
        path = BASE / "fon_videolar" / f"pixabay_{h['id']}.mp4"
        if not path.exists():
            with requests.get(f["url"], stream=True, timeout=180) as resp:
                resp.raise_for_status()
                with open(path, "wb") as fh:
                    for chunk in resp.iter_content(1 << 20):
                        fh.write(chunk)
        log(f"Fon video: Pixabay '{q}' ({path.name})")
        return path
    return None


def fon_tanla(cfg):
    min_yorqin = float(cfg.get("min_yorqinlik", 80))
    for nom, fn, kalit in (("Pexels", pexels_video, "pexels_api_key"),
                           ("Pixabay", pixabay_video, "pixabay_api_key")):
        key = (cfg.get(kalit) or "").strip()
        if not key:
            continue
        tried, last = set(), None
        for _ in range(5):
            try:
                p = fn(cfg, key, tried)
            except Exception as e:
                log(f"{nom} ishlamadi: {e}")
                break
            if not p:
                break
            tried.add(p.name)
            last = p
            y = parlaqlik(p)
            if y >= min_yorqin:
                log(f"Yorqinlik {y:.0f}: yaxshi")
                return p
            log(f"Yorqinlik {y:.0f}: qorong'u, boshqasini qidiramiz")
        if last:
            return last
    local = []
    for e in ("*.mp4", "*.mov", "*.webm"):
        local += list((BASE / "fon_videolar").glob(e))
    if local:
        return random.choice(local)
    log("Fon video yo'q, gradient fon ishlatiladi")
    return gradient_fon(BASE / "chiqish" / "_fon.png")


def musiqa_tanla():
    files = []
    for e in ("*.mp3", "*.m4a", "*.wav"):
        files += list((BASE / "musiqalar").glob(e)) + list(BASE.glob(e))
    return random.choice(files) if files else None


# ---------- video yasash (ffmpeg) ----------
def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def ambient_input(dur):
    """mp3 bo'lmasa: ffmpeg bilan sekin chalinadigan pianino-o'xshash arpedjio yasaydi."""
    chords = [(220.0, 261.63, 329.63, 440.0),     # La minor
              (174.61, 220.0, 261.63, 349.23),    # Fa major
              (196.0, 246.94, 293.66, 392.0),     # Sol major
              (146.83, 220.0, 293.66, 349.23)]    # Re minor
    notes = random.choice(chords)
    P, step = 3.6, 0.9
    parts = []
    for i, f in enumerate(notes):
        tt = f"mod(t+{P - i * step:.2f},{P})"
        parts.append(f"exp(-1.1*{tt})*(1-exp(-30*{tt}))*"
                     f"(sin(2*PI*{f}*t)+0.35*sin(2*PI*{2 * f}*t)+0.12*sin(2*PI*{3 * f}*t))*0.17")
    parts.append(f"0.05*sin(2*PI*{notes[0] / 2}*t)*(0.7+0.3*sin(2*PI*0.1*t))")
    return f"aevalsrc='{'+'.join(parts)}':s=44100:d={dur}"


def media_duration(path):
    try:
        r = subprocess.run([ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr)
        if m:
            return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    except Exception:
        pass
    return 0.0


def parse_srt(path):
    """SRT -> [(boshlanish, tugash, matn)] soniyalarda."""
    try:
        raw = Path(path).read_text(encoding="utf-8-sig", errors="ignore")
    except Exception:
        return []
    cues = []
    for block in re.split(r"\n\s*\n", raw.replace("\r\n", "\n")):
        m = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", block)
        if not m:
            continue
        g = list(map(int, m.groups()))
        a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        text_lines = block[m.end():].strip().split("\n")
        text = " ".join(t.strip() for t in text_lines if t.strip())
        text = re.sub(r"<[^>]+>", "", text)
        if text and b > a:
            cues.append((a, b, text))
    return sorted(cues)


def block_yasa(lines, font, fill, out):
    """Bir necha qatorli matn bloki (soya bilan). Qaytaradi: (pad, balandlik)."""
    pad = 14
    lh = int(font.size * 1.3) if hasattr(font, "size") else 56
    h = len(lines) * lh + pad * 2
    img = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    sh = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    for i, ln in enumerate(lines):
        sd.text((W // 2 + 2, pad + i * lh + 3), ln, font=font, fill=(0, 0, 0, 235), anchor="ma")
    sh = sh.filter(ImageFilter.GaussianBlur(5))
    img = Image.alpha_composite(img, sh)
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        d.text((W // 2, pad + i * lh), ln, font=font, fill=fill, anchor="ma")
    img.save(out)
    return pad, h


def blok_rasm(lines, font, fill, h):
    """Bir xil balandlikdagi shaffof matn bloki (yuqoridan tekislangan)."""
    pad = 14
    lh = int(getattr(font, "size", 44) * 1.3)
    img = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    sh = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    for i, ln in enumerate(lines):
        sd.text((W // 2 + 2, pad + i * lh + 3), ln, font=font, fill=(0, 0, 0, 235), anchor="ma")
    sh = sh.filter(ImageFilter.GaussianBlur(5))
    img = Image.alpha_composite(img, sh)
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        d.text((W // 2, pad + i * lh), ln, font=font, fill=fill, anchor="ma")
    return img, pad


def subtitr_trek(cues, start, dur, font, probe, out):
    """Hamma subtitrni BITTA shaffof video-oqimga yig'adi (concat ro'yxati). Tez ishlaydi."""
    lh = int(getattr(font, "size", 44) * 1.3)
    pad = 14
    hs = 3 * lh + 2 * pad
    blank = out / "_sb.png"
    Image.new("RGBA", (W, hs), (0, 0, 0, 0)).save(blank)
    items, t, n = [], 0.0, 0

    def add(png, d):
        if d > 0.001:
            items.append((png, d))

    fd = 0.07
    for a, b, text in cues:
        a2 = max(a - start, t)
        b2 = min(b - start, dur)
        if b2 - a2 < 0.3 or a2 >= dur:
            continue
        lines = wrap(probe, text, font, W - 200)[:3]
        img, _ = blok_rasm(lines, font, "#FFFFFFEB", hs)
        var = {}
        for name, mul in (("a", 0.35), ("b", 0.7), ("c", 1.0)):
            im = img.copy()
            im.putalpha(im.getchannel("A").point(lambda v, m=mul: int(v * m)))
            pth = out / f"_s{n}{name}.png"
            im.save(pth)
            var[name] = pth
        add(blank, a2 - t)
        add(var["a"], fd)
        add(var["b"], fd)
        hold = max(0.05, (b2 - a2) - 4 * fd)
        add(var["c"], hold)
        add(var["b"], fd)
        add(var["a"], fd)
        t = a2 + 4 * fd + hold
        n += 1
    add(blank, max(dur - t, 0) + 1.0)
    lst = out / "_subtitr.txt"
    with open(lst, "w", encoding="utf-8") as f:
        for pth, d in items:
            f.write(f"file '{pth.as_posix()}'\nduration {d:.3f}\n")
        f.write(f"file '{items[-1][0].as_posix()}'\n")
    return lst, pad, n


def musiqa_katlamlar(q, cfg, music):
    """Musiqa asosiy rolda. Qisqa qo'shiq: BUTUN qo'shiq. Uzun bo'lsa: gap tugaydigan joygacha.
    Qaytaradi: layers, davomiylik, musiqa boshlanishi, ovoz so'nish uzunligi."""
    md = media_duration(music)
    max_s = min(85.0, float(cfg.get("max_soniya", 60)))
    srt = music.with_suffix(".srt")
    cues = parse_srt(srt) if (cfg.get("subtitr", False) and srt.exists()) else []  # subtitr standart o'chiq
    start, tam = 0.0, False
    if md <= 0:
        dur = min(30.0, max_s)
    elif md <= max_s + 3:
        dur, tam = md, True                      # butun qo'shiq
    elif cues:
        cand = [c for c in cues if c[0] <= md - 20]
        c0 = random.choice(cand) if cand else cues[0]
        start = max(0.0, c0[0] - 1.0)
        ends = [c[1] for c in cues if start + 15 <= c[1] <= start + max_s]
        dur = (max(ends) - start + 0.6) if ends else min(max_s, md - start)
    else:
        start = random.uniform(0, md - max_s)
        dur = max_s
    dur = round(min(dur, 90.0), 1)
    log(f"Qo'shiq {md:.0f} soniya -> video {dur} soniya" + (" (butun qo'shiq)" if tam else ""))

    spath = find_font(["montserrat"], SANS_SYS)
    qpath = find_font(["semibold", "cormorant", "playfair", "garamond"], SERIF_SYS)
    probe = ImageDraw.Draw(Image.new("RGBA", (W, H)))
    out = BASE / "chiqish"
    layers = []
    y_sub = int(H * float(cfg.get("subtitr_y", 0.32)))

    nl = 3 if cues else 6
    scrim_yasa(y_sub - 220, y_sub + nl * 62 + 220, out / "_scrim.png")
    layers.append((out / "_scrim.png", 0, 0.2, None, 0.8))
    if not cues:  # subtitr yo'q: iqtibos qator-qator paydo bo'ladigan chiroyli ko'rinishda
        layers, _ = katlamlar_yasa(q, cfg)
        return layers, dur, start, (0.4 if tam else 1.5)
    if cues:
        font = load_font(spath, 44)
        lst, pad, n = subtitr_trek(cues, start, dur, font, probe, out)
        layers.append((lst, y_sub - pad, 0.0, None, 0.0))
        log(f"Subtitr: {srt.name} ({n} qator)")
    else:
        font = load_font(qpath, 50)
        lines = wrap(probe, q["text"], font, W - 220)[:5]
        if q.get("author"):
            lines = lines + ["— " + q["author"]]
        path = out / "_status.png"
        pad, _ = block_yasa(lines, font, "#F5F0E6EB", path)
        layers.append((path, y_sub - pad, 1.5, None, 1.5))
    handle = cfg.get("kanal_nomi", "")
    if handle:
        hp = out / "_handle.png"
        pad, _ = block_yasa([handle], load_font(spath, 32), "#FFFFFFB4", hp)
        layers.append((hp, H - 380 - pad, 2.0, None, 0.9))
    return layers, dur, start, (0.4 if tam else 1.5)


def video_yasa(q, cfg):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = BASE / "chiqish" / f"status_{ts}.mp4"
    music = musiqa_tanla()
    uslub = cfg.get("uslub", "musiqa")
    if uslub == "aralash":
        uslub = random.choice(["musiqa", "musiqa", "status"])
    mstart, fo = None, 2.0
    if music and uslub == "musiqa":
        layers, dur, mstart, fo = musiqa_katlamlar(q, cfg, music)
    else:
        layers, dur = katlamlar_yasa(q, cfg)
    bg = fon_tanla(cfg)
    ambient = (not music) and cfg.get("ambient_musiqa", True)
    is_video = bg.suffix.lower() in (".mp4", ".mov", ".webm")
    d = str(dur)

    cmd = [ffmpeg_exe(), "-y"]
    if is_video:
        cmd += ["-stream_loop", "-1", "-t", d, "-i", str(bg)]
    else:
        cmd += ["-framerate", "30", "-loop", "1", "-t", d, "-i", str(bg)]
    for path, *_ in layers:
        if str(path).endswith(".txt"):
            cmd += ["-f", "concat", "-safe", "0", "-i", str(path)]
        else:
            cmd += ["-framerate", "30", "-loop", "1", "-t", d, "-i", str(path)]
    ai = 1 + len(layers)
    if music:
        if mstart is not None:
            start = mstart
        else:
            md = media_duration(music)
            start = random.uniform(0, md - dur - 2) if md > dur + 4 else 0
        cmd += ["-stream_loop", "-1", "-ss", f"{start:.1f}", "-i", str(music)]
        log(f"Musiqa: {music.name} ({start:.0f}-soniyadan)")
    elif ambient:
        cmd += ["-f", "lavfi", "-i", ambient_input(dur + 1)]
        log("Musiqa: ichki yumshoq fon musiqasi")

    pan = (",scale=1166:2074,crop=1080:1920:x='(iw-ow)/2*(1+0.8*sin(t/9))':y='(ih-oh)/2*(1+0.8*cos(t/11))'"
           if is_video else "")
    zoom = "" if is_video else (",zoompan=z='min(1+0.0006*on,1.25)':x='iw/2-(iw/zoom/2)'"
                                ":y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30")
    f = ["[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,"
         "eq=saturation=1.06:contrast=1.05:brightness=-0.02" + zoom + pan + ",vignette=PI/4.6,setsar=1[v0]"]
    for i, (pth, y, st, en, fin) in enumerate(layers, 1):
        if str(pth).endswith(".txt"):
            f.append(f"[{i}:v]fps=30,format=rgba[s{i}]")
        else:
            fx = f"fade=t=in:st={st:.2f}:d={fin:.2f}:alpha=1"
            if en:
                fe = min(0.3, (en - st) / 3)
                fx += f",fade=t=out:st={en - fe:.2f}:d={fe:.2f}:alpha=1"
            f.append(f"[{i}:v]fps=30,format=rgba,{fx}[s{i}]")
        f.append(f"[v{i - 1}][s{i}]overlay=0:{y}:format=auto[v{i}]")
    f.append(f"[v{len(layers)}]fade=t=out:st={dur - 1.2:.2f}:d=1.2,format=yuv420p[v]")
    cmd += ["-filter_complex", ";".join(f), "-map", "[v]"]
    if music or ambient:
        af = f"afade=t=in:d=1.0,afade=t=out:st={max(dur - fo, 0):.1f}:d={fo}"
        if ambient:
            af = "lowpass=f=3500,aecho=0.8:0.85:700|1100:0.4|0.3," + af
        cmd += ["-map", f"{ai}:a", "-af", af, "-ac", "2"]
    cmd += ["-t", d, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]
    if music or ambient:
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    cmd += ["-movflags", "+faststart", str(out)]

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg xatosi:\n" + "\n".join(r.stderr.splitlines()[-12:]))
    log(f"Video tayyor: {out.name} ({dur} soniya)")
    return out


def caption_yasa(q, cfg):
    s = q["text"].replace("\n", " ")
    if q.get("author"):
        s += f"\n\n— {q['author']}"
    chaqiriq = cfg.get("chaqiriqlar") or [
        "💌 Bu statusni kimga yuborgan bo'lardingiz?",
        "🔖 Saqlab qo'ying, kerak bo'lib qoladi",
        "✨ Har kuni yangi statuslar — obuna bo'lib qoling",
        "💬 Rozimisiz? Izohda yozing",
        "🤍 Yoqqan bo'lsa, do'stingizga yuboring",
        "📌 Shu so'zlar kimga kerak — belgilab qo'ying",
    ]
    s += "\n\n" + random.choice(chaqiriq)
    if cfg.get("kanal_nomi"):
        s += f"\n{cfg['kanal_nomi']}"
    tags = cfg.get("hashtaglar", [])
    if tags:
        s += "\n\n" + " ".join(random.sample(tags, min(8, len(tags))))
    return s[:2200]


# ---------- Instagram ----------
def _check(r):
    if not r.ok:
        raise RuntimeError(f"Instagram API xatosi {r.status_code}: {r.text[:500]}")
    return r


def token_yangila(cfg, st, force=False):
    """Uzoq muddatli token 60 kun yashaydi; haftada bir yangilab turamiz."""
    import requests
    last = st.get("token_yangilangan", 0)
    if not force and time.time() - last < 7 * 86400:
        return
    try:
        host = cfg.get("graph_host", "graph.instagram.com")
        r = requests.get(f"https://{host}/refresh_access_token",
                         params={"grant_type": "ig_refresh_token",
                                 "access_token": cfg["access_token"]}, timeout=30)
        if r.ok and r.json().get("access_token"):
            cfg["access_token"] = r.json()["access_token"]
            save_json(BASE / "config.json", cfg)
            st["token_yangilangan"] = time.time()
            save_state(st)
            log("Token yangilandi")
        else:
            log(f"Token yangilanmadi: {r.text[:200]}")
    except Exception as e:
        log(f"Token yangilashda xato: {e}")


# ---- Cloudinary: Instagram video_url ni oladi, shuning uchun vaqtincha ochiq havola kerak ----
def cloud_parse(cfg):
    url = (cfg.get("cloudinary_url") or "").strip().strip("\"'")
    url = re.sub(r"^CLOUDINARY_URL\s*=\s*", "", url)
    m = re.match(r"cloudinary://([^:]+):([^@]+)@(.+)$", url)
    return (m.group(1), m.group(2), m.group(3)) if m else None


def cloud_sign(params, secret):
    s = "&".join(f"{k}={params[k]}" for k in sorted(params) if params[k] not in (None, ""))
    return hashlib.sha1((s + secret).encode()).hexdigest()


def cloud_yukla(cfg, video):
    import requests
    c = cloud_parse(cfg)
    if not c:
        raise RuntimeError("CLOUDINARY_URL yo'q yoki noto'g'ri (cloudinary://KALIT:SIR@NOM ko'rinishida bo'lishi kerak)")
    key, secret, cloud = c
    params = {"folder": "status", "timestamp": int(time.time())}
    sig = cloud_sign(params, secret)
    with open(video, "rb") as f:
        r = requests.post(f"https://api.cloudinary.com/v1_1/{cloud}/video/upload",
                          data={**params, "api_key": key, "signature": sig},
                          files={"file": f}, timeout=600)
    if not r.ok:
        raise RuntimeError(f"Cloudinary xatosi {r.status_code}: {r.text[:300]}")
    j = r.json()
    return j["secure_url"], j["public_id"]


def cloud_ochir(cfg, public_id):
    """Joylangandan keyin vaqtinchalik faylni o'chiramiz (xato bo'lsa ham jim o'tamiz)."""
    try:
        import requests
        key, secret, cloud = cloud_parse(cfg)
        params = {"public_id": public_id, "timestamp": int(time.time())}
        requests.post(f"https://api.cloudinary.com/v1_1/{cloud}/video/destroy", timeout=60,
                      data={**params, "api_key": key, "signature": cloud_sign(params, secret)})
    except Exception as e:
        log(f"Cloudinary faylini o'chirib bo'lmadi: {e}")


# ---- GitHub (ochiq repozitoriy + jsDelivr): vaqtincha ochiq havola ----
def github_yukla(cfg, video):
    import requests
    repo, tok = cfg["video_repo"].strip(), cfg["video_repo_token"].strip()
    path = f"v/{datetime.now():%Y%m%d_%H%M%S}.mp4"
    api = f"https://api.github.com/repos/{repo}/contents/{path}"
    hdr = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    with open(video, "rb") as f:
        raw = f.read()
    r = requests.put(api, headers=hdr, timeout=600, json={
        "message": "vaqtincha video", "content": base64.b64encode(raw).decode()})
    if not r.ok:
        raise RuntimeError(f"GitHub xatosi {r.status_code}: {r.text[:300]}")
    j = r.json()
    sha, fsha = j["commit"]["sha"], j["content"]["sha"]
    if len(raw) <= 19 * 1024 * 1024:
        url = f"https://cdn.jsdelivr.net/gh/{repo}@{sha}/{path}"
    else:  # jsDelivr 20 MB dan katta fayllarni bermaydi
        url = f"https://raw.githubusercontent.com/{repo}/{sha}/{path}"
    for _ in range(30):  # havola ochilguncha kutamiz
        try:
            g = requests.get(url, headers={"Range": "bytes=0-1"}, timeout=30)
            if g.status_code in (200, 206):
                break
        except Exception:
            pass
        time.sleep(4)
    else:
        raise RuntimeError(f"Havola ochilmadi: {url}")
    return url, ("github", repo, path, fsha)


def github_ochir(cfg, info):
    try:
        import requests
        _, repo, path, fsha = info
        requests.delete(f"https://api.github.com/repos/{repo}/contents/{path}", timeout=60,
                        headers={"Authorization": f"Bearer {cfg['video_repo_token'].strip()}",
                                 "Accept": "application/vnd.github+json"},
                        json={"message": "video o'chirildi", "sha": fsha})
    except Exception as e:
        log(f"GitHub faylini o'chirib bo'lmadi: {e}")


def video_yukla(cfg, video):
    """Instagram video_url so'raydi: vaqtincha ochiq havola yasaydi. Qaytaradi: (url, tozalash)."""
    if cloud_parse(cfg):
        url, pid = cloud_yukla(cfg, video)
        return url, (lambda: cloud_ochir(cfg, pid))
    if cfg.get("video_repo") and cfg.get("video_repo_token"):
        url, info = github_yukla(cfg, video)
        return url, (lambda: github_ochir(cfg, info))
    raise RuntimeError("Vaqtincha havola uchun VIDEO_REPO va VIDEO_REPO_TOKEN (yoki CLOUDINARY_URL) kerak")


def ig_joyla(cfg, video, caption):
    import requests
    host = cfg.get("graph_host", "graph.instagram.com")
    ver = cfg.get("api_version", "v23.0")
    hdr = {"Authorization": f"Bearer {cfg['access_token']}"}

    def joyla(data):
        r = _check(requests.post(f"https://{host}/{ver}/me/media", headers=hdr,
                                 timeout=60, data=data))
        cid = r.json()["id"]
        for _ in range(72):
            s = requests.get(f"https://{host}/{ver}/{cid}", headers=hdr, timeout=30,
                             params={"fields": "status_code,status"}).json()
            code = s.get("status_code")
            if code == "FINISHED":
                break
            if code in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"Instagram videoni qabul qilmadi: {s}")
            time.sleep(5)
        else:
            raise TimeoutError("Instagram videoni vaqtida qayta ishlamadi")
        r = _check(requests.post(f"https://{host}/{ver}/me/media_publish", headers=hdr,
                                 data={"creation_id": cid}, timeout=60))
        return r.json()

    url, tozala = video_yukla(cfg, video)
    log("Video vaqtincha internetga yuklandi")
    try:
        res = joyla({"media_type": "REELS", "video_url": url,
                     "caption": caption, "share_to_feed": "true"})
        log(f"✅ Reels joylandi: {res}")
        if story_kerakmi(cfg):
            if media_duration(video) > 60:
                log("Story o'tkazib yuborildi: video 60 soniyadan uzun (Instagram story chegarasi)")
            else:
                try:
                    res = joyla({"media_type": "STORIES", "video_url": url})
                    log(f"✅ Story joylandi: {res}")
                except Exception as e:  # story xatosi Reels'ni buzmasin
                    log(f"Story joylanmadi: {e}")
    finally:
        tozala()


def story_kerakmi(cfg):
    """Kuniga 9 ta joylashdan ~6 tasi story'ga ham chiqadi (story_ulushi: 3 tadan 2 tasi)."""
    if cfg.get("story", True) is False:
        log("Story o'chirilgan (config: story=false)")
        return False
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        return True  # qo'lda ishga tushirganda har doim story ham joylanadi
    har, nechta = cfg.get("story_ulushi", [2, 3])
    n = os.environ.get("GITHUB_RUN_NUMBER")
    ha = int(n) % nechta < har if (n and n.isdigit()) else random.random() < har / nechta
    if not ha:
        log(f"Bu safar story navbati emas (har {nechta} ta Reels'dan {har} tasi story'ga chiqadi)")
    return ha


# ---------- asosiy oqim ----------
def bitta_status(cfg, st, joylash):
    if joylash and not (cloud_parse(cfg) or (cfg.get("video_repo") and cfg.get("video_repo_token"))):
        raise RuntimeError("Secrets'da VIDEO_REPO_TOKEN va VIDEO_REPO yo'q: Instagram uchun vaqtincha havola kerak")
    q = tanla_matn(st)
    log(f"Matn: {q['text'][:50]!r} — {q.get('author')}")
    video = video_yasa(q, cfg)
    if joylash:
        ig_joyla(cfg, video, caption_yasa(q, cfg))
        st["ishlatilgan"].append(q["text"])
        save_state(st)
    # eski videolarni tozalash (oxirgi 15 tasi qoladi)
    vids = sorted((BASE / "chiqish").glob("status_*.mp4"))
    for old in vids[:-15]:
        old.unlink(missing_ok=True)
    return video


def jadval(cfg):
    slots = cfg.get("vaqtlar", ["09:00", "14:00", "19:30", "22:30"])
    log(f"Agent ishga tushdi. Vaqtlar: {', '.join(slots)} (kompyuter vaqti bo'yicha)")
    while True:
        st = load_state()
        if cfg.get("access_token"):
            token_yangila(cfg, st)
        now = datetime.now()
        for s in slots:
            k = f"{now:%Y-%m-%d} {s}"
            if k in st["bajarilgan"] or st["urinish"].get(k, 0) >= 3:
                continue
            h, m = map(int, s.split(":"))
            t = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if 0 <= (now - t).total_seconds() < 3600:  # 1 soat ichida bajaramiz
                st["urinish"][k] = st["urinish"].get(k, 0) + 1
                save_state(st)
                try:
                    bitta_status(cfg, st, joylash=True)
                    st["bajarilgan"].append(k)
                except Exception as e:
                    log(f"❌ Xato: {e}")
                # eski yozuvlarni tozalash
                st["bajarilgan"] = st["bajarilgan"][-40:]
                st["urinish"] = dict(list(st["urinish"].items())[-40:])
                save_state(st)
        time.sleep(30)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="video yasaydi, joylamaydi")
    ap.add_argument("--now", action="store_true", help="hoziroq bitta joylaydi")
    a = ap.parse_args()

    if a.test:
        cfg = load_cfg()
        v = bitta_status(cfg, load_state(), joylash=False)
        log(f"Test tayyor. Videoni oching: {v}")
        return
    cfg = load_cfg()
    if not cfg.get("access_token"):
        sys.exit("config.json ichida access_token bo'sh. README.md dagi 3-qadamga qarang.")
    if a.now:
        bitta_status(cfg, load_state(), joylash=True)
        return
    jadval(cfg)


if __name__ == "__main__":
    main()
