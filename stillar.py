# -*- coding: utf-8 -*-
"""
Reels uchun dizayn uslublari. Har bir Reels boshqacha ko'rinadi, oxirgi uslublar takrorlanmaydi.

agent.py shuni chaqiradi:
    nom = tanla(oxirgilar, majburiy, run_raqami)
    natija = build(nom, matn, muallif, handle, chiqish_papkasi, fonts_papkasi, fallback_shriftlar)

Qatlam: (png, y, boshlanish, tugash, fade, {"x": int, "rise": px}).
Birinchi qator va fon-qoraytirish 0-soniyadan to'liq ko'rinadi (Instagram muqovasi uchun).
Xavfsiz zona: tepada 250 px va pastda 420 px (1920 dan) bo'sh, yon chetlar kamida 90 px.
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
SAFE_TOP = 270          # matn shundan yuqoriga chiqmaydi (<= 250 qoidasi + zaxira)
SAFE_BOTTOM = 1380      # matn bloki shundan pastga tushmaydi
HANDLE_Y = 1425         # @kanal: pastki 420 px (y > 1500) dan tashqarida
MAX_LINES = 6
MIN_SIZE = 32
HARD_MIN_SIZE = 20     # 6 qatorga sig'masa ham xavfsiz zonada qolish uchun oxirgi chegara
AUTHOR_PX, HANDLE_PX = 42, 34
NAMES = ["klassik", "muharrir", "shisha", "kino", "mono", "romantik"]
RECENT_AVOID = 3

CREAM, WHITE, GOLD = (245, 240, 230), (255, 255, 255), (217, 178, 111)


# ---------- uslub tanlash ----------
def tanla(recent, forced=None, run=None):
    """Oxirgi RECENT_AVOID ta ishlatilgan uslubdan boshqasini tanlaydi."""
    if forced:
        if forced in NAMES:
            return forced
    banned = [n for n in (recent or [])[-RECENT_AVOID:]]
    cand = [n for n in NAMES if n not in banned] or list(NAMES)
    if run is not None:  # bulutda holat saqlanmaydi: run raqami bo'yicha aylantiramiz
        k = int(run) % len(NAMES)
        for n in NAMES[k:] + NAMES[:k]:
            if n in cand:
                return n
    return random.choice(cand)


# ---------- shrift va matn o'lchash ----------
def _font(fonts_dir, fname, size, weight, fallback):
    p = Path(fonts_dir) / fname
    try:
        if p.exists():
            f = ImageFont.truetype(str(p), size)
            if weight:
                try:
                    f.set_variation_by_axes([weight])
                except Exception:
                    pass
            return f
    except Exception:
        pass
    try:
        if fallback:
            return ImageFont.truetype(fallback, size)
        return ImageFont.load_default(size)
    except Exception:
        return ImageFont.load_default()


def tlen(text, f, track=0):
    if not text:
        return 0.0
    if not track:
        return f.getlength(text)
    return sum(f.getlength(c) for c in text) + track * (len(text) - 1)


def _draw(d, xy, text, f, fill, track=0):
    if not track:
        d.text(xy, text, font=f, fill=fill)
        return
    x, y = xy
    for c in text:
        d.text((x, y), c, font=f, fill=fill)
        x += f.getlength(c) + track


def _wrap(text, f, maxw, track=0):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for w in para.split():
            t = (cur + " " + w).strip()
            if tlen(t, f, track) <= maxw:
                cur = t
            else:
                if cur:
                    lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def _fit(text, mk, size0, maxw, track_em, lh_mul, max_h):
    """Avval <= 6 qator va balandlikka sig'ish uchun shrift kichrayadi (MIN_SIZE gacha).
    Baribir sig'masa, qatorlar 6 dan oshsa ham xavfsiz zonadan chiqmaydigan darajagacha kichraytiramiz."""
    size = size0
    while True:
        f = mk(size)
        tr = track_em * size
        lines = _wrap(text, f, maxw, tr)
        h = len(lines) * int(size * lh_mul)
        fits = h <= max_h and all(tlen(x, f, tr) <= maxw for x in lines)
        if (fits and len(lines) <= MAX_LINES) or size <= MIN_SIZE:
            break
        size -= 4
    while not fits and size > HARD_MIN_SIZE:
        size -= 2
        f = mk(size)
        tr = track_em * size
        lines = _wrap(text, f, maxw, tr)
        h = len(lines) * int(size * lh_mul)
        fits = h <= max_h and all(tlen(x, f, tr) <= maxw for x in lines)
    return f, lines, int(size * lh_mul), tr, size


def _author_font(fonts, name, weight, size, text, track, maxw, fallback):
    """Muallif qatori kengligi maxw dan oshmasin (juda uzun ism bo'lsa shrift 30 gacha kichrayadi)."""
    while True:
        f = _font(fonts, name, size, weight, fallback)
        if tlen(text, f, track) <= maxw or size <= 30:
            return f
        size -= 2


def _text_img(text, f, fill, track=0, shadow=(2, 4, 8, 200), glow=None, pad=36):
    """Bitta qator/so'z uchun shaffof rasm: soya va ixtiyoriy yorug'lik (glow) bilan."""
    asc, desc = f.getmetrics()
    w, h = int(math.ceil(tlen(text, f, track))) + 2 * pad + 2, asc + desc + 2 * pad
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if shadow:
        dx, dy, bl, al = shadow
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        _draw(ImageDraw.Draw(sh), (pad + dx, pad + dy), text, f, (0, 0, 0, al), track)
        img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(bl)))
    if glow:
        col, rad = glow
        g = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        _draw(ImageDraw.Draw(g), (pad, pad), text, f, tuple(col) + (255,), track)
        g = g.filter(ImageFilter.GaussianBlur(rad))
        img = Image.alpha_composite(Image.alpha_composite(img, g), g)
    _draw(ImageDraw.Draw(img), (pad, pad), text, f, fill, track)
    return img, pad


def _scrim(y0, y1, path, alpha=96, blur=160, color=(0, 0, 0)):
    img = Image.new("RGBA", (W, H), color + (0,))
    ImageDraw.Draw(img).rectangle([0, max(0, y0), W, min(H, y1)], fill=color + (alpha,))
    img.filter(ImageFilter.GaussianBlur(blur)).save(path)


# ---------- qatlam yig'uvchi ----------
class _Layers:
    def __init__(self, out):
        self.out, self.items, self.n, self.done = Path(out), [], 0, 0.0

    def add(self, img, x, y, start=0.0, fade=0.5, rise=0):
        path = self.out / f"_st{self.n}.png"
        self.n += 1
        img.save(path)
        fd = 0.0 if start <= 0.001 else fade
        self.items.append((path, int(y), float(start), None, fd, {"x": int(x), "rise": rise if fd else 0}))
        self.done = max(self.done, start + fd)

    def scrim(self, y0, y1, **kw):
        path = self.out / f"_st{self.n}.png"
        self.n += 1
        _scrim(y0, y1, path, **kw)
        self.items.append((path, 0, 0.0, None, 0.0, {}))

    def text(self, text, f, fill, x, y, start=0.0, fade=0.5, rise=0, **kw):
        img, pad = _text_img(text, f, fill, **kw)
        self.add(img, x - pad, y - pad, start, fade, rise)

    def rect(self, x, y, w, h, fill, start=0.0, fade=0.5):
        img = Image.new("RGBA", (max(1, int(w)), max(1, int(h))), fill)
        self.add(img, x, y, start, fade)


def _reveal_lines(L, lines, f, fill, y0, lh, tr, mode, step, fade, align="m", x0=0, cx=W // 2,
                  rise_px=26, **kw):
    """Matnni qator-qator / ko'tarilib / so'zma-so'z ochadi. Qaytaradi: oxirgi paydo bo'lish vaqti."""
    t = 0.0
    nwords = sum(len(ln.split()) for ln in lines[1:])
    group = max(1, math.ceil(nwords / 30))
    for i, ln in enumerate(lines):
        lw = tlen(ln, f, tr)
        lx = x0 if align == "l" else cx - lw / 2
        y = y0 + i * lh
        if mode != "word" or i == 0:
            L.text(ln, f, fill, lx, y, t, fade,
                   rise=rise_px if (mode == "rise" and t > 0) else 0, track=tr, **kw)
            if mode == "word":
                t = step
            else:
                t = (i + 1) * step
            continue
        words = ln.split()
        for a in range(0, len(words), group):
            pre = " ".join(words[:a]) + " " if a else ""
            wx = lx + (tlen(pre, f, tr) + tr if a else 0)
            L.text(" ".join(words[a:a + group]), f, fill, wx, y, t, fade, track=tr, **kw)
            t += step * 0.45
        t += step * 0.2
    return max(0.0, t - (step if mode != "word" else 0))


def _place(ch, bottom=None):
    """Blokning yuqori y si: markazga (0.45 H) yaqin, xavfsiz zonada."""
    if bottom is not None:
        return max(SAFE_TOP, bottom - ch)
    return int(max(SAFE_TOP, min(H * 0.45 - ch / 2, SAFE_BOTTOM - ch)))


def _handle(L, handle, fonts, fb, x=None, color=(255, 255, 255, 191), track_em=0.0):
    if not handle:
        return
    f = _font(fonts, "Montserrat-Medium.ttf", HANDLE_PX, None, fb["sans"])
    tr = track_em * HANDLE_PX
    lw = tlen(handle, f, tr)
    L.text(handle, f, color, (W - lw) / 2 if x is None else x, HANDLE_Y, 0.5, 0.5, track=tr,
           shadow=(1, 2, 6, 230))


# ---------- uslublar ----------
def _klassik(q, author, handle, L, fonts, fb):
    mk = lambda s: _font(fonts, "CormorantGaramond-SemiBold.ttf", s, None, fb["serif"])
    f, lines, lh, tr, size = _fit(q, mk, 88, W - 220, 0, 1.22, SAFE_BOTTOM - SAFE_TOP - 220)
    mark_h = 110
    total = mark_h + len(lines) * lh + (120 if author else 0)
    y = _place(total)
    L.scrim(y - 220, y + total + 220, alpha=min(165, 100 + 22 * max(0, len(lines) - 2)), blur=160)
    mf = _font(fonts, "CormorantGaramond-SemiBold.ttf", 150, None, fb["serif"])
    L.text("“", mf, (245, 240, 230, 154), (W - mf.getlength("“")) / 2, y - 25, shadow=(3, 4, 6, 200))
    t = _reveal_lines(L, lines, f, "#F5F0E6", y + mark_h, lh, 0, "line", 0.3, 0.5, shadow=(3, 4, 6, 200))
    if author:
        yy = y + mark_h + len(lines) * lh
        L.rect(W // 2 - 45, yy + 26, 90, 3, (217, 213, 204, 180), t + 0.1)
        af = _font(fonts, "CormorantGaramond-MediumItalic.ttf", 50, None, fb["italic"])
        L.text(author, af, "#F6EBCB", (W - tlen(author, af)) / 2, yy + 40, t + 0.3, shadow=(3, 4, 6, 200))
    _handle(L, handle, fonts, fb)
    return {"grade": "eq=saturation=1.06:contrast=1.05:brightness=-0.02", "finish": ""}


def _muharrir(q, author, handle, L, fonts, fb):
    mk = lambda s: _font(fonts, "PlayfairDisplay-Variable.ttf", s, 500, fb["serif"])
    xt, maxw = 140, 850
    f, lines, lh, tr, size = _fit(q, mk, 100, maxw, 0, 1.2, SAFE_BOTTOM - SAFE_TOP - 180)
    extra = 165 if author else 0
    total = len(lines) * lh + extra
    y = _place(total)
    L.scrim(y - 200, y + total + 200, alpha=min(185, 130 + 18 * max(0, len(lines) - 3)), blur=150)
    L.rect(96, y + 8, 4, total - 16, GOLD + (235,), 0.0)
    t = _reveal_lines(L, lines, f, "#FBF8F1", y, lh, 0, "rise", 0.4, 0.7, align="l", x0=xt,
                      shadow=(2, 4, 8, 190))
    if author:
        a = author.upper()
        af = _author_font(fonts, "Montserrat-Variable.ttf", 500, AUTHOR_PX, a, 3, maxw, fb["sans"])
        L.text(a, af, GOLD + (255,), xt, y + len(lines) * lh + 68, t + 0.3, 0.5,
               track=3, shadow=(1, 2, 6, 230))
    _handle(L, handle, fonts, fb, x=xt)
    return {"grade": "eq=saturation=0.82:contrast=1.08:brightness=-0.04,colorbalance=bs=0.04:bm=0.03",
            "finish": ""}


def _shisha(q, author, handle, L, fonts, fb):
    mk = lambda s: _font(fonts, "Lora-Italic-Variable.ttf", s, 500, fb["italic"])
    cw, inner = 900, 800
    padt, padb = 92, 66
    f, lines, lh, tr, size = _fit(q, mk, 72, inner, 0, 1.3,
                                  SAFE_BOTTOM - SAFE_TOP - padt - padb - (100 if author else 0))
    ch = padt + len(lines) * lh + (100 if author else 0) + padb
    cy = _place(ch)
    cx = (W - cw) // 2
    m = 90
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, cw - 1, ch - 1], radius=56, fill=255)
    mpath = L.out / "_stmask.png"
    mask.save(mpath)
    card = Image.new("RGBA", (cw + 2 * m, ch + 2 * m), (0, 0, 0, 0))
    sh = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([m, m + 18, m + cw, m + ch + 18], radius=56, fill=(0, 0, 0, 150))
    card = Image.alpha_composite(card, sh.filter(ImageFilter.GaussianBlur(34)))
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle([m, m, m + cw - 1, m + ch - 1], radius=56, fill=(8, 9, 18, 172),
                         outline=(255, 255, 255, 80), width=2)
    L.add(card, cx - m, cy - m, 0.0)
    L.rect(W // 2 - 32, cy + 52, 64, 3, GOLD + (230,), 0.0)
    t = _reveal_lines(L, lines, f, "#FFFFFF", cy + padt, lh, 0, "word", 0.28, 0.3,
                      shadow=(2, 3, 9, 200))
    if author:
        a = author.upper()
        af = _author_font(fonts, "Montserrat-Variable.ttf", 500, AUTHOR_PX, a, 3, inner, fb["sans"])
        L.text(a, af, "#F1E7D0", (W - tlen(a, af, 3)) / 2, cy + padt + len(lines) * lh + 34, t + 0.25, 0.5,
               track=3, shadow=(1, 2, 6, 230))
    _handle(L, handle, fonts, fb)
    return {"grade": "eq=saturation=1.14:contrast=1.03:brightness=-0.01", "finish": "",
            "card": (cx, cy, cw, ch, mpath)}


def _kino(q, author, handle, L, fonts, fb):
    mk = lambda s: _font(fonts, "Lora-Italic-Variable.ttf", s, 500, fb["italic"])
    xt, maxw = 110, 860
    f, lines, lh, tr, size = _fit(q, mk, 66, maxw, 0, 1.32, 560)
    total = len(lines) * lh + (108 if author else 0)
    y = _place(total, bottom=SAFE_BOTTOM)
    L.scrim(y - 420, SAFE_BOTTOM + 170, alpha=185, blur=120)
    t = _reveal_lines(L, lines, f, "#FFF3DE", y, lh, 0, "line", 0.6, 0.9, align="l", x0=xt,
                      shadow=(2, 3, 9, 225))
    if author:
        a = "— " + author.upper()
        af = _author_font(fonts, "Montserrat-Variable.ttf", 500, AUTHOR_PX, a, 3, maxw, fb["sans"])
        L.rect(xt, y + len(lines) * lh + 18, 56, 2, (227, 183, 122, 230), t + 0.2, 0.5)
        L.text(a, af, "#F0C48A", xt, y + len(lines) * lh + 40, t + 0.4, 0.6,
               track=3, shadow=(1, 2, 6, 230))
    _handle(L, handle, fonts, fb, x=xt, track_em=0.1)
    bar = 190
    return {"grade": ("eq=saturation=0.88:contrast=1.12:brightness=-0.05,"
                      "colorbalance=rs=0.06:rm=0.05:bs=-0.06:bm=-0.04"),
            "finish": (f"noise=alls=9:allf=t,drawbox=x=0:y=0:w=iw:h={bar}:color=black:t=fill,"
                       f"drawbox=x=0:y=ih-{bar}:w=iw:h={bar}:color=black:t=fill")}


def _mono(q, author, handle, L, fonts, fb):
    mk = lambda s: _font(fonts, "Montserrat-Variable.ttf", s, 700, fb["sans"])
    maxw = 880
    f, lines, lh, tr, size = _fit(q.upper(), mk, 62, maxw, 0.1, 1.42,
                                  SAFE_BOTTOM - SAFE_TOP - 220)
    total = 56 + len(lines) * lh + 54 + (84 if author else 0)
    y = _place(total)
    L.scrim(y - 240, y + total + 240, alpha=130, blur=160)
    L.rect(W // 2 - 60, y, 120, 3, (255, 255, 255, 235), 0.0)
    ty = y + 56
    t = _reveal_lines(L, lines, f, "#FFFFFF", ty, lh, tr, "word", 0.3, 0.3, shadow=(0, 4, 14, 225))
    yb = ty + len(lines) * lh + 22
    L.rect(W // 2 - 60, yb, 120, 3, (255, 255, 255, 235), t + 0.1, 0.4)
    if author:
        a = author.upper()
        af = _author_font(fonts, "Montserrat-Variable.ttf", 500, AUTHOR_PX, a, 4, maxw, fb["sans"])
        L.text(a, af, (255, 255, 255, 235), (W - tlen(a, af, 4)) / 2, yb + 30, t + 0.25, 0.5,
               track=4, shadow=(1, 2, 8, 235))
    _handle(L, handle, fonts, fb, track_em=0.12)
    return {"grade": "hue=s=0,eq=contrast=1.2:brightness=-0.08", "finish": ""}


def _romantik(q, author, handle, L, fonts, fb):
    mk = lambda s: _font(fonts, "PlayfairDisplay-Italic-Variable.ttf", s, 500, fb["italic"])
    f, lines, lh, tr, size = _fit(q, mk, 84, 860, 0, 1.3, SAFE_BOTTOM - SAFE_TOP - 270)
    top, bot = 70, (150 if author else 20)
    total = top + len(lines) * lh + bot
    y = _place(total)
    L.scrim(y - 230, y + total + 230, alpha=min(200, 170 + 10 * max(0, len(lines) - 3)), blur=170, color=(40, 6, 22))
    # bezak: ikki chiziq va o'rtada romb
    d = Image.new("RGBA", (260, 24), (0, 0, 0, 0))
    dd = ImageDraw.Draw(d)
    dd.line([(10, 12), (100, 12)], fill=GOLD + (230,), width=2)
    dd.line([(160, 12), (250, 12)], fill=GOLD + (230,), width=2)
    dd.polygon([(130, 2), (140, 12), (130, 22), (120, 12)], fill=GOLD + (255,))
    L.add(d, (W - 260) // 2, y + 8, 0.0)
    glow = ((255, 176, 150), 10)
    t = _reveal_lines(L, lines, f, "#FFF7F0", y + top, lh, 0, "rise", 0.45, 0.8,
                      shadow=(0, 4, 10, 225), glow=glow, pad=44)
    if author:
        af = _author_font(fonts, "PlayfairDisplay-Italic-Variable.ttf", 500, 52, author, 0, 860, fb["italic"])
        L.text(author, af, "#FBE3B0", (W - tlen(author, af)) / 2, y + top + len(lines) * lh + 26,
               t + 0.35, 0.6, rise=14, shadow=(0, 3, 9, 230))
    _handle(L, handle, fonts, fb)
    return {"grade": ("eq=saturation=1.1:contrast=0.98:brightness=0.02,"
                      "colorbalance=rs=0.08:gs=-0.02:bs=0.03:rm=0.06:bm=0.02:rh=0.04:gh=0.02,"
                      "curves=all='0/0.05 1/0.98',unsharp=7:7:-0.7:7:7:0"),
            "finish": ""}


_BUILDERS = {"klassik": _klassik, "muharrir": _muharrir, "shisha": _shisha,
             "kino": _kino, "mono": _mono, "romantik": _romantik}


def build(name, text, author, handle, out, fonts_dir, fb):
    """Qaytaradi: dict(layers, muqova, grade, finish, card, name). fb: {"serif","italic","sans"} zaxira shriftlar."""
    L = _Layers(out)
    spec = _BUILDERS[name](text, author, handle, L, fonts_dir, fb)
    spec.setdefault("card", None)
    spec["layers"] = L.items
    spec["name"] = name
    spec["muqova"] = round(max(L.done, 0.5) + 0.3, 2)
    return spec
