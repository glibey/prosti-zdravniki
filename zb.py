"""Prosti zdravniki → Telegram alerts (Slovenia).

Polls Sledilnik's daily mirror of ZZZS open data (which doctors accept new patients) and notifies
subscribers when a doctor of their chosen type in their municipality (optionally + radius) starts accepting.

Env: TG_TOKEN (without it: dry-run, alerts printed), OWNER_CHAT (gets /stats + errors), POLL_MIN (default 30).
Run: python3 zb.py            # bot + poller
     python3 zb.py --diff SHA  # print what alerts would fire between commit SHA and today's data
Deep links: t.me/<bot>?start=<type>_<muni-slug> subscribes in one tap; ?start=m_<muni-slug> preselects the municipality.
"""
import csv, io, json, math, os, re, sqlite3, sys, threading, time, unicodedata, urllib.error, urllib.parse, urllib.request

_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env):
    for _l in open(_env):
        if "=" in _l and not _l.startswith("#"):
            os.environ.setdefault(*_l.strip().split("=", 1))

RAW = "https://raw.githubusercontent.com/sledilnik/zdravniki-data/{ref}/csv/{f}"
TOKEN = os.environ.get("TG_TOKEN")
OWNER = int(os.environ.get("OWNER_CHAT", 0))
POLL = float(os.environ.get("POLL_MIN", 30)) * 60
ICON = {"gp": "🩺", "ped": "🧸", "gyn": "🌸", "den": "🦷", "den-y": "🦷", "den-s": "🎓"}
TYPE_NAMES = {  # lang: type: (label, plural)
    "sl": {"gp": ("Družinski zdravnik", "družinski zdravniki"), "ped": ("Pediater", "pediatri"),
           "gyn": ("Ginekolog", "ginekologi"), "den": ("Zobozdravnik", "zobozdravniki"),
           "den-y": ("Zobozdravnik za mladino", "zobozdravniki za mladino"),
           "den-s": ("Zobozdravnik za študente", "zobozdravniki za študente")},
    "en": {"gp": ("Family doctor (GP)", "family doctors"), "ped": ("Paediatrician", "paediatricians"),
           "gyn": ("Gynaecologist", "gynaecologists"), "den": ("Dentist", "dentists"),
           "den-y": ("Dentist for children/youth", "youth dentists"),
           "den-s": ("Dentist for students", "student dentists")},
    "uk": {"gp": ("Сімейний лікар", "сімейні лікарі"), "ped": ("Педіатр", "педіатри"),
           "gyn": ("Гінеколог", "гінекологи"), "den": ("Стоматолог", "стоматологи"),
           "den-y": ("Дитячий стоматолог", "дитячі стоматологи"),
           "den-s": ("Стоматолог для студентів", "стоматологи для студентів")},
    "ru": {"gp": ("Семейный врач", "семейные врачи"), "ped": ("Педиатр", "педиатры"),
           "gyn": ("Гинеколог", "гинекологи"), "den": ("Стоматолог", "стоматологи"),
           "den-y": ("Детский стоматолог", "детские стоматологи"),
           "den-s": ("Стоматолог для студентов", "стоматологи для студентов")},
}
TYPES = {t: (f"{ICON[t]} {l}", p) for t, (l, p) in TYPE_NAMES["sl"].items()}  # used by gen_site.py
LANGS = {"sl": "🇸🇮 Slovenščina", "en": "🇬🇧 English", "uk": "🇺🇦 Українська", "ru": "Русский"}
S = {
    "welcome": {
        "sl": "Pozdravljeni! 👋\n\nTa bot vas <b>obvesti, ko zdravnik v vaši občini začne sprejemati nove paciente</b> (podatki ZZZS, preverjeni vsak dan).\n\nIzberite vrsto zdravnika:",
        "en": "Hi! 👋\n\nThis bot <b>notifies you when a doctor in your Slovenian municipality starts accepting new patients</b> (ZZZS data, checked daily).\n\nChoose the type of doctor:",
        "uk": "Вітаю! 👋\n\nЦей бот <b>повідомить, коли лікар у вашій громаді Словенії почне приймати нових пацієнтів</b> (дані ZZZS, перевірка щодня).\n\nОберіть тип лікаря:",
        "ru": "Здравствуйте! 👋\n\nЭтот бот <b>сообщит, когда врач в вашей общине Словении начнёт принимать новых пациентов</b> (данные ZZZS, проверка каждый день).\n\nВыберите тип врача:"},
    "choose_type": {"sl": "Izberite vrsto zdravnika:", "en": "Choose the type of doctor:",
                    "uk": "Оберіть тип лікаря:", "ru": "Выберите тип врача:"},
    "muni_type": {"sl": "📍 <b>{muni}</b>\n\nIzberite vrsto zdravnika:", "en": "📍 <b>{muni}</b>\n\nChoose the type of doctor:",
                  "uk": "📍 <b>{muni}</b>\n\nОберіть тип лікаря:", "ru": "📍 <b>{muni}</b>\n\nВыберите тип врача:"},
    "ask_muni": {"sl": "{type} ✔️\n\nNapišite <b>občino ali kraj</b> (npr. Maribor):",
                 "en": "{type} ✔️\n\nType your <b>municipality or town</b> (e.g. Maribor):",
                 "uk": "{type} ✔️\n\nНапишіть <b>громаду або місто</b> (напр. Maribor):",
                 "ru": "{type} ✔️\n\nНапишите <b>общину или город</b> (напр. Maribor):"},
    "no_muni": {"sl": "Te občine ne najdem 🤔 Poskusite drugače (npr. <i>Maribor</i>, <i>Ljubljana</i>, <i>Ptuj</i>).",
                "en": "I can't find that municipality 🤔 Try another spelling (e.g. <i>Maribor</i>, <i>Ljubljana</i>, <i>Ptuj</i>).",
                "uk": "Не знаходжу таку громаду 🤔 Спробуйте інакше (напр. <i>Maribor</i>, <i>Ljubljana</i>, <i>Ptuj</i>).",
                "ru": "Не нахожу такую общину 🤔 Попробуйте иначе (напр. <i>Maribor</i>, <i>Ljubljana</i>, <i>Ptuj</i>)."},
    "which_muni": {"sl": "Katero občino ste mislili?", "en": "Which municipality did you mean?",
                   "uk": "Яку громаду ви мали на увазі?", "ru": "Какую общину вы имели в виду?"},
    "ask_radius": {"sl": "<b>{muni}</b> — samo občina ali tudi okolica?", "en": "<b>{muni}</b> — just this municipality or the surroundings too?",
                   "uk": "<b>{muni}</b> — тільки ця громада чи й околиці?", "ru": "<b>{muni}</b> — только эта община или и окрестности?"},
    "only_muni": {"sl": "Samo občina", "en": "Only here", "uk": "Тільки тут", "ru": "Только здесь"},
    "plus_km": {"sl": "+ okolica {r} km", "en": "+ {r} km around", "uk": "+ {r} км навколо", "ru": "+ {r} км вокруг"},
    "sub_on": {"sl": "🔔 Opozorilo vklopljeno: {what}.", "en": "🔔 Alert is on: {what}.",
               "uk": "🔔 Сповіщення увімкнено: {what}.", "ru": "🔔 Уведомление включено: {what}."},
    "help": {"sl": "/moja — vaša opozorila · /start — dodaj novo · /zdaj — kdo sprejema zdaj · /kmalu — kdo bo morda kmalu · /blizu — najbližji · /jezik — jezik",
             "en": "/moja — my alerts · /start — add another · /zdaj — accepting now · /kmalu — likely to open soon · /blizu — nearest to me · /jezik — language",
             "uk": "/moja — мої сповіщення · /start — додати ще · /zdaj — хто приймає зараз · /kmalu — хто може відкритися скоро · /blizu — найближчі · /jezik — мова",
             "ru": "/moja — мои уведомления · /start — добавить ещё · /zdaj — кто принимает сейчас · /kmalu — кто может открыться скоро · /blizu — ближайшие · /jezik — язык"},
    "none_now": {"sl": "Trenutno v {where} <b>ni</b> prostih ({plural}). Obvestilo dobite, ko se to spremeni.",
                 "en": "Right now there are <b>no</b> {plural} accepting in {where}. You'll get a message when that changes.",
                 "uk": "Зараз у {where} <b>немає</b> вільних ({plural}). Ви отримаєте повідомлення, коли це зміниться.",
                 "ru": "Сейчас в {where} <b>нет</b> свободных ({plural}). Вы получите сообщение, когда это изменится."},
    "now_list": {"sl": "✅ Trenutno sprejemajo ({plural}, {where}):", "en": "✅ Accepting now ({plural}, {where}):",
                 "uk": "✅ Зараз приймають ({plural}, {where}):", "ru": "✅ Сейчас принимают ({plural}, {where}):"},
    "more": {"sl": "…in še {n}. Vse na zdravniki.sledilnik.org", "en": "…and {n} more. All on zdravniki.sledilnik.org",
             "uk": "…і ще {n}. Усі на zdravniki.sledilnik.org", "ru": "…и ещё {n}. Все на zdravniki.sledilnik.org"},
    "no_subs": {"sl": "Nimate naročil. /start za novo.", "en": "You have no alerts. /start to add one.",
                "uk": "У вас немає сповіщень. /start — додати.", "ru": "У вас нет уведомлений. /start — добавить."},
    "your_subs": {"sl": "Vaša opozorila (kliknite za izbris):", "en": "Your alerts (tap to delete):",
                  "uk": "Ваші сповіщення (натисніть, щоб видалити):", "ru": "Ваши уведомления (нажмите, чтобы удалить):"},
    "alert": {"sl": "🔔 <b>Nov prost zdravnik!</b> Sprejema nove paciente:", "en": "🔔 <b>New doctor available!</b> Now accepting new patients:",
              "uk": "🔔 <b>З'явився вільний лікар!</b> Приймає нових пацієнтів:", "ru": "🔔 <b>Появился свободный врач!</b> Принимает новых пациентов:"},
    "footer": {"sl": "<i>Podatki ZZZS (prek Sledilnika), osveženo enkrat dnevno. Pred obiskom pokličite ambulanto.</i>",
               "en": "<i>ZZZS data (via Sledilnik), updated daily. Call the clinic before you go.</i>",
               "uk": "<i>Дані ZZZS (через Sledilnik), оновлюються щодня. Перед візитом зателефонуйте в амбулаторію.</i>",
               "ru": "<i>Данные ZZZS (через Sledilnik), обновляются ежедневно. Перед визитом позвоните в амбулаторию.</i>"},
    "soon_head": {"sl": "⏳ <b>Kdo bo morda kmalu sprejemal</b> ({plural}, {where})\n\nNajmanj obremenjeni zdravniki, ki trenutno ne sprejemajo. Zgodovinsko taki odprejo vpis 3–10× pogosteje kot ostali — ni pa zagotovila.",
                  "en": "⏳ <b>Who may open soon</b> ({plural}, {where})\n\nLeast-loaded doctors that are not accepting yet. Historically these open 3–10× more often than the rest — no guarantee.",
                  "uk": "⏳ <b>Хто може скоро відкрити запис</b> ({plural}, {where})\n\nНайменш завантажені лікарі, які зараз не приймають. За історією такі відкриваються в 3–10 разів частіше за інших — але без гарантії.",
                  "ru": "⏳ <b>Кто может скоро открыть запись</b> ({plural}, {where})\n\nНаименее загруженные врачи, которые сейчас не принимают. По истории такие открываются в 3–10 раз чаще остальных — но без гарантии."},
    "load": {"sl": "obremenjenost {p}% povprečja", "en": "load {p}% of average", "uk": "завантаженість {p}% від середньої",
             "ru": "загруженность {p}% от средней"},
    "soon_none": {"sl": "Ni podatkov za {where}.", "en": "No data for {where}.", "uk": "Немає даних для {where}.", "ru": "Нет данных для {where}."},
    "choose_lang": {"sl": "Izberite jezik:", "en": "Choose language:", "uk": "Оберіть мову:", "ru": "Выберите язык:"},
    "lang_set": {"sl": "Jezik: slovenščina ✔️", "en": "Language: English ✔️", "uk": "Мова: українська ✔️", "ru": "Язык: русский ✔️"},
    "near_type": {"sl": "📍 Katere vrste zdravnika iščete v bližini?", "en": "📍 Which type of doctor are you looking for nearby?",
                  "uk": "📍 Якого лікаря шукаєте поруч?", "ru": "📍 Какого врача ищете рядом?"},
    "near_ask": {"sl": "Pritisnite gumb spodaj in delite lokacijo — pokažem najbližje, ki sprejemajo.",
                 "en": "Tap the button below to share your location — I'll show the nearest ones accepting patients.",
                 "uk": "Натисніть кнопку нижче й надішліть локацію — покажу найближчих, хто приймає.",
                 "ru": "Нажмите кнопку ниже и отправьте локацию — покажу ближайших, кто принимает."},
    "near_btn": {"sl": "📍 Pošlji mojo lokacijo", "en": "📍 Send my location", "uk": "📍 Надіслати локацію", "ru": "📍 Отправить локацию"},
    "near_head": {"sl": "📍 Najbližji, ki sprejemajo ({plural}):", "en": "📍 Nearest accepting ({plural}):",
                  "uk": "📍 Найближчі, хто приймає ({plural}):", "ru": "📍 Ближайшие, кто принимает ({plural}):"},
    "near_none": {"sl": "V 50 km ni nikogar, ki bi sprejemal ({plural}).", "en": "No {plural} accepting within 50 km.",
                  "uk": "У радіусі 50 км ніхто не приймає ({plural}).", "ru": "В радиусе 50 км никто не принимает ({plural})."},
    "share": {"sl": "📤 Deli s prijatelji", "en": "📤 Share with friends", "uk": "📤 Поділитися", "ru": "📤 Поделиться"},
    "share_text": {"sl": "Bot te obvesti, ko zdravnik v tvoji občini začne sprejemati nove paciente",
                   "en": "This bot tells you when a doctor in your Slovenian municipality starts accepting new patients",
                   "uk": "Бот повідомляє, коли лікар у твоїй громаді Словенії почне приймати нових пацієнтів",
                   "ru": "Бот сообщает, когда врач в твоей общине Словении начнёт принимать новых пациентов"},
}
COMMANDS = {
    "sl": [("start", "Novo opozorilo"), ("moja", "Moja opozorila"), ("zdaj", "Kdo sprejema zdaj"), ("kmalu", "Kdo bo morda kmalu"), ("blizu", "Najbližji meni"), ("jezik", "Jezik")],
    "en": [("start", "New alert"), ("moja", "My alerts"), ("zdaj", "Accepting now"), ("kmalu", "Likely to open soon"), ("blizu", "Nearest to me"), ("jezik", "Language")],
    "uk": [("start", "Нове сповіщення"), ("moja", "Мої сповіщення"), ("zdaj", "Хто приймає зараз"), ("kmalu", "Хто може відкритися скоро"), ("blizu", "Найближчі до мене"), ("jezik", "Мова")],
    "ru": [("start", "Новое уведомление"), ("moja", "Мои уведомления"), ("zdaj", "Кто принимает сейчас"), ("kmalu", "Кто может открыться скоро"), ("blizu", "Ближайшие ко мне"), ("jezik", "Язык")],
}
RADII = [0, 10, 25]
BOT_USER = os.environ.get("BOT_USER", "ZdravnikAlarmBot")
CHANNEL = os.environ.get("CHANNEL")  # e.g. @ProstiZdravniki — daily openings are posted there when set
SITE = "https://glibey.github.io/prosti-zdravniki"
DB = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), "zb.db"), check_same_thread=False)
DB.executescript("""
CREATE TABLE IF NOT EXISTS subs(chat INTEGER, type TEXT, muni TEXT, radius INTEGER, created REAL, active INTEGER DEFAULT 1,
  PRIMARY KEY(chat, type, muni));
CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, accepts TEXT);
CREATE TABLE IF NOT EXISTS pending(chat INTEGER PRIMARY KEY, type TEXT, muni TEXT);
CREATE TABLE IF NOT EXISTS sent(ts REAL, chat INTEGER, key TEXT);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS users(chat INTEGER PRIMARY KEY, lang TEXT, src TEXT, created REAL);
""")
lock = threading.Lock()


def http(url, data=None, timeout=40):
    req = urllib.request.Request(url, data, {"User-Agent": "zdravniki-alerts", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def slug(s):
    """URL/deep-link safe municipality id (Telegram start params allow only A-Za-z0-9_-)."""
    return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")


def km(a, b, c, d):
    p = math.pi / 180
    h = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def load(ref="main"):
    """Return (doctors dict key -> row with institution fields merged, municipality centroids)."""
    get = lambda f: list(csv.DictReader(io.StringIO(http(RAW.format(ref=ref, f=f)).decode("utf-8"))))
    inst = {r["id_inst"]: r for r in get("institutions.csv")}
    docs = {}
    for r in get("doctors.csv"):
        if r["type"] not in TYPES:
            continue
        i = inst.get(r["id_inst"], {})
        m = {k: (r.get(k) or i.get(k) or "") for k in ("address", "post", "city", "municipality", "phone", "website")}
        m.update(name=r["doctor"], type=r["type"], inst=i.get("name", ""), orderform=r.get("orderform", ""),
                 note=r.get("note_override", ""), accepts=(r.get("accepts_override") or r["accepts"]).strip(),
                 load=float(r.get("load") or 0),
                 lat=float(r.get("lat") or i.get("lat") or 0), lon=float(r.get("lon") or i.get("lon") or 0))
        docs[f"{r['doctor']}|{r['type']}|{r['id_inst']}"] = m
    cent = {}
    for d in docs.values():
        if d["municipality"] and d["lat"]:
            cent.setdefault(d["municipality"], []).append((d["lat"], d["lon"]))
    cent = {k: (sum(a for a, _ in v) / len(v), sum(b for _, b in v) / len(v)) for k, v in cent.items()}
    return docs, cent


DOCS, CENT, AVG_LOAD = {}, {}, {}


def matches(d, typ, muni, radius):
    if d["type"] != typ:
        return False
    if d["municipality"] == muni:
        return True
    if radius and muni in CENT and d["lat"]:
        return km(*CENT[muni], d["lat"], d["lon"]) <= radius
    return False


def tname(typ, lang, plural=False):
    return TYPE_NAMES[lang][typ][1] if plural else f"{ICON[typ]} {TYPE_NAMES[lang][typ][0]}"


def card(d, lang="sl", extra=""):
    lines = [f"<b>{esc(d['name'])}</b> — {TYPE_NAMES[lang][d['type']][0].lower()}",
             f"🏥 {esc(d['inst'])}", f"📍 {esc(', '.join(x for x in (d['address'], d['post'] or d['city']) if x))}"]
    if d["phone"]:
        lines.append(f"📞 {esc(d['phone'])}")
    if d["orderform"] or d["website"]:
        lines.append(f"🌐 {esc(d['orderform'] or d['website'])}")
    if d["note"]:
        lines.append(f"ℹ️ {esc(d['note'])}")
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tg(method, **p):
    return json.loads(http(f"https://api.telegram.org/bot{TOKEN}/{method}", json.dumps(p).encode()))


def send(chat, text, kb=None, markup=None):
    if not TOKEN:
        print(f"[dry → {chat}]\n{text}\n{json.dumps(kb, ensure_ascii=False) if kb else ''}\n", flush=True)
        return True
    try:
        tg("sendMessage", chat_id=chat, text=text, parse_mode="HTML", disable_web_page_preview=True,
           **({"reply_markup": {"inline_keyboard": kb}} if kb else {"reply_markup": markup} if markup else {}))
        return True
    except urllib.error.HTTPError as e:
        print("send error", chat, e.code, e.read()[:200], flush=True)
        if e.code == 403:
            with lock:
                DB.execute("UPDATE subs SET active=0 WHERE chat=?", (chat,)); DB.commit()
        return False


def lang_of(chat, code=None):
    """Stored language, else guessed from Telegram's language_code (and stored)."""
    r = DB.execute("SELECT lang FROM users WHERE chat=?", (chat,)).fetchone()
    if r and r[0]:
        return r[0]
    c = (code or "")[:2]
    lang = c if c in ("sl", "uk", "ru") else "sl" if not c else "en"
    with lock:
        DB.execute("INSERT OR IGNORE INTO users(chat, lang, created) VALUES(?,?,?)", (chat, lang, time.time())); DB.commit()
    return lang


# ---------- alerts ----------

def opened(old, new):
    """Keys that switched to accepting (or appeared already accepting) between two snapshots."""
    return [k for k, d in new.items() if d["accepts"] == "y" and old.get(k, "n") != "y"]


def notify(keys):
    subs = DB.execute("SELECT chat, type, muni, radius FROM subs WHERE active=1").fetchall()
    per_chat = {}
    for k in keys:
        d = DOCS[k]
        for chat, typ, muni, radius in subs:
            if matches(d, typ, muni, radius) and k not in per_chat.get(chat, []):
                per_chat.setdefault(chat, []).append(k)
    for chat, ks in per_chat.items():
        lang = lang_of(chat)
        body = "\n\n".join(card(DOCS[k], lang) for k in ks[:10])
        more = f"\n\n…+{len(ks) - 10}" if len(ks) > 10 else ""
        if send(chat, f"{S['alert'][lang]}\n\n{body}{more}\n\n{S['footer'][lang]}"):
            with lock:
                DB.executemany("INSERT INTO sent VALUES(?,?,?)", [(time.time(), chat, k) for k in ks]); DB.commit()
    return per_chat


def post_channel(keys):
    """Public channel digest of today's openings (Slovenian), each with a one-tap subscribe link."""
    if not CHANNEL:
        return
    by = {}
    for k in keys:
        by.setdefault((DOCS[k]["municipality"], DOCS[k]["type"]), []).append(DOCS[k])
    lines = [f"🔔 <b>Novi prosti zdravniki</b> ({time.strftime('%-d. %-m.')}) — sprejemajo nove paciente:\n"]
    for (muni, typ), ds in sorted(by.items())[:40]:
        names = ", ".join(esc(d["name"]) for d in ds[:4]) + (f" +{len(ds) - 4}" if len(ds) > 4 else "")
        lines.append(f"{ICON[typ]} <b>{esc(muni)}</b> · {TYPE_NAMES['sl'][typ][0].lower()}: {names} "
                     f"(<a href=\"https://t.me/{BOT_USER}?start={typ}_{slug(muni)}\">obvesti me</a>)")
    lines.append(f"\nVse po občinah: {SITE}/\nObvestila za vašo občino: @{BOT_USER}")
    send(CHANNEL, "\n".join(lines)[:4000])


def check_stale(ts):
    """Tell the owner (once a day) when Sledilnik data has not been refreshed for 2+ days."""
    try:
        age = time.time() - int(ts)
    except ValueError:
        return
    today = time.strftime("%F")
    if age > 2 * 86400 and OWNER and DB.execute("SELECT v FROM meta WHERE k='stale_warned'").fetchone() != (today,):
        send(OWNER, f"⚠️ Sledilnik data is {age / 86400:.1f} days old (ts {ts}). Alerts are paused until it updates.")
        with lock:
            DB.execute("INSERT OR REPLACE INTO meta VALUES('stale_warned', ?)", (today,)); DB.commit()


def set_docs(docs, cent):
    global DOCS, CENT, AVG_LOAD
    DOCS, CENT = docs, cent
    by = {}
    for d in docs.values():
        if d["load"] > 0:
            by.setdefault(d["type"], []).append(d["load"])
    AVG_LOAD = {t: sorted(v)[len(v) // 2] for t, v in by.items()}  # median per type


def poll_once():
    ts = http(RAW.format(ref="main", f="doctors.csv.timestamp")).decode().strip()
    check_stale(ts)
    last = DB.execute("SELECT v FROM meta WHERE k='ts'").fetchone()
    if DOCS and last and last[0] == ts:
        return 0
    set_docs(*load())
    old = dict(DB.execute("SELECT key, accepts FROM state").fetchall())
    keys = opened(old, DOCS) if old else []  # first run only seeds state
    if keys:
        notify(keys)
        post_channel(keys)
    with lock:
        DB.execute("DELETE FROM state")
        DB.executemany("INSERT INTO state VALUES(?,?)", [(k, d["accepts"]) for k, d in DOCS.items()])
        DB.execute("INSERT OR REPLACE INTO meta VALUES('ts', ?)", (ts,)); DB.commit()
    print(time.strftime("%F %T"), f"data ts {ts}: {len(DOCS)} doctors, {len(keys)} newly accepting", flush=True)
    return len(keys)


def poll_loop():
    while True:
        try:
            poll_once()
        except Exception as e:
            print("poll error", e, flush=True)
            if OWNER:
                send(OWNER, f"poll error: {esc(str(e))[:300]}")
        time.sleep(POLL)


# ---------- bot ----------

def find_muni(q):
    q = norm(q)
    munis = sorted(CENT)
    exact = [m for m in munis if norm(m) == q or slug(m) == slug(q)]
    if exact:
        return exact
    by_city = sorted({d["municipality"] for d in DOCS.values() if norm(d["city"]) == q and d["municipality"]})
    if by_city:
        return by_city
    return [m for m in munis if q in norm(m)][:8]


def muni_by_slug(s):
    return next((m for m in CENT if slug(m) == s), None)


def accepting(typ, muni, radius):
    return [d for d in DOCS.values() if d["accepts"] == "y" and matches(d, typ, muni, radius)]


def type_kb(lang):
    return [[{"text": tname(t, lang), "callback_data": f"t:{t}"}] for t in TYPES]


def where_of(muni, r):
    return f"{esc(muni)}{f' (+{r} km)' if r else ''}"


def subs_text(chat, lang):
    rows = DB.execute("SELECT type, muni, radius FROM subs WHERE chat=? AND active=1", (chat,)).fetchall()
    if not rows:
        return S["no_subs"][lang], None
    kb = [[{"text": f"❌ {tname(t, lang)} · {m}{f' +{r} km' if r else ''}", "callback_data": f"d:{t}|{m}"}] for t, m, r in rows]
    return S["your_subs"][lang], kb


def share_kb(lang):
    url = f"https://t.me/share/url?url=https://t.me/{BOT_USER}&text={urllib.parse.quote(S['share_text'][lang])}"
    return [[{"text": S["share"][lang], "url": url}]]


def set_pending(chat, typ, muni):
    with lock:
        DB.execute("INSERT OR REPLACE INTO pending VALUES(?,?,?)", (chat, typ, muni)); DB.commit()


def on_start(chat, lang, payload):
    """/start [<type>_<muni-slug> | m_<muni-slug>]"""
    with lock:
        DB.execute("UPDATE users SET src=COALESCE(src, ?) WHERE chat=?", (payload or "direct", chat)); DB.commit()
    kind, _, s = (payload or "").partition("_")
    muni = muni_by_slug(s) if s else None
    if muni and kind in TYPES:
        return ask_radius(chat, lang, kind, muni)
    if muni:
        set_pending(chat, None, muni)
        return send(chat, S["welcome"][lang].rsplit("\n\n", 1)[0] + "\n\n" + S["muni_type"][lang].format(muni=esc(muni)),
                    type_kb(lang))
    return send(chat, S["welcome"][lang], type_kb(lang))


def for_each_sub(chat, lang, fn):
    rows = DB.execute("SELECT type, muni, radius FROM subs WHERE chat=? AND active=1", (chat,)).fetchall()
    if not rows:
        return send(chat, S["no_subs"][lang])
    for typ, muni, r in rows:
        fn(chat, lang, typ, muni, r)


def on_text(chat, text, code=None):
    lang = lang_of(chat, code)
    t = text.strip()
    if t.startswith("/start"):
        return on_start(chat, lang, t[6:].strip())
    if t.startswith("/moja"):
        return send(chat, *subs_text(chat, lang))
    if t.startswith("/zdaj"):
        return for_each_sub(chat, lang, show_now)
    if t.startswith("/kmalu"):
        return for_each_sub(chat, lang, show_soon)
    if t.startswith("/blizu"):
        return send(chat, S["near_type"][lang], [[{"text": tname(x, lang), "callback_data": f"n:{x}"}] for x in TYPES])
    if t.startswith(("/jezik", "/lang")):
        return send(chat, S["choose_lang"][lang], [[{"text": v, "callback_data": f"l:{k}"}] for k, v in LANGS.items()])
    if t.startswith("/stats") and chat == OWNER:
        n = DB.execute("SELECT COUNT(DISTINCT chat), COUNT(*) FROM subs WHERE active=1").fetchone()
        s = DB.execute("SELECT COUNT(*), COUNT(DISTINCT chat) FROM sent").fetchone()
        u = DB.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        top = DB.execute("SELECT muni, COUNT(*) c FROM subs WHERE active=1 GROUP BY muni ORDER BY c DESC LIMIT 8").fetchall()
        langs = DB.execute("SELECT lang, COUNT(*) FROM users GROUP BY lang").fetchall()
        srcs = DB.execute("SELECT CASE WHEN src='direct' THEN 'direct' ELSE 'site' END, COUNT(*) FROM users "
                          "WHERE src IS NOT NULL GROUP BY 1").fetchall()
        return send(chat, f"users {u} (with alerts {n[0]}), subs {n[1]}\nalerts sent {s[0]} to {s[1]} users\n"
                          f"langs {dict(langs)} · src {dict(srcs)}\n" + "\n".join(f"{m}: {c}" for m, c in top))
    p = DB.execute("SELECT type, muni FROM pending WHERE chat=?", (chat,)).fetchone()
    if not p or not p[0] or p[1] == "@near":
        return send(chat, S["choose_type"][lang], type_kb(lang))
    found = find_muni(t)
    if not found:
        return send(chat, S["no_muni"][lang])
    if len(found) == 1:
        return ask_radius(chat, lang, p[0], found[0])
    send(chat, S["which_muni"][lang], [[{"text": m, "callback_data": f"m:{m}"}] for m in found])


def ask_radius(chat, lang, typ, muni):
    set_pending(chat, typ, muni)
    send(chat, S["ask_radius"][lang].format(muni=esc(muni)),
         [[{"text": S["only_muni"][lang] if r == 0 else S["plus_km"][lang].format(r=r), "callback_data": f"r:{r}"}
           for r in RADII]])


def show_now(chat, lang, typ, muni, r):
    now = accepting(typ, muni, r)
    plural, where = tname(typ, lang, True), where_of(muni, r)
    if not now:
        return send(chat, S["none_now"][lang].format(where=where, plural=plural))
    body = "\n\n".join(card(d, lang) for d in now[:8])
    more = "\n\n" + S["more"][lang].format(n=len(now) - 8) if len(now) > 8 else ""
    send(chat, f"{S['now_list'][lang].format(plural=plural, where=where)}\n\n{body}{more}")


def show_soon(chat, lang, typ, muni, r):
    plural, where = tname(typ, lang, True), where_of(muni, r)
    leaving = re.compile(r"pokoj|upokoj|odhaja|odšel|porodni|bolni", re.I)  # retired/leaving/on leave: low load, won't open
    cand = sorted((d for d in DOCS.values() if d["accepts"] != "y" and d["load"] > 0 and not leaving.search(d["note"])
                   and matches(d, typ, muni, r)), key=lambda d: d["load"])[:5]
    if not cand or not AVG_LOAD.get(typ):
        return send(chat, S["soon_none"][lang].format(where=where))
    body = "\n\n".join(card(d, lang, "📊 " + S["load"][lang].format(p=round(100 * d["load"] / AVG_LOAD[typ])))
                       for d in cand)
    send(chat, f"{S['soon_head'][lang].format(plural=plural, where=where)}\n\n{body}")


def show_near(chat, lang, typ, lat, lon):
    plural = tname(typ, lang, True)
    near = sorted(((km(lat, lon, d["lat"], d["lon"]), d) for d in DOCS.values()
                   if d["type"] == typ and d["accepts"] == "y" and d["lat"]), key=lambda x: x[0])
    near = [(dist, d) for dist, d in near if dist <= 50][:6]
    rm = {"remove_keyboard": True}
    if not near:
        return send(chat, S["near_none"][lang].format(plural=plural), markup=rm)
    body = "\n\n".join(card(d, lang, f"📏 {dist:.1f} km") for dist, d in near)
    send(chat, f"{S['near_head'][lang].format(plural=plural)}\n\n{body}", markup=rm)


def on_location(chat, lat, lon, code=None):
    lang = lang_of(chat, code)
    p = DB.execute("SELECT type, muni FROM pending WHERE chat=?", (chat,)).fetchone()
    typ = p[0] if p and p[1] == "@near" and p[0] in TYPES else "gp"
    with lock:
        DB.execute("DELETE FROM pending WHERE chat=? AND muni='@near'", (chat,)); DB.commit()
    show_near(chat, lang, typ, lat, lon)


def on_cb(chat, data, code=None):
    lang = lang_of(chat, code)
    kind, val = data.split(":", 1)
    if kind == "l" and val in LANGS:
        with lock:
            DB.execute("UPDATE users SET lang=? WHERE chat=?", (val, chat)); DB.commit()
        if TOKEN:  # this chat's command menu follows the chosen language
            tg("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS[val]],
               scope={"type": "chat", "chat_id": chat})
        return send(chat, S["lang_set"][val] + "\n\n" + S["help"][val])
    p = DB.execute("SELECT type, muni FROM pending WHERE chat=?", (chat,)).fetchone()
    if kind == "n" and val in TYPES:
        set_pending(chat, val, "@near")
        return send(chat, S["near_ask"][lang], markup={"keyboard": [[{"text": S["near_btn"][lang], "request_location": True}]],
                                                       "resize_keyboard": True, "one_time_keyboard": True})
    if p and p[1] == "@near":
        p = None
    if kind == "t":
        if p and p[1]:  # municipality already chosen via deep link
            return ask_radius(chat, lang, val, p[1])
        set_pending(chat, val, None)
        return send(chat, S["ask_muni"][lang].format(type=tname(val, lang)))
    if kind == "m" and p:
        return ask_radius(chat, lang, p[0], val)
    if kind == "r" and p and p[0] and p[1]:
        typ, muni, r = p[0], p[1], int(val)
        with lock:
            DB.execute("INSERT OR REPLACE INTO subs VALUES(?,?,?,?,?,1)", (chat, typ, muni, r, time.time()))
            DB.execute("DELETE FROM pending WHERE chat=?", (chat,)); DB.commit()
        send(chat, S["sub_on"][lang].format(what=f"{tname(typ, lang)} · {esc(muni)}{f' +{r} km' if r else ''}")
             + "\n" + S["help"][lang], share_kb(lang))
        return show_now(chat, lang, typ, muni, r)
    if kind == "d":
        typ, muni = val.split("|", 1)
        with lock:
            DB.execute("DELETE FROM subs WHERE chat=? AND type=? AND muni=?", (chat, typ, muni)); DB.commit()
        return send(chat, *subs_text(chat, lang))


def set_commands_menu():
    for lang, cmds in COMMANDS.items():
        p = {"commands": [{"command": c, "description": d} for c, d in cmds]}
        if lang != "sl":
            p["language_code"] = lang
        tg("setMyCommands", **p)


def bot_loop():
    off = 0
    set_commands_menu()
    while True:
        try:
            for u in tg("getUpdates", timeout=25, offset=off)["result"]:
                off = u["update_id"] + 1
                try:
                    if "message" in u and "location" in u["message"]:
                        m = u["message"]
                        on_location(m["chat"]["id"], m["location"]["latitude"], m["location"]["longitude"],
                                    m.get("from", {}).get("language_code"))
                    elif "message" in u and "text" in u["message"]:
                        m = u["message"]
                        print("msg", m["chat"]["id"], m["text"][:40], flush=True)
                        on_text(m["chat"]["id"], m["text"], m.get("from", {}).get("language_code"))
                    elif "callback_query" in u:
                        q = u["callback_query"]
                        tg("answerCallbackQuery", callback_query_id=q["id"])
                        on_cb(q["message"]["chat"]["id"], q["data"], q.get("from", {}).get("language_code"))
                except Exception as e:
                    print("update error", e, flush=True)
        except Exception as e:
            print("getUpdates error", e, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--diff":
        old, _ = load(sys.argv[2])
        set_docs(*load())
        ks = opened({k: d["accepts"] for k, d in old.items()}, DOCS)
        print(f"{len(ks)} newly accepting since {sys.argv[2][:8]}")
        for k in ks:
            print(" ", DOCS[k]["type"], "|", DOCS[k]["municipality"], "|", DOCS[k]["name"])
        sys.exit()
    poll_once()
    if not TOKEN:
        print("dry-run: no TG_TOKEN; poller only", flush=True)
        poll_loop()
    threading.Thread(target=poll_loop, daemon=True).start()
    bot_loop()
