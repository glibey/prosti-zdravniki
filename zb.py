"""Prosti zdravniki → Telegram alerts (Slovenia).

Polls Sledilnik's daily mirror of ZZZS open data (which doctors accept new patients) and notifies
subscribers when a doctor of their chosen type in their municipality (optionally + radius) starts accepting.

Env: TG_TOKEN (without it: dry-run, alerts printed), OWNER_CHAT (gets /stats + errors), POLL_MIN (default 30).
Run: python3 zb.py            # bot + poller
     python3 zb.py --diff SHA  # print what alerts would fire between commit SHA and today's data
"""
import csv, io, json, math, os, sqlite3, sys, threading, time, unicodedata, urllib.error, urllib.request

_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env):
    for _l in open(_env):
        if "=" in _l and not _l.startswith("#"):
            os.environ.setdefault(*_l.strip().split("=", 1))

RAW = "https://raw.githubusercontent.com/sledilnik/zdravniki-data/{ref}/csv/{f}"
TOKEN = os.environ.get("TG_TOKEN")
OWNER = int(os.environ.get("OWNER_CHAT", 0))
POLL = float(os.environ.get("POLL_MIN", 30)) * 60
TYPES = {  # id: (button label, plural for messages)
    "gp": ("🩺 Družinski zdravnik", "družinski zdravniki"),
    "ped": ("🧸 Pediater", "pediatri"),
    "gyn": ("🌸 Ginekolog", "ginekologi"),
    "den": ("🦷 Zobozdravnik", "zobozdravniki"),
    "den-y": ("🦷 Zobozdravnik za mladino", "zobozdravniki za mladino"),
    "den-s": ("🎓 Zobozdravnik za študente", "zobozdravniki za študente"),
}
RADII = [0, 10, 25]
DB = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), "zb.db"), check_same_thread=False)
DB.executescript("""
CREATE TABLE IF NOT EXISTS subs(chat INTEGER, type TEXT, muni TEXT, radius INTEGER, created REAL, active INTEGER DEFAULT 1,
  PRIMARY KEY(chat, type, muni));
CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, accepts TEXT);
CREATE TABLE IF NOT EXISTS pending(chat INTEGER PRIMARY KEY, type TEXT, muni TEXT);
CREATE TABLE IF NOT EXISTS sent(ts REAL, chat INTEGER, key TEXT);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
""")
lock = threading.Lock()


def http(url, data=None, timeout=40):
    req = urllib.request.Request(url, data, {"User-Agent": "zdravniki-alerts", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


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
                 lat=float(r.get("lat") or i.get("lat") or 0), lon=float(r.get("lon") or i.get("lon") or 0))
        docs[f"{r['doctor']}|{r['type']}|{r['id_inst']}"] = m
    cent = {}
    for d in docs.values():
        if d["municipality"] and d["lat"]:
            cent.setdefault(d["municipality"], []).append((d["lat"], d["lon"]))
    cent = {k: (sum(a for a, _ in v) / len(v), sum(b for _, b in v) / len(v)) for k, v in cent.items()}
    return docs, cent


DOCS, CENT = {}, {}


def matches(d, typ, muni, radius):
    if d["type"] != typ:
        return False
    if d["municipality"] == muni:
        return True
    if radius and muni in CENT and d["lat"]:
        return km(*CENT[muni], d["lat"], d["lon"]) <= radius
    return False


def card(d):
    lines = [f"<b>{esc(d['name'])}</b> — {TYPES[d['type']][0].split(' ', 1)[1].lower()}",
             f"🏥 {esc(d['inst'])}", f"📍 {esc(', '.join(x for x in (d['address'], d['post'] or d['city']) if x))}"]
    if d["phone"]:
        lines.append(f"📞 {esc(d['phone'])}")
    if d["orderform"] or d["website"]:
        lines.append(f"🌐 {esc(d['orderform'] or d['website'])}")
    if d["note"]:
        lines.append(f"ℹ️ {esc(d['note'])}")
    return "\n".join(lines)


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tg(method, **p):
    return json.loads(http(f"https://api.telegram.org/bot{TOKEN}/{method}", json.dumps(p).encode()))


def send(chat, text, kb=None):
    if not TOKEN:
        print(f"[dry → {chat}]\n{text}\n", flush=True)
        return True
    try:
        tg("sendMessage", chat_id=chat, text=text, parse_mode="HTML", disable_web_page_preview=True,
           **({"reply_markup": {"inline_keyboard": kb}} if kb else {}))
        return True
    except urllib.error.HTTPError as e:
        print("send error", chat, e.code, e.read()[:200], flush=True)
        if e.code == 403:
            with lock:
                DB.execute("UPDATE subs SET active=0 WHERE chat=?", (chat,)); DB.commit()
        return False


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
            if matches(d, typ, muni, radius):
                per_chat.setdefault(chat, []).append(k)
    for chat, ks in per_chat.items():
        body = "\n\n".join(card(DOCS[k]) for k in ks[:10])
        more = f"\n\n…in še {len(ks) - 10}" if len(ks) > 10 else ""
        if send(chat, f"🔔 <b>Nov prost zdravnik!</b> Sprejema nove paciente:\n\n{body}{more}\n\n"
                      "<i>Podatki ZZZS (prek Sledilnika), osveženo enkrat dnevno. Pred obiskom pokličite ambulanto.</i>"):
            with lock:
                DB.executemany("INSERT INTO sent VALUES(?,?,?)", [(time.time(), chat, k) for k in ks]); DB.commit()
    return per_chat


def poll_once():
    global DOCS, CENT
    ts = http(RAW.format(ref="main", f="doctors.csv.timestamp")).decode().strip()
    last = DB.execute("SELECT v FROM meta WHERE k='ts'").fetchone()
    if DOCS and last and last[0] == ts:
        return 0
    DOCS, CENT = load()
    old = dict(DB.execute("SELECT key, accepts FROM state").fetchall())
    keys = opened(old, DOCS) if old else []  # first run only seeds state
    if keys:
        notify(keys)
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
    exact = [m for m in munis if norm(m) == q]
    if exact:
        return exact
    by_city = sorted({d["municipality"] for d in DOCS.values() if norm(d["city"]) == q and d["municipality"]})
    if by_city:
        return by_city
    return [m for m in munis if q in norm(m)][:8]


def accepting(typ, muni, radius):
    return [d for d in DOCS.values() if d["accepts"] == "y" and matches(d, typ, muni, radius)]


def type_kb():
    return [[{"text": TYPES[t][0], "callback_data": f"t:{t}"}] for t in TYPES]


WELCOME = ("Pozdravljeni! 👋\n\nTa bot vas <b>obvesti, ko zdravnik v vaši občini začne sprejemati nove paciente</b> "
           "(podatki ZZZS, preverjeni vsak dan).\n\nIzberite vrsto zdravnika:")


def subs_text(chat):
    rows = DB.execute("SELECT type, muni, radius FROM subs WHERE chat=? AND active=1", (chat,)).fetchall()
    if not rows:
        return "Nimate naročil. /start za novo.", None
    kb = [[{"text": f"❌ {TYPES[t][0]} · {m}{f' +{r} km' if r else ''}", "callback_data": f"d:{t}|{m}"}] for t, m, r in rows]
    return "Vaša opozorila (kliknite za izbris):", kb


def on_text(chat, text):
    t = text.strip()
    if t.startswith("/start"):
        return send(chat, WELCOME, type_kb())
    if t.startswith("/moja"):
        return send(chat, *subs_text(chat))
    if t.startswith("/zdaj"):
        rows = DB.execute("SELECT type, muni, radius FROM subs WHERE chat=? AND active=1", (chat,)).fetchall()
        if not rows:
            return send(chat, "Nimate naročil. /start")
        for typ, muni, r in rows:
            show_now(chat, typ, muni, r)
        return
    if t.startswith("/stats") and chat == OWNER:
        n = DB.execute("SELECT COUNT(DISTINCT chat), COUNT(*) FROM subs WHERE active=1").fetchone()
        s = DB.execute("SELECT COUNT(*), COUNT(DISTINCT chat) FROM sent").fetchone()
        top = DB.execute("SELECT muni, COUNT(*) c FROM subs WHERE active=1 GROUP BY muni ORDER BY c DESC LIMIT 8").fetchall()
        return send(chat, f"users {n[0]}, subs {n[1]}\nalerts sent {s[0]} to {s[1]} users\n" +
                    "\n".join(f"{m}: {c}" for m, c in top))
    p = DB.execute("SELECT type FROM pending WHERE chat=?", (chat,)).fetchone()
    if not p:
        return send(chat, "Najprej izberite vrsto zdravnika:", type_kb())
    found = find_muni(t)
    if not found:
        return send(chat, "Te občine ne najdem 🤔 Poskusite drugače (npr. <i>Maribor</i>, <i>Ljubljana</i>, <i>Ptuj</i>).")
    if len(found) == 1:
        return ask_radius(chat, p[0], found[0])
    send(chat, "Katero občino ste mislili?", [[{"text": m, "callback_data": f"m:{m}"}] for m in found])


def ask_radius(chat, typ, muni):
    with lock:
        DB.execute("INSERT OR REPLACE INTO pending VALUES(?,?,?)", (chat, typ, muni)); DB.commit()
    send(chat, f"<b>{esc(muni)}</b> — samo občina ali tudi okolica?",
         [[{"text": "Samo občina" if r == 0 else f"+ okolica {r} km", "callback_data": f"r:{r}"} for r in RADII]])


def show_now(chat, typ, muni, r):
    now = accepting(typ, muni, r)
    where = f"{esc(muni)}{f' (+{r} km)' if r else ''}"
    if not now:
        return send(chat, f"Trenutno v {where} <b>ni</b> prostih ({TYPES[typ][1]}). Obvestilo dobite, ko se to spremeni.")
    body = "\n\n".join(card(d) for d in now[:8])
    more = f"\n\n…in še {len(now) - 8}. Vse na zdravniki.sledilnik.org" if len(now) > 8 else ""
    send(chat, f"✅ Trenutno sprejemajo ({TYPES[typ][1]}, {where}):\n\n{body}{more}")


def on_cb(chat, data):
    kind, val = data.split(":", 1)
    if kind == "t":
        with lock:
            DB.execute("INSERT OR REPLACE INTO pending VALUES(?,?,NULL)", (chat, val)); DB.commit()
        return send(chat, f"{TYPES[val][0]} ✔️\n\nNapišite <b>občino ali kraj</b> (npr. Maribor):")
    p = DB.execute("SELECT type, muni FROM pending WHERE chat=?", (chat,)).fetchone()
    if kind == "m" and p:
        return ask_radius(chat, p[0], val)
    if kind == "r" and p and p[1]:
        typ, muni, r = p[0], p[1], int(val)
        with lock:
            DB.execute("INSERT OR REPLACE INTO subs VALUES(?,?,?,?,?,1)", (chat, typ, muni, r, time.time()))
            DB.execute("DELETE FROM pending WHERE chat=?", (chat,)); DB.commit()
        send(chat, f"🔔 Opozorilo vklopljeno: {TYPES[typ][0]} · {esc(muni)}{f' +{r} km' if r else ''}.\n"
                   "/moja — vaša opozorila · /start — dodaj novo · /zdaj — kdo sprejema zdaj")
        return show_now(chat, typ, muni, r)
    if kind == "d":
        typ, muni = val.split("|", 1)
        with lock:
            DB.execute("DELETE FROM subs WHERE chat=? AND type=? AND muni=?", (chat, typ, muni)); DB.commit()
        return send(chat, *subs_text(chat))


def bot_loop():
    off = 0
    tg("setMyCommands", commands=[{"command": "start", "description": "Novo opozorilo"},
                                  {"command": "moja", "description": "Moja opozorila"},
                                  {"command": "zdaj", "description": "Kdo sprejema zdaj"}])
    while True:
        try:
            for u in tg("getUpdates", timeout=25, offset=off)["result"]:
                off = u["update_id"] + 1
                try:
                    if "message" in u and "text" in u["message"]:
                        print("msg", u["message"]["chat"]["id"], u["message"]["text"][:40], flush=True)
                        on_text(u["message"]["chat"]["id"], u["message"]["text"])
                    elif "callback_query" in u:
                        q = u["callback_query"]
                        tg("answerCallbackQuery", callback_query_id=q["id"])
                        on_cb(q["message"]["chat"]["id"], q["data"])
                except Exception as e:
                    print("update error", e, flush=True)
        except Exception as e:
            print("getUpdates error", e, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--diff":
        old, _ = load(sys.argv[2])
        DOCS, CENT = load()
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
