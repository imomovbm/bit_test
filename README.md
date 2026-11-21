# TestDuel

Foydalanuvchilar o'rtasida test bo'yicha bellashuv (duel) va mustaqil mashq qilish uchun veb-ilova.

## Imkoniyatlar

- **Duel** — ikki foydalanuvchi bitta mavzuni tanlaydi, har biriga 15 ta savol beriladi, har bir savolga 15 soniya.
  - G'olib — ko'proq to'g'ri javob bergan; teng bo'lsa — tezroq javob bergan.
  - Raqib aloqasi uzilsa yoki 30 soniya davomida javob bermasa — ikkinchi ishtirokchi g'olib.
- **Taklif havolasi** — onlayn bo'lmagan do'stni duelga havola orqali chaqirish.
- **Mashq rejimi** — vaqt cheklovisiz 10 / 30 / 50 yoki barcha savollar.
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
| **Administrator** | bosh administrator tayinlagan foydalanuvchilar (birinchi ro'yxatdan o'tgan foydalanuvchi ham) | test mavzularini yuklash va boshqarish; foydalanuvchilar ro'yxatini **faqat ko'rish** |
| Foydalanuvchi | qolganlar | duel, o'rganish, Balloon Pop, reyting |

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
  - mavzu sahifasida: savollarni **qo'lda qo'shish, tahrirlash va o'chirish** (ko'p variantli, 2–10 variant,
    bitta to'g'ri javob), **fayldan savol qo'shish** (mavzu oxiriga), fayl bilan almashtirish, `.txt` sifatida
    yuklab olish, nomini o'zgartirish, variantlarni aralashtirish;
  - **Faol / yopiq** — yopiq mavzu foydalanuvchilarga (duel, o'rganish, Balloon Pop) ko'rinmaydi va unda o'ynab
    bo'lmaydi; uni kutayotganlar navbatdan chiqariladi. Savoli yo'q mavzu ham ko'rinmaydi.
- **Foydalanuvchilar** — qidirish va saralash (adminlar, onlayn, bloklangan), **yangi akkaunt yaratish**
  (tasodifiy parol bilan), admin huquqini berish/olish, **bloklash** (foydalanuvchi darhol tizimdan chiqariladi va
  kira olmaydi), parolni tiklash, o'chirish.
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

## Loyiha tuzilishi

```
app/        backend (aiohttp): server, REST API, WebSocket, duel mexanizmi, Balloon Pop qoidalari, fayl parseri, SQLite
static/     frontend (HTML/CSS/JS; Balloon Pop sahnasi — static/js/balloon-scene.js)
tests/      testlar
run.py      ishga tushirish nuqtasi
```
