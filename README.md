# TestDuel

Foydalanuvchilar o'rtasida test bo'yicha bellashuv (duel) va mustaqil mashq qilish uchun veb-ilova.

## Imkoniyatlar

- **Duel** — ikki foydalanuvchi bitta mavzuni tanlaydi, har biriga 15 ta savol beriladi, har bir savolga 15 soniya.
  - G'olib — ko'proq to'g'ri javob bergan; teng bo'lsa — tezroq javob bergan.
  - Raqib aloqasi uzilsa yoki 30 soniya davomida javob bermasa — ikkinchi ishtirokchi g'olib.
  - **Lobbi** — raqib kutayotganlar ro'yxati (taxallus, mavzu, kutish vaqti) va **bir bosishda qo'shilish**; mavzu
    tanlansa yoki «Istalgan mavzuda raqib topish» bosilsa — tezkor juftlash; «Hozir faol mavzular»; hammasi jonli
    (WebSocket). Bir vaqtda bosgan ikki kishidan faqat bittasi duelga kiradi.
  - **Mavzular katalogi** — «Qizg'in / Bugun / Hafta / Oy / Hammasi» bo'yicha reyting, qidiruv, cheksiz aylantirish
    (minglab mavzu bo'lsa ham hammasi birdaniga yuklanmaydi). Batafsil: [docs/scaling.md](docs/scaling.md).
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
- O'yin faqat **Boshlash** bosilganda boshlanadi. Bosqichlar (server boshqaradi, vaqtlar — `app/config.py`):
  `lobby → topic_intro (5 s) → question_read (5 s) → question_active (savol vaqti) → question_result → leaderboard →
  (keyingi savolni o'qish …) → oxirgi savol natijasi → podium_intro (3 s) → reveal_3rd (3,5 s) → reveal_2nd (3,5 s) →
  reveal_1st (6 s) → final_results`.
  - **Mavzu** (`topic_intro`, bir marta): mavzu nomi o'qituvchi va barcha o'quvchilar ekranida, sanoq bilan.
  - **O'qish** (`question_read`, har savol oldidan 5 s): savol matni **faqat o'qituvchi ekranida**; o'quvchilarda —
    rangli shakllar va sanoq, tugmalar hali bosilmaydi.
  - **Javoblar** (`question_active`): tugmalar ochiladi, taymer shu paytdan boshlanadi (ball ham shu paytdan o'lchanadi).
  - Natija (javoblar taqsimoti, to'g'ri javob) → **eng yaxshi 5 talik**: har qatorda o'rin, avatar, ism, umumiy ball,
    shu savolda olingan ball va o'rin o'zgarishi — `▲ 2` (yashil), `▼ 1` (qizil), `–` (o'zgarmadi), `YANGI` (keyin
    qo'shilgan o'quvchining birinchi reytingi); strelka va son har doim bor (faqat rang emas). Qatorlar eski joyidan
    yangisiga suriladi (~0,7 s, «kamroq harakat» sozlamasida — siljishsiz). Kimdir kamida 2 o'ringa ko'tarilsa —
    «Eng katta sakrash» qatori. 1-savoldan keyin strelka yo'q (oldingi reyting yo'q).
  - **G'oliblarni e'lon qilish** (oxirgi savoldan keyin reyting ko'rsatilmaydi — natija oldindan ma'lum bo'lmasin):
    «Va g'oliblar…» → 3-o'rin → 2-o'rin → 1-o'rin (ustun ko'tariladi, tushganda avatar, ism va ball chiqadi; 1-o'ringa
    yengil konfetti, faqat CSS) → **yakuniy natijalar**: podium, birinchi 10 tasi ajratilgan to'liq reyting (ism bo'yicha
    qidiruv), «Yangi o'yin», «O'yinlar paneli» va **CSV yuklab olish** (ism, avatar, ball, o'rin, to'g'ri javoblar).
    O'yinchilar 3 tadan kam bo'lsa — ortiqcha qadamlar tashlanadi; hech kim qolmasa — «O'yinda hech kim qolmadi».
    Qadamlar avtomatik o'tadi; «Keyingi o'rin» (Probel/Enter) tezlashtiradi, «Natijalarga o'tish» — darhol natijalar.
  Hamma javob bersa, savol vaqt tugashini kutmasdan yopiladi. «O'tkazib yuborish» (mavzu va o'qish bosqichlari),
  «Savolni yakunlash» va «Tugatish» (muddatidan oldin yakuniy natijalar) tugmalari bor. Probel/Enter — keyingi bosqich
  (bosib turilsa ham bitta amal), F — to'liq ekran. Bosqich boshlanishi va tugashi server vaqtida (Unix ms) yuboriladi;
  ekranlar soatlar farqini bir marta o'lchab, sanoqni shundan ko'rsatadi — qarorlar faqat serverda.
- PIN o'qituvchi va o'quvchi ekranining tepasida doim ko'rinib turadi. O'qituvchi sahifani yangilasa yoki aloqa uzilsa,
  o'sha o'yinni boshqarishda davom etadi.

**O'quvchi** (ro'yxatdan o'tmasdan): QR kodni skanerlaydi yoki `sayt/play` ni ochib PIN kiritadi, so'ng ism yozadi va
**avatar** tanlaydi (30 ta oddiy emoji: hayvonlar, mevalar, sport, buyumlar; bittasi tasodifiy tanlangan bo'ladi).
- Avatar lobbida almashtirilishi mumkin (o'yin boshlangach — yo'q), ism yonida hamma joyda ko'rinadi (lobbi, o'quvchi
  ekrani, natija, reyting, g'oliblar, yakuniy natijalar, o'qituvchi ekranlari), qayta ulanganda saqlanadi. Server faqat ro'yxatdagi
  indeksni qabul qiladi (simda emoji emas, raqam); bir xil avatar bir nechta o'quvchida bo'lishi mumkin.
- Ism: 1–20 belgi, o'yinda yagona (katta-kichik harf va o'xshash harflar hisobga olinmaydi); HTML, ko'rinmas belgilar,
  emoji va oddiy so'kinishlar filtrlanadi.
- Kech qo'shilish mumkin (o'yin o'rtasida ham) — 0 ball bilan joriy savoldan davom etadi.
- Telefonda **faqat rangli shakllar** (qizil sakkizburchak, ko'k tomchi, sariq yulduz, yashil plyus) — savol va javob
  matni yuborilmaydi. Serverdan faqat bosqich, savol raqami, variantlar soni, server vaqtlari va shaxsiy natija keladi
  (o'rtacha ~85 bayt); to'g'ri javob savol yopilgandan keyingina yuboriladi. O'quvchi sahifasi asosiy ilovani
  yuklamaydi: JS ~15 KB, CSS ~8 KB (gzip); sekin 4G va o'rta telefonda ~0,6 s da, takroriy ochilishda ~0,45 s da
  tayyor ([docs/performance.md](docs/performance.md)).
- Har savoldan keyin: to'g'ri/noto'g'ri, olingan ball, umumiy ball, o'rin va uning o'zgarishi («▲ 3 → 5-o'rin —
  3 o'ringa ko'tarildingiz», «▼ 2 → 8-o'rin», «– → 4-o'rin»); yuqoridagi o'quvchiga yaqin bo'lsa — «Ali sizdan 120
  ball oldinda». Telefonga faqat o'z o'rni, o'zgarishi va (yaqin bo'lsa) bitta qo'shnining ismi keladi.
- G'oliblar e'lon qilinayotganda telefonda «Kim podiumga chiqdi?» va e'lon qilinganlar ro'yxati; podiumdagi o'quvchi
  o'z o'rnini **aynan o'z o'rni e'lon qilinganda** ko'radi, qolganlar — yakuniy natijalarda. Server hali e'lon
  qilinmagan o'rinni hech kimga yubormaydi (o'qituvchi ekraniga ham).
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

**Dizayn:** to'q dengiz ko'ki sahna, sakkizburchak motivi (logotip — to'rtta javob rangidan tuzilgan sakkizburchak,
yuklanish belgisi, o'rin nishonlari va podium medallari). Ranglar va shakl ranglari bitta faylda —
`static/css/octagon-theme.css` (JS da rang qiymatlari yo'q); har bir rang o'z shakli bilan (rang yagona belgi emas),
kontrast WCAG AA bo'yicha tekshiriladi (`tests/test_octagon_theme.py`). Shakllar — inline SVG, ekranni o'quvchi
dasturlar uchun nomlari bor («Qizil sakkizburchak» va h.k.). Animatsiyalar qisqa va «kamroq harakat» sozlamasida
o'chadi. Ovoz standart holatda o'chiq (o'qituvchi ekranidagi tugma bilan yoqiladi; faqat brauzerda yaratiladigan
oddiy signal tovushlari).

**4 tadan ko'p variantli savollar** (o'yinda ko'pi bilan 4 ta shakl): o'qituvchi tanlaydi — **qisqartirish**
(standart: to'g'ri javob + tasodifiy 3 ta noto'g'ri variant) yoki **o'yinga olmaslik**. 2 variantli (ha/yo'q) savollar
2 ta katta tugma bilan ko'rsatiladi.

**Cheklovlar** (hammasi `TD_OCTAGON_*` o'zgaruvchilari bilan o'zgartiriladi, pastdagi jadval): o'yin holati server
xotirasida (bitta server nusxasi; Railway'da `numReplicas: 1`), ~2 soat faolsiz qolgan o'yinlar o'chiriladi. Bitta
o'yinda 300 tagacha o'quvchi; bitta o'qituvchida 5 tagacha tugallanmagan va 5 tagacha tugagan o'yin. Noto'g'ri
PIN/token urinishlari — IP bo'yicha 5 daqiqada 60 ta (bitta maktab tarmog'idagi sinf xatolari uchun); bir daqiqada
barcha IP lardan 300 tadan ko'p noto'g'ri urinish bo'lsa (PIN taxmin qilish hujumi), har bir IP ga 5 ta qoladi. Bitta
IP dan qo'shilish — 10 daqiqada 1000 ta (bir nechta to'liq sinf bitta NAT ortida); ochiq ulanishlar — bitta IP dan
500 ta, jami 5000 ta. WebSocket xabari 4 KB gacha, 10 soniyada 60 tagacha. Sig'im (bitta jarayon):
[docs/architecture.md](docs/architecture.md#capacity).

**Server qayta ishga tushsa** (yangi versiya joylashtirilganda) davom etayotgan Octagon o'yinlari **saqlanadi**:
to'xtashda ular diskka (bazaning yonida, faqat egasi o'qiy oladi) yoziladi, ekranlar «Server yangilanmoqda — o'yin
davom etadi» xabarini ko'rsatadi va avtomatik qayta ulanadi. Yangi jarayon o'yinlarni tiklaydi: o'sha bosqich, ballar,
avatarlar; server to'xtab turgan vaqt savol vaqtidan olinmaydi (pauza). Fayl 10 daqiqadan eski bo'lsa
(`TD_OCTAGON_RESTORE_MAX_AGE`) yoki server to'satdan o'chsa (SIGKILL, elektr) — o'yinlar yo'qoladi va hamma tushunarli
xabar oladi. Batafsil: [docs/runbook.md](docs/runbook.md).

**Versiyalar:** WebSocket qo'l berishida protokol versiyasi (`v: 2`) bor — joylashtirishdan oldin ochilgan eski sahifa
«Sayt yangilandi — sahifani yangilang» xabarini oladi (jim buzilmaydi); asosiy ilovada server javobidagi
`X-Release` boshqa bo'lsa, pastda «yangilash» eslatmasi chiqadi. Xabarlar formati:
[docs/architecture.md](docs/architecture.md#protocol).

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
    bo'lmaydi; uni kutayotganlar navbatdan chiqariladi (xabar bilan), boshlangan duellar oxirigacha davom etadi.
    Yopish yumshoq: savollar va tarix saqlanadi, istalgan vaqtda qayta ochish mumkin. Savoli yo'q mavzu ham ko'rinmaydi.
  - **Faollik** — ro'yxat serverda sahifalanadi: oxirgi o'yin, jami duellar, oxirgi 30 kundagi duellar, holat
    (saralash), filtrlar (holat, nom, «N kundan beri o'ynalmagan»: 30/60/90/180), belgilab **ommaviy yopish/ochish**
    (soni bilan tasdiqlash);
  - **O'chirishga tavsiya** — N kundan (standart 90) beri o'ynalmagan faol mavzular: bittalab bir bosishda yoki
    hammasini yopish; **Jurnal** — har bir holat o'zgarishi (kim, qachon, sabab); **avtomatik yopish** — ixtiyoriy,
    standart holatda o'chiq.
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

Barcha vaqtlar, chegaralar va bo'sag'alar bitta joyda — `app/config.py`. Ishga tushishda tekshiriladi: noto'g'ri
tur, ruxsat etilgan oraliqdan tashqari qiymat yoki bir-biriga zid sozlamalar (masalan, `TD_OCTAGON_JOIN_LIMIT` <
`TD_OCTAGON_MAX_PLAYERS`) bo'lsa — server ishga tushmaydi va **hamma** xatolar ro'yxatini chiqaradi. Joriy qiymatlarni
ko'rish (maxfiylari yashiriladi): `python run.py --check-config`.

| O'zgaruvchi | Standart | Tavsif |
|---|---|---|
| **Server** | | |
| `TD_DATA_DIR` | `./data` | Ma'lumotlar papkasi (baza, o'yinlar holati) |
| `TD_DB_PATH` | `$TD_DATA_DIR/testduel.db` | SQLite baza fayli |
| `TD_HOST` | `0.0.0.0` | Tinglanadigan manzil |
| `TD_PORT` (yoki `PORT`) | `8080` | Port (Railway: PORT) |
| `TD_ADMINS` | — | Ro'yxatdan o'tganda admin bo'ladigan loginlar (vergul bilan) |
| `TD_SUPERADMIN` | `admin` | Bosh administrator logini |
| `TD_SUPERADMIN_PASSWORD` | — | Bosh administrator paroli (yaratish/tiklash) |
| `TD_TRUST_PROXY` | `0` | X-Forwarded-* sarlavhalariga ishonish (proksi ortida) |
| `TD_DEV` | `0` | Ishlab chiquvchi rejimi: statik fayllar diskdan, keshsiz |
| `TD_SESSION_DAYS` | `30` | Kirish sessiyasi muddati (kun) |
| `TD_PUBLIC_URL` | — | Saytning ommaviy manzili (QR va qo'shilish havolasi uchun) |
| **Kuzatuv va ishlatish** | | |
| `TD_LOG_FORMAT` | `text` | Jurnal formati: text | json (har qator — bitta JSON obyekt) |
| `TD_LOG_LEVEL` | `INFO` | Jurnal darajasi |
| `TD_METRICS_TOKEN` | — | /metrics uchun Bearer token (bo'lmasa — faqat administratorlar) |
| `TD_ERROR_WEBHOOK` | — | Xatolar yuboriladigan webhook (JSON POST); bo'sh — faqat jurnal |
| `TD_SHUTDOWN_GRACE` | `5` | To'xtashda ochiq so'rovlarni kutish (soniya) |
| `TD_CLIENT_ERROR_LIMIT` | `30` | Brauzer xatosi hisobotlari: IP bo'yicha 10 daqiqada |
| **HTTP chegaralari** | | |
| `TD_LOGIN_FAIL_LIMIT` | `10` | Noto'g'ri parol: IP+login bo'yicha urinishlar |
| `TD_LOGIN_FAIL_WINDOW` | `600` | … shuncha soniyada |
| `TD_REGISTER_LIMIT` | `100` | Ro'yxatdan o'tish: IP bo'yicha |
| `TD_REGISTER_WINDOW` | `600` | … shuncha soniyada |
| **Duel** | | |
| `TD_DUEL_QUESTIONS` | `15` | Duelda har bir ishtirokchiga savollar soni |
| `TD_QUESTION_TIME` | `15` | Duel: bitta savol uchun vaqt (soniya) |
| `TD_AFK_LIMIT` | `30` | Duel: shuncha soniya javob bermasa — mag'lub |
| `TD_DISCONNECT_GRACE` | `10` | Duel: aloqa uzilsa, qaytish uchun vaqt (soniya) |
| **Mavzular faolligi, reyting, lobbi** | | |
| `TD_TZ_OFFSET_HOURS` | `5` | Kunlik hisoblar vaqt mintaqasi (Toshkent: UTC+5) |
| `TD_HOT_WINDOW_DAYS` | `14` | «Qizg'in» reyting oynasi (kun) |
| `TD_HOT_HALF_LIFE_DAYS` | `2` | «Qizg'in» reyting yarim yemirilishi (kun) |
| `TD_HOT_LIVE_WEIGHT` | `3` | Hozir o'ynayotganlar og'irligi |
| `TD_RANKING_TTL` | `30` | Reyting ro'yxatlari keshi (soniya) |
| `TD_RANKING_REFRESH` | `5` | Yangi duel boshlangach reyting eng tez yangilanishi (soniya) |
| `TD_SEEK_TTL` | `120` | Raqib kutish muddati (soniya) |
| `TD_SUGGEST_IDLE_DAYS` | `90` | Shuncha kun o'ynalmagan mavzular o'chirishga tavsiya qilinadi |
| **Octagon** | | |
| `TD_OCTAGON_INTRO` | `5` | «Boshlash»dan keyin mavzu nomi hamma ekranda (soniya) |
| `TD_OCTAGON_READ` (eski nomi: `TD_OCTAGON_READY`) | `5` | Savolni o'qish vaqti: matn faqat o'qituvchida, tugmalar yopiq (soniya) |
| `TD_OCTAGON_PODIUM_INTRO` | `3` | Oxirgi savoldan keyin «Va g'oliblar…» ekrani (soniya) |
| `TD_OCTAGON_REVEAL_STEP` | `3.5` | Podium: 3- va 2-o'rin ochilgandan keyingi pauza (soniya) |
| `TD_OCTAGON_REVEAL_WINNER` | `6` | Podium: 1-o'rin ekrani, keyin to'liq natijalar (soniya) |
| `TD_OCTAGON_TIME_MIN` | `5` | Savol vaqti: eng kami (soniya) |
| `TD_OCTAGON_TIME_MAX` | `120` | Savol vaqti: eng ko'pi (soniya) |
| `TD_OCTAGON_TIME_DEFAULT` | `20` | Savol vaqti: standart (soniya) |
| `TD_OCTAGON_MAX_QUESTIONS` | `100` | Bitta o'yindagi eng ko'p savollar |
| `TD_OCTAGON_DEFAULT_QUESTIONS` | `10` | Savollar soni: standart |
| `TD_OCTAGON_MAX_PLAYERS` | `300` | Bitta o'yindagi eng ko'p o'quvchilar |
| `TD_OCTAGON_MAX_GAMES_PER_TEACHER` | `5` | O'qituvchining bir vaqtdagi o'yinlari |
| `TD_OCTAGON_MAX_FINISHED_PER_TEACHER` | `5` | Xotirada saqlanadigan tugagan o'yinlar (o'qituvchiga) |
| `TD_OCTAGON_MAX_GAMES` | `500` | Serverdagi jami o'yinlar |
| `TD_OCTAGON_MAX_SOCKETS` | `5000` | Jami ochiq o'quvchi/o'qituvchi ulanishlari |
| `TD_OCTAGON_MAX_SOCKETS_PER_IP` | `500` | Bitta IP dan ulanishlar (maktab NAT) |
| `TD_OCTAGON_FAIL_LIMIT` | `60` | Noto'g'ri PIN/token urinishlari: IP bo'yicha |
| `TD_OCTAGON_FAIL_WINDOW` | `300` | … shuncha soniyada |
| `TD_OCTAGON_GLOBAL_FAIL_LIMIT` | `300` | Barcha IP lardan noto'g'ri urinishlar — PIN taxmin hujumi belgisi |
| `TD_OCTAGON_GLOBAL_FAIL_WINDOW` | `60` | … shuncha soniyada |
| `TD_OCTAGON_SURGE_FAIL_LIMIT` | `5` | Hujum paytida bitta IP ga ruxsat etilgan noto'g'ri urinishlar |
| `TD_OCTAGON_JOIN_LIMIT` | `1000` | Yangi o'yinchilar: IP bo'yicha (≥ o'yindagi eng ko'p o'quvchilar) |
| `TD_OCTAGON_JOIN_WINDOW` | `600` | … shuncha soniyada |
| `TD_OCTAGON_HOST_FLUSH` | `0.25` | O'qituvchi ekrani yangilanishi: kichik o'yinlar (soniya) |
| `TD_OCTAGON_HOST_FLUSH_BIG` | `1` | … katta o'yinlar (soniya) |
| `TD_OCTAGON_HOST_FLUSH_BIG_FROM` | `40` | Katta o'yin: o'quvchilar soni shundan ko'p |
| `TD_OCTAGON_TTL` | `7200` | Faolsiz o'yin xotiradan o'chiriladi (soniya) |
| `TD_OCTAGON_SWEEP_EVERY` | `60` | Eskirgan o'yinlarni tozalash oralig'i (soniya) |
| `TD_OCTAGON_RESTORE_MAX_AGE` | `600` | Qayta ishga tushishda saqlangan o'yinlar tiklanadi, agar shundan yangi bo'lsa (soniya; 0 — tiklanmaydi) |
| **WebSocket** | | |
| `TD_WS_OCTAGON_MAX_MESSAGE` | `4096` | /ws/octagon: bitta xabarning eng katta hajmi (bayt) |
| `TD_WS_OCTAGON_FLOOD_LIMIT` | `60` | /ws/octagon: 10 soniyada eng ko'p xabar |
| `TD_WS_DUEL_FLOOD_LIMIT` | `120` | /ws: 10 soniyada eng ko'p xabar |

Misol: `TD_PORT=9000 TD_ADMINS=bekzod TD_OCTAGON_READ=7 python run.py`

## Railway'ga joylashtirish

Repozitoriyda `railway.json` (ishga tushirish buyrug'i, holat tekshiruvi — `/healthz`) va `.python-version` bor.

1. [railway.com](https://railway.com) da GitHub orqali kiring → **New Project → Deploy from GitHub repo** → `bit_test`.
2. Servis sozlamalarida **Volume** qo'shing, mount path: `/data`.
3. **Variables** bo'limiga qo'shing: `TD_DATA_DIR=/data` (baza va qayta ishga tushishda saqlanadigan Octagon o'yinlari
   volume'da — qayta deploy qilinganda o'chmaydi).
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

## Ishlatish (production)

- **Holat tekshiruvi:** `GET /healthz` → `{"status":"ok","release":"…","uptimeS":…}` (baza ham tekshiriladi; to'xtash
  paytida — 503).
- **Ko'rsatkichlar:** `GET /metrics` (Prometheus matni, `Authorization: Bearer $TD_METRICS_TOKEN`) yoki administrator
  uchun `GET /api/admin/metrics` (JSON): faol o'yinlar, ulangan o'quvchilar, xabarlar soni, xatolar, p50/p95 kechikishlar.
- **Jurnal:** `TD_LOG_FORMAT=json` — har qator bitta JSON obyekt. Jurnalda ism, login, token, IP va savol matni
  yo'q — faqat identifikatorlar va sonlar. Xatolar `TD_ERROR_WEBHOOK` ga ham yuborilishi mumkin (brauzerdagi xatolar ham).
- **To'xtash:** SIGTERM/Ctrl+C — Octagon o'yinlari saqlanadi va qayta ishga tushganda davom etadi (yuqorida).
- **Zaxira:** `python3 scripts/db_tool.py backup data/testduel.db zaxira.db` (ishlab turgan server bilan ham xavfsiz);
  yangi versiyadan oldin nusxada tekshirish: `python3 scripts/db_tool.py check zaxira.db`.
- **Qo'llanma** (joylashtirish, orqaga qaytarish, nosozliklar): [docs/runbook.md](docs/runbook.md); arxitektura,
  protokol va saqlash qoidalari: [docs/architecture.md](docs/architecture.md), [docs/performance.md](docs/performance.md).

## Testlar

```bash
pip install pytest pyflakes mypy
python -m pytest            # birlik, API, WebSocket, xavfsizlik, kesh, tamper, qayta ishga tushish testlari
bash scripts/lint.sh        # pyflakes + ESLint (npx orqali) + node --check
mypy                        # sof modullar: bosqichlar mashinasi, ball, sozlamalar, statik fayllar, kuzatuv
python scripts/bundle_budget.py   # JS/CSS hajmi byudjeti (o'quvchi sahifasi JS ≤ 20 KB gzip, qat'iy chegara 100 KB)
```

CI (`.github/workflows/ci.yml`) har bir push va PR da: lint, tur tekshiruvi, `--check-config`, pytest, hajm byudjeti,
`pip-audit` (zaifliklar) va brauzer E2E testlari. Kenglik tekshiruvlari shriftga bog'liq: CI dagi shrift (DejaVu Sans)
bilan mahalliy tekshirish — `FONTCONFIG_FILE=e2e/fonts-ci.conf node e2e/octagon.e2e.js`.

- `tests/test_octagon.py` — ball hisoblash (0,5 s, yarim/to'liq vaqt, 1 ms chegaralari, turli vaqtlar), ismlar, o'yin
  dvigateli (soxta soat bilan: lobbi, vaqt, kech qo'shilish, qayta ulanish, ikkinchi oyna, band ism, o'quvchi
  xabarlarida matn yo'qligi, tozalash);
- `tests/test_octagon_api.py` — rollar va 403/401 (REST va WebSocket), `/play`, haqiqiy WebSocket orqali to'liq o'yin;
- `tests/test_octagon_security.py` va `tests/test_octagon.py` oxiridagi testlar — xavfsizlik auditi regressiyalari
  (IDOR, sessiya, CSRF/CORS, sarlavhalar, cheklovlar, poyga holatlari, server qayta ishga tushishi);
- `tests/test_octagon_flow.py`, `tests/test_octagon_avatars.py`, `tests/test_octagon_v2_audit.py` — v2: bosqichlar
  mashinasi (har bir o'tish, vaqtlar, noqonuniy o'tishlar), avatarlar, protokol versiyasi, chegaralar, audit topilmalari
  ([docs/octagon-v2-audit.md](docs/octagon-v2-audit.md));
- `tests/test_octagon_restart.py`, `tests/test_tamper.py`, `tests/test_http_cache.py`, `tests/test_config.py`,
  `tests/test_observability.py`, `tests/test_i18n_strings.py` — qayta ishga tushishda saqlash, qurilmadagi
  ma'lumotlarni o'zgartirish, kesh/siqish, sozlamalar tekshiruvi, ko'rsatkichlar va jurnal, matnlar jadvali;
- `tests/test_qr.py` — QR kod kodlovchisi;
- `tests/test_activity.py`, `tests/test_catalog.py`, `tests/test_lobby.py`, `tests/test_admin_topics.py`,
  `tests/test_leaderboard_stats.py` — mavzular faolligi (parallel yozish, backfill, migratsiya), reyting va «qizg'in»
  formula, lobbi va juftlash (bir vaqtda qo'shilish), boshqaruv vositalari (403/401), reyting yig'indisi.

Brauzerdagi to'liq tekshiruv (Playwright; ilovaning o'ziga kerak emas):

```bash
npm i -D playwright && npx playwright install chromium
node e2e/octagon.e2e.js        # o'zi vaqtinchalik server ishga tushiradi; skrinshotlar: e2e/screenshots/
```

U rollarni, to'liq o'yinni (PIN/QR, kech qo'shilish, qayta ulanish, ikkinchi oyna, band ism, tarmoq uzilishi,
qo'shilishni yopish), o'quvchi xabarlarini, XSS (savol/variant/ism/mavzu nomidagi HTML faqat matn) va 360 / 375 / 768 /
1280 px kengliklarni (gorizontal siljish yo'q, tugmalar ≥ 48 px) tekshiradi; brauzer konsolidagi har qanday xato
(jumladan CSP buzilishi) testni yiqitadi.

```bash
node e2e/lobby.e2e.js          # duel bosh sahifasi: jonli lobbi -> qo'shilish -> duel -> «Bugun» reytingi, poyga, boshqaruv
python3 scripts/loadtest.py    # yuklama sinovi: 5 000 mavzu, 20 000 foydalanuvchi, bir yillik duellar, 500 o'yinchi
python3 scripts/octagon_load.py    # Octagon: 20 ta o'yin bir vaqtda, eng kattasida 300 o'quvchi (p95, xotira, xatolar)
node scripts/perf-routes.js        # sahifalar: sekin 4G + 4x sekin protsessor, birinchi va takroriy ochilish
python3 scripts/loadtest.py --explain   # asosiy so'rovlarning EXPLAIN QUERY PLAN natijalari
```

Natijalar va cheklovlar: [docs/scaling.md](docs/scaling.md).

## Masshtab: mavzular faolligi, reyting va lobbi

- Duel boshlanganda (sanoq tugagach) mavzuning oxirgi o'yini, duellar soni va kunlik yig'indisi bitta qisqa
  tranzaksiyada yoziladi; reytinglar faqat shu yig'indidan hisoblanadi (duellar jadvali sanalmaydi) va xotirada
  keshlanadi (≤ 30 s eskirishi mumkin; jonli kutish/o'ynash sonlari ≤ 1 s).
- Yangi ustunlar va jadvallar ilova birinchi ishga tushganda avtomatik qo'shiladi va mavjud duellar tarixidan
  to'ldiriladi (550 ming duelda ~3 soniya). Qo'lda qayta hisoblash va tekshirish:

  ```bash
  python -m app.backfill --db data/testduel.db --dry-run   # bazaning nusxasida (asl faylga tegmaydi)
  python -m app.backfill --db data/testduel.db             # yozish (idempotent, bitta tranzaksiya)
  ```

- Ilova **bitta nusxada** ishlaydi (lobbi va duellar holati jarayon xotirasida) — bir nechta nusxa ortida
  ishlatish qo'llab-quvvatlanmaydi.

## Loyiha tuzilishi

```
app/        backend (aiohttp): server, REST API, WebSocket, duel mexanizmi, Balloon Pop qoidalari, Octagon (app/octagon.py;
            bosqichlar — app/octagon_flow.py, ball — app/octagon_scoring.py), sozlamalar (app/config.py), statik
            fayllar va kesh (app/assets.py), kuzatuv (app/observability.py), ishlatish (app/ops.py), QR kod, rollar, SQLite
static/     frontend (HTML/CSS/JS; Balloon Pop sahnasi — static/js/balloon-scene.js;
            o'quvchilar sahifasi — static/play.html + static/js/play.js + static/css/play.css)
tests/      testlar (pytest)
e2e/        brauzer testlari (Playwright)
scripts/    yuklama va tezlik sinovlari, lint, hajm byudjeti, baza zaxirasi (db_tool.py)
docs/       hujjatlar: architecture.md, runbook.md, performance.md, octagon-v2-audit.md, octagon-audit.md, scaling.md
run.py      ishga tushirish nuqtasi
```
