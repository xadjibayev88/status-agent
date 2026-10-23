# Instagram Status Agent

Matnli statuslarni (mashhur kishilar so'zlari, maqollar) fon video + musiqa bilan
9:16 Reels qilib yasaydi va Instagramga kuniga 3-4 marta o'zi joylaydi.

## 1-qadam: o'rnatish (bir marta)
1. Python 3.9+ o'rnatilgan bo'lsin (python.org).
2. Shu papkada cmd/terminal ochib: `pip install -r requirements.txt`
   (ffmpeg ham shu bilan o'rnatiladi, alohida kerak emas)
3. `config.example.json` ni nusxalab `config.json` deb nomlang.
   `kanal_nomi` ga o'z kanalingizni yozing (videoda pastda ko'rinadi).

## 2-qadam: sinov (Instagramsiz)
`python agent.py --test`
`chiqish/` papkasida video chiqadi. Tekshiring.

Chiroyli shrift: fonts.google.com dan Cormorant Garamond va Montserrat ni
yuklab, `.ttf` fayllarini `fonts/` ichiga tashlang. Bo'lmasa kompyuterdagi
oddiy shrift ishlatiladi.

## 3-qadam: bepul fon videolar va musiqa
- Fon video: pexels.com/api da bepul kalit oling va `config.json` dagi
  `pexels_api_key` ga yozing. Agent portret videolarni o'zi yuklaydi.
  Yoki o'zingizning videolaringizni `fon_videolar/` ga tashlang.
- Musiqa: pixabay.com/music yoki YouTube Audio Library dan mualliflik
  huquqisiz mp3 yuklab, `musiqalar/` ga tashlang. Agent tasodifiy tanlaydi.
  (Instagramning "trend musiqa"sini API orqali qo'shib bo'lmaydi.)

## 4-qadam: Instagram ulash
1. Instagram akkaunt Professional (Business yoki Creator) bo'lishi shart.
2. developers.facebook.com da ilova yarating, "Instagram" mahsulotini qo'shing
   (Instagram API with Instagram Login).
3. O'z akkauntingizni Instagram tester qilib qo'shing va token yarating,
   ruxsatlar: `instagram_business_basic`, `instagram_business_content_publish`.
4. Tokenni `config.json` dagi `access_token` ga qo'ying.
5. Sinov: `python agent.py --now` (bitta video joylaydi).

## 5-qadam: ishga tushirish
`python agent.py`
Oyna ochiq tursin. Vaqtlar `config.json` da `vaqtlar` ichida (3 ta
xohlasangiz bittasini o'chiring). Kompyuter o'chiq bo'lsa ishlamaydi;
24/7 uchun keyin bepul serverga ko'chirish mumkin.

## Matnlar
`matnlar.json` ga o'zingiz yangi matn qo'shing: {"text": "...", "author": "..."}
Muallifi aniq bo'lmasa `"author": null` yozing. Noto'g'ri nisbat izohlarda
tuzatiladi. Agent bir matnni hammasi ishlatilmaguncha takrorlamaydi.
