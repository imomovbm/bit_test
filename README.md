# TestDuel

Foydalanuvchilar o'rtasida test bo'yicha bellashuv (duel) va mustaqil mashq qilish uchun veb-ilova.

## Imkoniyatlar

- **Duel** — ikki foydalanuvchi bitta mavzuni tanlaydi, har biriga 15 ta savol beriladi, har bir savolga 15 soniya.
  - G'olib — ko'proq to'g'ri javob bergan; teng bo'lsa — tezroq javob bergan.
  - Raqib aloqasi uzilsa yoki 30 soniya davomida javob bermasa — ikkinchi ishtirokchi g'olib.
- **Taklif havolasi** — onlayn bo'lmagan do'stni duelga havola orqali chaqirish.
- **Mashq rejimi** — vaqt cheklovisiz 10 / 30 / 50 yoki barcha savollar.
- **O'yinlar paneli** (faqat o'qituvchilar va administratorlar uchun):
  - **Octagon** — jonli viktorina: savollar proyektorda, o'quvchilar telefonda PIN bilan qo'shilib (ro'yxatdan
    o'tmasdan) rangli shakllarni bosib javob beradi (pastda batafsil);
  - **Balloon Pop** — sinfda bitta ekranda (proyektor/doska) o'ynaladigan jamoaviy o'yin (pastda batafsil).
- **Reyting** va shaxsiy statistika.
- **Boshqaruv paneli** (faqat administratorlar uchun) — test mavzularini yuklash va foydalanuvchilarni boshqarish (pastda batafsil).
- Oddiy ro'yxatdan o'tish (login + parol), yorug'/qorong'i rejim, mobil qurilmalarga moslashgan.

## Ishga tushirish

Python 3.11+ kerak.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Brauzerda oching: <http://localhost:8080>

**Birinchi ro'yxatdan o'tgan foydalanuvchi avtomatik ravishda administrator bo'ladi.**
Ma'lumotlar bazasi (SQLite) `data/testduel.db` faylida saqlanadi.

## Octagon — jonli viktorina

O'yin nomi bitta joyda — `static/js/octagon/common.js` dagi `GAME_NAME` (masalan, `'Blitz'` ga almashtirish mumkin;
ichki nomlar — `/api/octagon`, `app/octagon.py` — o'zgarmaydi).

**O'qituvchi:** «O'yinlar» → Octagon → mavzu, savollar soni va **har bir savol uchun vaqt** (10 / 20 / 30 / 60 s yoki
5–120 s oralig'ida istalgan son, standart 20 s), savollar/variantlarni aralashtirish → **Lobbini ochish**.
- Lobbida katta **PIN** (6 xonali) va **QR kod** (havola: `sayt/play/PIN`), qo'shilgan o'quvchilar (onlayn/oflayn) va
  ularning soni. Nomaqbul ismli o'quvchini chiqarish mumkin (o'sha ism bu o'yinda qayta ishlatilmaydi, boshqa ism
  bilan qaytishi mumkin). **«Qo'shilish ochiq / yopiq»** tugmasi yangi o'quvchilar qo'shilishini to'xtatadi (o'yindagilar
  qayta ulana oladi). Savol vaqtini lobbida o'zgartirish mumkin, o'yin boshlangach u qulflanadi (server ham
  tekshiradi).
- O'yin faqat **Boshlash** bosilganda boshlanadi. Har bir savol: «tayyorlaning» (3 s) → savol (savol matni va
  variantlar rang + shakl bilan) → natija (javoblar taqsimoti, to'g'ri javob) → eng yaxshi 5 talik → keyingi savol →
  yakunda podium. Hamma javob bersa, savol vaqt tugashini kutmasdan yopiladi. «Savolni yakunlash» va «Tugatish»
  (muddatidan oldin yakuniy natijalar) tugmalari bor. Probel/Enter — keyingi bosqich, F — to'liq ekran.
- PIN o'qituvchi va o'quvchi ekranining tepasida doim ko'rinib turadi. O'qituvchi sahifani yangilasa yoki aloqa uzilsa,
  o'sha o'yinni boshqarishda davom etadi.

**O'quvchi** (ro'yxatdan o'tmasdan): QR kodni skanerlaydi yoki `sayt/play` ni ochib PIN kiritadi, so'ng faqat ism
yozadi.
- Ism: 1–20 belgi, o'yinda yagona (katta-kichik harf va o'xshash harflar hisobga olinmaydi); HTML, ko'rinmas belgilar,
  emoji va oddiy so'kinishlar filtrlanadi.
- Kech qo'shilish mumkin (o'yin o'rtasida ham) — 0 ball bilan joriy savoldan davom etadi.
- Telefonda **faqat rangli shakllar** (qizil uchburchak, ko'k romb, sariq doira, yashil kvadrat) — savol va javob
  matni yuborilmaydi. Serverdan faqat savol raqami, variantlar soni, qolgan vaqt va shaxsiy natija keladi (xabarlar
  ~100 bayt); to'g'ri javob savol yopilgandan keyingina yuboriladi. O'quvchi sahifasi asosiy ilovani yuklamaydi
  (jami ~34 KB).
- Har savoldan keyin: to'g'ri/noto'g'ri, olingan ball, umumiy ball va o'rin.
- Birinchi qo'shilishda server o'yinchi ID va maxfiy token beradi — ular brauzerda (localStorage, bo'lmasa cookie)
  PIN bo'yicha saqlanadi. Sahifa yangilansa, aloqa uzilsa yoki oyna yopilib qayta ochilsa — o'sha o'yinchi (ism, ball,
  javoblar) davom etadi, dublikat yaratilmaydi. Shu token ikkinchi oynada ochilsa, yangi oyna egallaydi, eskisi
  xabar bilan yopiladi. Tokensiz kishi band ismni (hatto aloqasi uzilgan o'yinchinikini) ololmaydi.
- Aloqa uzilsa — avtomatik qayta ulanish (oraliq 0,4 s dan 5 s gacha oshib boradi), server joriy holatni (savol,
  qolgan vaqt, ball) qayta yuboradi. Aloqasiz bosilgan javob ulanish tiklanganda yuboriladi.

**Ball (har bir savol uchun, butun son):** to'g'ri javob — 500 + tezlik uchun 500 gacha, noto'g'ri yoki javobsiz — 0.
`ball = round((1 − (t / vaqt) / 2) × 1000)` — `t` javob vaqti (ms) **serverda** o'lchanadi: savol ochilgan paytdan
javob serverga yetib kelgan paytgacha (mijoz yuborgan vaqtga ishonilmaydi).
- 0,5 s gacha (shu jumladan aynan 0,5 s) javob — to'liq **1000** ball; vaqt oxirida — 500; yarmida — 750.
- Hisob aniq kasrlar bilan, faqat oxirida bir marta yaxlitlanadi (0,5 — yuqoriga). Funksiya: `app/octagon.py` →
  `calculate_score(is_correct, response_time_ms, timer_ms, max_points=1000)`.
- Har savolga bitta javob (birinchisi hisoblanadi). Server vaqti tugagach kelgan javob qabul qilinmaydi — tarmoq
  kechikishi o'quvchi hisobiga ketadi; shuning uchun telefondagi taymer o'lchangan kechikish (ping) bo'yicha biroz
  oldinroq tugaydi.
- Reytingda teng ball: kam umumiy javob vaqti (javobsiz savol — to'liq vaqt hisoblanadi), so'ng ism bo'yicha.

**4 tadan ko'p variantli savollar** (o'yinda ko'pi bilan 4 ta shakl): o'qituvchi tanlaydi — **qisqartirish**
(standart: to'g'ri javob + tasodifiy 3 ta noto'g'ri variant) yoki **o'yinga olmaslik**. 2 variantli (ha/yo'q) savollar
2 ta katta tugma bilan ko'rsatiladi.

**Cheklovlar:** o'yin holati server xotirasida (bitta server nusxasi uchun; Railway'da `numReplicas: 1`), ~2 soat
faolsiz qolgan o'yinlar o'chiriladi. Bitta o'yinda 300 tagacha o'quvchi; bitta o'qituvchida 5 tagacha tugallanmagan
va 5 tagacha tugagan (natijasi ko'rinadigan) o'yin — eskilari avtomatik yopiladi. Noto'g'ri PIN/token urinishlari
IP bo'yicha cheklangan (5 daqiqada 20 ta); bir daqiqada barcha IP lardan 300 tadan ko'p noto'g'ri urinish bo'lsa
(PIN taxmin qilish hujumi), har bir IP ga 5 ta qoladi. Bitta IP dan qo'shilish — 10 daqiqada 200 ta (maktab
tarmog'i uchun); ochiq ulanishlar — bitta IP dan 500 ta, jami 5000 ta (`TD_OCTAGON_MAX_SOCKETS`). WebSocket xabari
4 KB gacha, 10 soniyada 60 tagacha.

**Server qayta ishga tushsa** davom etayotgan Octagon o'yinlari yo'qoladi (ular faqat xotirada). Ulanishlar «server
to'xtadi» bilan yopiladi; o'quvchi telefoni qayta ulanib, «oldingi o'yindagi joyingiz topilmadi» va PIN topilmadi
degan xabarni ko'radi, o'qituvchi ekrani — «O'yin topilmadi» va «Yangi o'yin» tugmasi. O'qituvchi yangi o'yin ochadi.

**Xavfsizlik** (batafsil — [docs/octagon-audit.md](docs/octagon-audit.md)): o'yinni faqat egasi boshqaradi va har bir
boshqaruv amalida sessiya qayta tekshiriladi (tizimdan chiqilsa yoki parol tiklansa ochiq oynalar uziladi); javob
vaqti, to'g'riligi va ball faqat serverda; o'quvchi tokeni 192 bit, bazada emas, xotirada xesh ko'rinishida. Barcha
javoblarda xavfsizlik sarlavhalari: `Content-Security-Policy` (skriptlar faqat shu saytdan), `X-Frame-Options: DENY`,
`X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`.

## Balloon Pop — jamoaviy sinf o'yini

Har bir jamoaning odamchasi o'z rangidagi sharlarda akulalar ustida osilib turadi.
O'yinni o'qituvchi bitta ekranda boshqaradi (proyektor, interaktiv doska yoki kompyuter).

1. **Tosh, qaychi, qog'oz** — jamoalar sinfda o'ynaydi, o'qituvchi yutgan jamoani belgilaydi.
2. **Savol** — yutqazgan jamoa tanlangan mavzudan bitta savolga javob beradi.
3. **Zar** — yutgan jamoa birinchi bo'lib zar tashlaydi va raqibning tushgan son miqdoricha sharini portlatadi
   (sharlarni sichqoncha/barmoq bilan bosib yoki «Avtomatik portlatish» tugmasi bilan).
4. **Imkoniyat** — yutqazgan jamoa savolga to'g'ri javob bergan bo'lsa, u ham zar tashlaydi.
5. **Akulalar** — sharlari tugagan jamoa suvga tushadi va akulaga yem bo'ladi. Havoda qolgan jamoa g'olib.

**Yordamlar** — savolga javob berayotgan jamoa har biridan o'yinda **bir marta** foydalana oladi:

- **AI'dan so'rash** — jamoa savolni telefonidagi AI yordamchiga beradi (savol vaqtiga +30 soniya);
- **Guruhdan so'rash** — guruhdoshlar fikri so'raladi, masalan qo'l ko'tarib (+30 soniya);
- **50:50** — ikkita noto'g'ri javob olib tashlanadi.

Savol almashtirilsa («Boshqa savol») yoki tosh-qaychi-qog'oz qayta o'ynalsa («Orqaga»), shu savolda ishlatilgan
yordamlar jamoaga qaytariladi. Har bir jamoaning qolgan yordamlari tabloda ko'rinadi.

O'yin boshida tanlanadi: mavzu, ikki jamoaning nomi va rangi (8 ta rang), har bir jamoaga sharlar soni
(5 dan 50 gacha istalgan son — yozib kiritiladi yoki tayyor variantlardan tanlanadi) va savolga javob vaqti
(cheklovsiz, 20, 30 yoki 60 soniya).

- O'yin holati serverda saqlanadi — sahifa yangilansa yoki brauzer yopilsa ham o'yin davom etadi.
- Tosh-qaychi-qog'oz natijasi xato belgilansa — «Orqaga»; savol mos kelmasa — «Boshqa savol».
- O'yinni muddatidan oldin yakunlash mumkin: ko'proq shari qolgan jamoa g'olib bo'ladi.
- To'liq ekran rejimi (`F` tugmasi), klaviatura: `1`/`2` — tosh-qaychi-qog'oz g'olibi,
  `1–4` yoki `A–D` — javob, `Probel`/`Enter` — zar tashlash va davom etish.
- Oxirgi o'yinlar tarixi va «Qayta o'ynash» (xuddi shu sozlamalar bilan yangi o'yin).

## Boshqaruv paneli

Menyudagi **Boshqaruv** bo'limi faqat administratorlarga ko'rinadi (server ham barcha amallarni tekshiradi).

**Rollar:**

| Rol | Kim | Huquqlar |
|---|---|---|
| **Bosh administrator** (tizim egasi) | login `admin` (`TD_SUPERADMIN` bilan o'zgartirish mumkin) | hammasi: test mavzulari va **foydalanuvchilarni boshqarish** — yaratish, bloklash, parolni tiklash, admin qilish, o'chirish, ro'yxatdan o'tishni yopish |
| **Administrator** | bosh administrator tayinlagan foydalanuvchilar (birinchi ro'yxatdan o'tgan foydalanuvchi ham) | test mavzularini yuklash va boshqarish; o'qituvchi huquqlari; foydalanuvchilar ro'yxatini **faqat ko'rish** |
| **O'qituvchi** | bosh administrator tayinlagan foydalanuvchilar | «O'yinlar» paneli: Balloon Pop va Octagon o'yinlarini yaratish va o'tkazish |
| Foydalanuvchi | qolganlar | duel, o'rganish, reyting |

- **O'qituvchi rolini berish:** bosh administrator — «Boshqaruv» → «Foydalanuvchilar» → qatordagi «O'qituvchi qilish»
  tugmasi (yoki yangi akkaunt yaratishda «Rol: O'qituvchi»). Rol olib qo'yilsa, foydalanuvchining menyusi darhol
  yangilanadi va uning Octagon o'yinlari yopiladi. Eski bazalarga `users.is_teacher` ustuni ishga tushishda
  avtomatik qo'shiladi.
- «O'yinlar» bo'limi o'qituvchi bo'lmaganlarga menyuda ko'rinmaydi, to'g'ridan-to'g'ri havola (`#/games…`,
  eski `#/balloon`) bosh sahifaga qaytaradi, server esa o'yin yaratish/boshqarish so'rovlariga (REST va WebSocket)
  403 qaytaradi. O'quvchilarning qo'shilish sahifasi (`/play`) — ommaviy, menyuda yo'q.

- `admin` logini band qilingan: uni faqat **birinchi** foydalanuvchi sifatida ro'yxatdan o'tkazish mumkin. Yangi
  serverda birinchi bo'lib `admin` loginini ro'yxatdan o'tkazing.
- Server har safar ishga tushganda `admin` akkaunti administrator va bloklanmagan holatga keltiriladi.
- `TD_SUPERADMIN_PASSWORD` berilsa: `admin` akkaunti bo'lmasa — shu parol bilan yaratiladi, bor bo'lsa — paroli
  shu qiymatga tiklanadi (parol unutilganda yoki boshqa foydalanuvchi birinchi ro'yxatdan o'tib qo'ygan bo'lsa).

- **Umumiy ko'rinish** — foydalanuvchilar, onlayn, mavzular, duellar, mashg'ulotlar va Balloon Pop o'yinlari
  statistikasi; yangi foydalanuvchilar va so'nggi faollik.
- **Test mavzulari**
  - **Yangi mavzu** — nom berib bo'sh mavzu yaratish, keyin savollarni qo'shish;
  - `.txt` fayl yuklash — mavzu fayldagi savollar bilan birga yaratiladi (bir nechta faylni birdaniga);
  - mavzu sahifasida: savollarni **qo'lda qo'shish, tahrirlash va mavzudan olib tashlash** (ko'p variantli,
    2–10 variant, bitta to'g'ri javob), **bankdan tanlash**, **fayldan savol qo'shish** (mavzu oxiriga), fayl bilan
    almashtirish, `.txt` sifatida yuklab olish, nomini o'zgartirish, variantlarni aralashtirish;
  - **Faol / yopiq** — yopiq mavzu foydalanuvchilarga (duel, o'rganish, Balloon Pop) ko'rinmaydi va unda o'ynab
    bo'lmaydi; uni kutayotganlar navbatdan chiqariladi. Savoli yo'q mavzu ham ko'rinmaydi.
- **Savollar banki** — barcha savollar bir joyda; har bir savol bankda alohida saqlanadi va mavzularga
  *biriktiriladi* (bir savol bir nechta mavzuda bo'lishi mumkin):
  - qidiruv (savol va variant matni), mavzu bo'yicha filtr (shu jumladan «hech bir mavzuda yo'q»), sahifalash;
  - savollarni belgilash — sahifalar va filtrlar almashganda ham saqlanadi; `Shift` bilan oraliqni belgilash,
    «filtrdagi barchasini tanlash» (5000 tagacha);
  - tanlanganlarni **mavjud yoki yangi mavzuga qo'shish** — turli mavzulardagi savollardan aralash (takrorlash)
    mavzu tuzish mumkin; mavzuda bor savollar takrorlanmaydi;
  - savolni qo'lda qo'shish, `.txt` fayldan bankka yuklash (ixtiyoriy — mavzuga ham biriktirish), tahrirlash
    (o'zgarish savol biriktirilgan barcha mavzularda ko'rinadi), bankdan butunlay o'chirish (bittalab yoki
    tanlanganlarni);
  - bir xil savol (matn, variantlar va to'g'ri javob; bo'shliq va harf katta-kichikligi hisobga olinmaydi) qayta
    yuklansa bankda takrorlanmaydi — mavjudi ishlatiladi;
  - mavzu o'chirilsa yoki savol mavzudan olib tashlansa, savol bankda qoladi.
  - Eski bazalar ishga tushganda avtomatik ko'chiriladi (savol identifikatorlari saqlanadi, davom etayotgan
    o'yinlar buzilmaydi).
- **Foydalanuvchilar** — qidirish va saralash (adminlar, onlayn, bloklangan), **yangi akkaunt yaratish**
  (tasodifiy parol bilan), admin huquqini berish/olish, **bloklash** (foydalanuvchi darhol tizimdan chiqariladi va
  kira olmaydi), parolni tiklash, o'chirish.
- Uzun ro'yxatlar (mavzular, mavzu savollari, foydalanuvchilar — 50 tadan; bank — 30 tadan) sahifalarga bo'linadi.
- **Ro'yxatdan o'tishni yopish** — yopilganda yangi akkauntlarni faqat administrator yaratadi.

## Test fayli formati

```
Savol matni
====
Variant
====
#To'g'ri variant
====
Variant
++++
Keyingi savol
====
...
```

- savollar `++++` bilan ajratiladi;
- savol matni va variantlar `====` bilan ajratiladi;
- to'g'ri variant oldiga `#` qo'yiladi (variant matni o'zi `#` bilan boshlansa — `\#`, to'g'ri javob bo'lsa — `#\#`).

## Sozlamalar (muhit o'zgaruvchilari)

| O'zgaruvchi | Standart | Tavsif |
|---|---|---|
| `TD_HOST` | `0.0.0.0` | Tinglanadigan manzil |
| `TD_PORT` (yoki `PORT`) | `8080` | Port |
| `TD_DATA_DIR` | `./data` | Ma'lumotlar papkasi |
| `TD_DB_PATH` | `$TD_DATA_DIR/testduel.db` | SQLite fayli |
| `TD_ADMINS` | — | Vergul bilan ajratilgan loginlar; ro'yxatdan o'tganda admin bo'ladi |
| `TD_SUPERADMIN` | `admin` | Bosh administrator (tizim egasi) logini |
| `TD_SUPERADMIN_PASSWORD` | — | Berilsa: bosh administrator akkauntini yaratadi yoki parolini shu qiymatga tiklaydi |
| `TD_TRUST_PROXY` | — | `1` — teskari proksi (Nginx) ortida: mijoz IP manzili `X-Forwarded-For` dan olinadi (Railway'da avtomatik) |
| `TD_DUEL_QUESTIONS` | `15` | Dueldagi savollar soni |
| `TD_QUESTION_TIME` | `15` | Bitta savol uchun vaqt (soniya) |
| `TD_AFK_LIMIT` | `30` | Javobsiz qolish chegarasi (soniya) |
| `TD_DISCONNECT_GRACE` | `10` | Aloqa uzilganda qaytish uchun vaqt (soniya) |
| `TD_OCTAGON_READY` | `3` | Octagon: har bir savol oldidan «tayyorlaning» sanog'i (soniya) |
| `TD_OCTAGON_TTL` | `7200` | Octagon: faolsiz o'yin xotiradan o'chiriladigan vaqt (soniya) |
| `TD_OCTAGON_MAX_SOCKETS` | `5000` | Octagon: jami ochiq ulanishlar chegarasi |
| `TD_PUBLIC_URL` | — | Saytning ommaviy manzili (masalan, `https://quiz.maktab.uz`). Berilsa, QR kod va qo'shilish havolasi doim shu manzilga ishora qiladi |

Misol: `TD_PORT=9000 TD_ADMINS=bekzod python run.py`

## Railway'ga joylashtirish

Repozitoriyda `railway.json` (ishga tushirish buyrug'i, holat tekshiruvi) va `.python-version` bor.

1. [railway.com](https://railway.com) da GitHub orqali kiring → **New Project → Deploy from GitHub repo** → `bit_test`.
2. Servis sozlamalarida **Volume** qo'shing, mount path: `/data`.
3. **Variables** bo'limiga qo'shing: `TD_DATA_DIR=/data` (baza volume'da saqlanadi, qayta deploy qilinganda o'chmaydi).
   Ixtiyoriy: `TD_ADMINS=admin` — shu login bilan ro'yxatdan o'tgan foydalanuvchi admin bo'ladi.
4. **Settings → Networking → Generate Domain** — sayt manzili (`https://….up.railway.app`).
5. Saytni ochib birinchi bo'lib **`admin`** loginini ro'yxatdan o'tkazing — bu bosh administrator (tizim egasi).
   Yoki `TD_SUPERADMIN_PASSWORD` o'zgaruvchisini qo'shing — `admin` akkaunti avtomatik yaratiladi.

Bitta nusxa (replica) ishlashi kerak — `railway.json` da shunday sozlangan.

## Serverga joylashtirish

Ilova bitta jarayonda ishlaydi (duel holati xotirada saqlanadi), shuning uchun **bitta** nusxada ishga tushiring.
Nginx orqasida ishlatganda WebSocket uchun quyidagilarni qo'shing:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 3600s;
}
```

Taklif havolalari to'g'ri ishlashi uchun saytni domen orqali (HTTPS tavsiya etiladi) oching.
Nginx orqasida `TD_TRUST_PROXY=1` qo'ying — urinishlar cheklovi har bir foydalanuvchining haqiqiy IP manzili bo'yicha ishlaydi.

**Xavfsizlik:** barcha huquqlar serverda tekshiriladi; parollar scrypt bilan saqlanadi, sessiya tokenlari bazada
xesh ko'rinishida; boshqa saytlardan yuborilgan so'rovlar (CSRF) va WebSocket ulanishlari rad etiladi; API faqat
JSON qabul qiladi; boshqaruvdan tashqaridagi so'rovlar hajmi cheklangan; `admin` loginiga o'xshatib yozilgan
loginlar (masalan, kirillcha «а» bilan) ro'yxatdan o'tkazilmaydi.

## Testlar

```bash
pip install pytest
python -m pytest
```

- `tests/test_octagon.py` — ball hisoblash (0,5 s, yarim/to'liq vaqt, 1 ms chegaralari, turli vaqtlar), ismlar, o'yin
  dvigateli (soxta soat bilan: lobbi, vaqt, kech qo'shilish, qayta ulanish, ikkinchi oyna, band ism, o'quvchi
  xabarlarida matn yo'qligi, tozalash);
- `tests/test_octagon_api.py` — rollar va 403/401 (REST va WebSocket), `/play`, haqiqiy WebSocket orqali to'liq o'yin;
- `tests/test_octagon_security.py` va `tests/test_octagon.py` oxiridagi testlar — xavfsizlik auditi regressiyalari
  (IDOR, sessiya, CSRF/CORS, sarlavhalar, cheklovlar, poyga holatlari, server qayta ishga tushishi);
- `tests/test_qr.py` — QR kod kodlovchisi.

Brauzerdagi to'liq tekshiruv (Playwright; ilovaning o'ziga kerak emas):

```bash
npm i -D playwright && npx playwright install chromium
node e2e/octagon.e2e.js        # o'zi vaqtinchalik server ishga tushiradi; skrinshotlar: e2e/screenshots/
```

U rollarni, to'liq o'yinni (PIN/QR, kech qo'shilish, qayta ulanish, ikkinchi oyna, band ism, tarmoq uzilishi,
qo'shilishni yopish), o'quvchi xabarlarini, XSS (savol/variant/ism/mavzu nomidagi HTML faqat matn) va 360 / 375 / 768 /
1280 px kengliklarni (gorizontal siljish yo'q, tugmalar ≥ 48 px) tekshiradi; brauzer konsolidagi har qanday xato
(jumladan CSP buzilishi) testni yiqitadi.

## Loyiha tuzilishi

```
app/        backend (aiohttp): server, REST API, WebSocket, duel mexanizmi, Balloon Pop qoidalari, Octagon (app/octagon.py),
            QR kod (app/qr.py), rollar (app/roles.py), fayl parseri, SQLite
static/     frontend (HTML/CSS/JS; Balloon Pop sahnasi — static/js/balloon-scene.js;
            o'quvchilar sahifasi — static/play.html + static/js/play.js + static/css/play.css)
tests/      testlar (pytest)
e2e/        brauzer testlari (Playwright)
run.py      ishga tushirish nuqtasi
```
