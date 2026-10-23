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


def load_cfg():
    p = BASE / "config.json"
    if not p.exists():
        sys.exit("config.json topilmadi. config.example.json dan nusxa olib, "
                 "nomini config.json qiling.")
    return load_json(p, {})


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


def overlay_yasa(q, cfg, out):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, H], fill=(0, 0, 0, 85))  # fonni biroz qoraytiradi

    qpath = find_font(["cormorant", "playfair", "garamond"], SERIF_SYS)
    spath = find_font(["montserrat"], SANS_SYS)

    size = 84
    while True:
        font = load_font(qpath, size)
        lines = wrap(d, q["text"], font, W - 200)
        if len(lines) <= 8 or size <= 44:
            break
        size -= 4
    lh = int(size * 1.28)
    author = q.get("author")
    total = len(lines) * lh + (110 if author else 0)
    y = int(H * 0.46 - total / 2)

    items = []  # (x, y, matn, shrift, rang)
    for ln in lines:
        items.append((W // 2, y, ln, font, "#F5F0E6"))
        y += lh
    if author:
        items.append((W // 2, y + 50, "— " + author, load_font(spath, 38), "#D9D5CC"))
    handle = cfg.get("kanal_nomi", "")
    if handle:
        items.append((W // 2, H - 380, handle, load_font(spath, 34), "#FFFFFFB4"))

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for x, yy, t, f, _ in items:
        sd.text((x + 3, yy + 4), t, font=f, fill=(0, 0, 0, 200), anchor="ma")
    shadow = shadow.filter(ImageFilter.GaussianBlur(6))
    img = Image.alpha_composite(img, shadow)
    d = ImageDraw.Draw(img)
    for x, yy, t, f, c in items:
        d.text((x, yy), t, font=f, fill=c, anchor="ma")
    img.save(out)


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


def fon_tanla(cfg):
    key = cfg.get("pexels_api_key", "").strip()
    if key:
        try:
            p = pexels_video(cfg, key)
            if p:
                return p
        except Exception as e:
            log(f"Pexels ishlamadi: {e}")
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
        files += list((BASE / "musiqalar").glob(e))
    return random.choice(files) if files else None


# ---------- video yasash (ffmpeg) ----------
def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def video_yasa(q, cfg):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    overlay = BASE / "chiqish" / "_matn.png"
    out = BASE / "chiqish" / f"status_{ts}.mp4"
    overlay_yasa(q, cfg, overlay)
    bg = fon_tanla(cfg)
    music = musiqa_tanla()
    dur = round(max(7.0, min(12.0, 5 + len(q["text"]) * 0.07)), 1)

    cmd = [ffmpeg_exe(), "-y"]
    if bg.suffix.lower() in (".mp4", ".mov", ".webm"):
        cmd += ["-stream_loop", "-1", "-i", str(bg)]
    else:
        cmd += ["-loop", "1", "-i", str(bg)]
    cmd += ["-loop", "1", "-i", str(overlay)]
    if music:
        cmd += ["-i", str(music)]
        log(f"Musiqa: {music.name}")
    vf = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
          "fps=30,eq=brightness=-0.08:saturation=0.9,setsar=1[bg];"
          "[1:v]fps=30,format=rgba,fade=t=in:st=0.5:d=1.2:alpha=1[tx];"
          "[bg][tx]overlay=0:0:format=auto,format=yuv420p[v]")
    cmd += ["-filter_complex", vf, "-map", "[v]"]
    if music:
        cmd += ["-map", "2:a", "-af",
                f"afade=t=in:d=1,afade=t=out:st={dur - 1.5}:d=1.5"]
    cmd += ["-t", str(dur), "-c:v", "libx264", "-preset", "medium", "-crf", "23"]
    if music:
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
        cfg = load_json(BASE / "config.json", load_json(BASE / "config.example.json", {}))
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
