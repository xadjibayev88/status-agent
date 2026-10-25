#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Faollik agenti: oxirgi Reels'lardagi yangi izohlarga avtomatik javob yozadi.
Izohga javob bergan kanal Instagram algoritmida yuqoriroq ko'rinadi va
izoh qoldirgan odamning obuna bo'lish ehtimoli oshadi.

Har bir izohga faqat 1 marta javob beradi (javob bergan-bermaganini Instagramning
o'zidan tekshiradi, shuning uchun hech qanday fayl saqlash shart emas).

Kerakli ruxsat: instagram_business_manage_comments
(token shu ruxsat bilan yaratilmagan bo'lsa, agent xato bermasdan to'xtaydi va
logda nima qilish kerakligini yozadi).
"""
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent

# ---- Javoblar (xohlasangiz config.json ga "izoh_javoblari": [...] qo'shib almashtiring) ----
UMUMIY = [
    "Rahmat! ❤️ Har kuni yangi statuslar bor, kuzatib boring ✨",
    "Sizga yoqqanidan xursandmiz 🙏 Yaqinlaringizga ham yuboring 💌",
    "Katta rahmat! 🤍 Qaysi mavzuda status ko'proq bo'lsin?",
    "Rahmat, fikringiz biz uchun muhim 🌿",
    "❤️🙏 Obuna bo'lib qoling, ertaga yana zo'r status bo'ladi!",
    "Juda to'g'ri aytdingiz 👌 Rahmat!",
    "Rahmat! Saqlab qo'ying, kerak bo'lib qoladi 🔖",
]
QISQA = ["❤️🙏", "🤍✨", "🙏🌿", "Rahmat! ❤️", "🫶"]
SAVOL = [
    "Yaxshi savol! 🙏 Direktga yozing, albatta javob beramiz 💬",
    "Rahmat savolingiz uchun! Keyingi statuslarda bu haqida ham bo'ladi ✨",
]
MUSIQA = [
    "Musiqa nomini direktga yozib yuboramiz 🎵 Rahmat!",
    "Bu musiqa bizga ham juda yoqadi 🎶 Rahmat!",
]


def log(msg):
    print(msg, flush=True)


def load_cfg():
    cfg = {}
    for name in ("config.json", "config.example.json"):
        p = BASE / name
        if p.exists():
            cfg = json.loads(p.read_text(encoding="utf-8"))
            break
    if os.environ.get("IG_ACCESS_TOKEN"):
        cfg["access_token"] = os.environ["IG_ACCESS_TOKEN"]
    return cfg


def javob_tanla(text, cfg):
    t = (text or "").lower().strip()
    if cfg.get("izoh_javoblari"):
        return random.choice(cfg["izoh_javoblari"])
    if any(w in t for w in ("musiqa", "music", "qo'shiq", "qoshiq", "песня", "музыка", "song")):
        return random.choice(MUSIQA)
    if "?" in t:
        return random.choice(SAVOL)
    if len(re.sub(r"[\W_]+", "", t)) <= 3:  # faqat emoji yoki juda qisqa izoh
        return random.choice(QISQA)
    return random.choice(UMUMIY)


def main():
    cfg = load_cfg()
    token = cfg.get("access_token")
    if not token:
        log("IG_ACCESS_TOKEN yo'q, faollik agenti o'tkazib yuborildi.")
        return
    host = cfg.get("graph_host", "graph.instagram.com")
    ver = cfg.get("api_version", "v23.0")
    api = f"https://{host}/{ver}"
    hdr = {"Authorization": f"Bearer {token}"}
    max_javob = int(cfg.get("max_izoh_javob", 25))   # bir ishga tushishda ko'pi bilan
    nechta_post = int(cfg.get("izoh_post_soni", 15))   # oxirgi nechta Reels tekshiriladi

    me = requests.get(f"{api}/me", headers=hdr, params={"fields": "user_id,username"}, timeout=30).json()
    mening = (me.get("username") or "").lower()
    if not mening:
        log(f"Akkauntni aniqlab bo'lmadi: {me}")
        return

    media = requests.get(f"{api}/me/media", headers=hdr, timeout=30,
                         params={"fields": "id,timestamp", "limit": nechta_post}).json()
    if "error" in media:
        log(f"Postlarni o'qib bo'lmadi: {media['error'].get('message')}")
        return

    yozildi = jami = oldin = 0
    postlar = media.get("data", [])
    log(f"Akkaunt: @{mening}, tekshiriladigan Reels: {len(postlar)} ta")
    for m in postlar:
        r = requests.get(f"{api}/{m['id']}/comments", headers=hdr, timeout=30,
                         params={"fields": "id,text,username,replies{username}", "limit": 50}).json()
        if "error" in r:
            msg = r["error"].get("message", "")
            log(f"Izohlarni o'qib bo'lmadi: {msg}")
            if "permission" in msg.lower() or r["error"].get("code") in (10, 200):
                log("👉 Token 'instagram_business_manage_comments' ruxsatisiz yaratilgan. "
                    "Meta Developers > Instagram > API setup bo'limida tokenni qayta yarating "
                    "(ruxsatlar ro'yxatida comments belgilangan bo'lsin) va IG_ACCESS_TOKEN secretini yangilang.")
                return
            continue
        izohlar = r.get("data", [])
        if izohlar:
            log(f"  Post {m['id']}: {len(izohlar)} ta izoh")
        for c in izohlar:
            if (c.get("username") or "").lower() == mening:
                continue
            jami += 1
            javoblar = (c.get("replies") or {}).get("data", [])
            if any((x.get("username") or "").lower() == mening for x in javoblar):
                oldin += 1
                continue
            matn = javob_tanla(c.get("text"), cfg)
            p = requests.post(f"{api}/{c['id']}/replies", headers=hdr,
                              data={"message": matn}, timeout=30)
            if p.ok:
                yozildi += 1
                log(f"💬 @{c.get('username')}: {c.get('text', '')[:40]!r} → {matn}")
            else:
                log(f"Javob yozilmadi: {p.text[:200]}")
            if yozildi >= max_javob:
                log(f"Limitga yetildi ({max_javob}), qolganlari keyingi safar.")
                return
            time.sleep(random.uniform(4, 9))  # spamga o'xshamasligi uchun
    log(f"Faollik agenti tugadi: begona izohlar {jami} ta, oldin javob berilgan {oldin} ta, "
        f"hozir javob yozildi {yozildi} ta.")
    if jami == 0:
        log("Izoh topilmadi. Agar videolaringizda boshqalarning izohi bo'lsa-yu bu yerda 0 chiqsa, "
            "Meta ilovasi 'Development' rejimida bo'lgani uchun begona izohlar ko'rinmayotgan bo'lishi mumkin.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # asosiy joylashni hech qachon buzmasin
        log(f"Faollik agentida xato: {e}")
    sys.exit(0)
