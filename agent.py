#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instagram status-video agenti.

  python agent.py          -> doimiy ishlaydi, jadval bo'yicha o'zi joylaydi
  python agent.py --test   -> bitta video yasaydi (chiqish/ papkada), joylamaydi
  python agent.py --now    -> bitta video yasab, darhol joylaydi
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

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
    baza = load_json(BASE / "matnlar.json", [])
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
    qpath = find_font(["cormorant", "playfair", "garamond"], SERIF_SYS)
    spath = find_font(["montserrat"], SANS_SYS)
    probe = ImageDraw.Draw(Image.new("RGBA", (W, H)))
    size = 76
    while True:
        font = load_font(qpath, size)
        lines = wrap(probe, q["text"], font, W - 220)
        if len(lines) <= 6 or size <= 40:
            break
        size -= 4
    lh = int(size * 1.3)
    author = q.get("author")
    mark_h = 110
    total = mark_h + len(lines) * lh + (110 if author else 0)
    y = int(H * 0.45 - total / 2)
    out = BASE / "chiqish"
    layers = []

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
        add("author", "\u2014 " + author, load_font(spath, 34), "#D9D5CC", yy + 40, 70, t_end + 0.7)
        last = t_end + 0.7
    handle = cfg.get("kanal_nomi", "")
    if handle:
        add("handle", handle, load_font(spath, 34), "#FFFFFFB4", H - 380, 70, 2.0)
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


def pexels_video(cfg, key):
    import requests
    q = random.choice(cfg.get("fon_qidiruv", ["nature"]))
    r = requests.get("https://api.pexels.com/videos/search",
                     headers={"Authorization": key},
                     params={"query": q, "orientation": "portrait",
                             "size": "medium", "per_page": 20}, timeout=30)
    r.raise_for_status()
    vids = r.json().get("videos", [])
    random.shuffle(vids)
    for v in vids:
        if v.get("duration", 0) < 6:
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


def pixabay_video(cfg, key):
    import requests
    q = random.choice(cfg.get("fon_qidiruv", ["nature"]))
    r = requests.get("https://pixabay.com/api/videos/", timeout=30,
                     params={"key": key, "q": q, "per_page": 30,
                             "safesearch": "true", "min_width": 720})
    r.raise_for_status()
    hits = [h for h in r.json().get("hits", []) if h.get("duration", 0) >= 6]
    random.shuffle(hits)

    def info(h):
        v = h.get("videos", {})
        f = v.get("large") if v.get("large", {}).get("url") else v.get("medium", {})
        return f

    # vertikal (portret) videolarni afzal ko'ramiz, bo'lmasa istalgani (markazdan kesiladi)
    hits.sort(key=lambda h: 0 if info(h).get("height", 0) > info(h).get("width", 1) else 1)
    for h in hits:
        f = info(h)
        if not f.get("url"):
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
    for nom, fn, kalit in (("Pexels", pexels_video, "pexels_api_key"),
                           ("Pixabay", pixabay_video, "pixabay_api_key")):
        key = (cfg.get(kalit) or "").strip()
        if key:
            try:
                p = fn(cfg, key)
                if p:
                    return p
            except Exception as e:
                log(f"{nom} ishlamadi: {e}")
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
        sd.text((W // 2 + 2, pad + i * lh + 3), ln, font=font, fill=(0, 0, 0, 210), anchor="ma")
    sh = sh.filter(ImageFilter.GaussianBlur(4))
    img = Image.alpha_composite(img, sh)
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        d.text((W // 2, pad + i * lh), ln, font=font, fill=fill, anchor="ma")
    img.save(out)
    return pad, h


def musiqa_katlamlar(q, cfg, music):
    """Musiqa asosiy rolda: subtitr (.srt bo'lsa) yoki tepada bitta kichik status.
    Qaytaradi: layers, davomiylik, musiqaning boshlanish soniyasi."""
    md = media_duration(music)
    dur = round(random.uniform(15, 25), 1)
    if md and md < dur + 2:
        dur = round(max(10.0, md - 1), 1)
    srt = music.with_suffix(".srt")
    cues = parse_srt(srt) if srt.exists() else []
    start = 0.0
    if cues:
        cand = [c for c in cues if not md or c[0] <= md - dur]
        c0 = random.choice(cand) if cand else cues[0]
        start = max(0.0, c0[0] - 1.0)
    elif md > dur + 4:
        start = random.uniform(0, md - dur - 2)

    spath = find_font(["montserrat"], SANS_SYS)
    qpath = find_font(["cormorant", "playfair", "garamond"], SERIF_SYS)
    probe = ImageDraw.Draw(Image.new("RGBA", (W, H)))
    out = BASE / "chiqish"
    layers = []
    y_sub = int(H * float(cfg.get("subtitr_y", 0.32)))

    if cues:
        font = load_font(spath, 44)
        n = 0
        for a, b, text in cues:
            a2, b2 = a - start, min(b - start, dur - 1.0)
            if b2 <= 0.3 or a2 >= dur - 1.0:
                continue
            a2 = max(a2, 0.2)
            lines = wrap(probe, text, font, W - 200)[:3]
            path = out / f"_c{n}.png"
            pad, _ = block_yasa(lines, font, "#FFFFFFEB", path)
            fin = min(0.3, (b2 - a2) / 3)
            layers.append((path, y_sub - pad, a2, b2, fin))
            n += 1
            if n >= 16:
                break
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
    return layers, dur, start


def video_yasa(q, cfg):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = BASE / "chiqish" / f"status_{ts}.mp4"
    music = musiqa_tanla()
    uslub = cfg.get("uslub", "musiqa")
    if uslub == "aralash":
        uslub = random.choice(["musiqa", "musiqa", "status"])
    mstart = None
    if music and uslub == "musiqa":
        layers, dur, mstart = musiqa_katlamlar(q, cfg, music)
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

    zoom = "" if is_video else (",zoompan=z='min(1+0.0006*on,1.25)':x='iw/2-(iw/zoom/2)'"
                                ":y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30")
    f = ["[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,"
         "eq=brightness=-0.06:saturation=0.95,"
         "drawbox=x=0:y=0:w=iw:h=ih:color=black@0.28:t=fill" + zoom + ",setsar=1[v0]"]
    for i, (_, y, st, en, fin) in enumerate(layers, 1):
        fx = f"fade=t=in:st={st:.2f}:d={fin:.2f}:alpha=1"
        if en:
            fo = min(0.3, (en - st) / 3)
            fx += f",fade=t=out:st={en - fo:.2f}:d={fo:.2f}:alpha=1"
        f.append(f"[{i}:v]fps=30,format=rgba,{fx}[s{i}]")
        f.append(f"[v{i - 1}][s{i}]overlay=0:{y}:format=auto[v{i}]")
    f.append(f"[v{len(layers)}]fade=t=out:st={dur - 1.2:.2f}:d=1.2,format=yuv420p[v]")
    cmd += ["-filter_complex", ";".join(f), "-map", "[v]"]
    if music or ambient:
        af = f"afade=t=in:d=1.5,afade=t=out:st={dur - 2:.1f}:d=2"
        if ambient:
            af = "lowpass=f=3500,aecho=0.8:0.85:700|1100:0.4|0.3," + af
        cmd += ["-map", f"{ai}:a", "-af", af, "-ac", "2"]
    cmd += ["-t", d, "-c:v", "libx264", "-preset", "medium", "-crf", "23"]
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


def ig_joyla(cfg, video, caption):
    import requests
    host = cfg.get("graph_host", "graph.instagram.com")
    ver = cfg.get("api_version", "v23.0")
    tok = cfg["access_token"]
    hdr = {"Authorization": f"Bearer {tok}"}

    r = _check(requests.post(
        f"https://{host}/{ver}/me/media", headers=hdr, timeout=60,
        data={"media_type": "REELS", "upload_type": "resumable",
              "caption": caption, "share_to_feed": "true"}))
    j = r.json()
    cid = j["id"]
    uri = j.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{ver}/{cid}"

    size = os.path.getsize(video)
    with open(video, "rb") as f:
        _check(requests.post(uri, timeout=900, data=f, headers={
            "Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)}))

    for _ in range(60):
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
    log(f"✅ Instagramga joylandi: {r.json()}")


# ---------- asosiy oqim ----------
def bitta_status(cfg, st, joylash):
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
