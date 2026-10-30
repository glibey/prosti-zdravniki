"""Static SEO site: one page per municipality listing doctors that accept new patients, CTA to the bot.
Usage: python3 gen_site.py [out_dir]   (SITE_URL env sets the canonical base URL)"""
import html, os, re, sys, time
from zb import ICON, TYPES, TYPE_NAMES, load, norm, slug as tg_slug

BOT = "ZdravnikAlarmBot"
BASE = os.environ.get("SITE_URL", "https://glibey.github.io/prosti-zdravniki").rstrip("/")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
e = html.escape
slug = lambda s: norm(s).replace(" ", "-").replace("/", "-")
SHORT = {t: n for t, (n, _) in TYPE_NAMES["sl"].items()}

CSS = """
:root{--bg:#f4f6fb;--card:#fff;--ink:#0f172a;--mute:#64748b;--line:#e2e8f0;--acc:#2563eb;--acc2:#0ea5e9;--ok:#059669;
--okbg:#d1fae5;--no:#94a3b8;--chip:#eef2ff;--shadow:0 1px 2px rgba(15,23,42,.04),0 4px 16px rgba(15,23,42,.06);color-scheme:light}
@media(prefers-color-scheme:dark){:root{--bg:#0b1120;--card:#131c2e;--ink:#e2e8f0;--mute:#94a3b8;--line:#1e293b;--acc:#60a5fa;
--acc2:#38bdf8;--ok:#34d399;--okbg:#064e3b;--no:#475569;--chip:#1e293b;--shadow:none;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 Inter,system-ui,-apple-system,Segoe UI,sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:880px;margin:0 auto;padding:0 16px}
header.top{position:sticky;top:0;z-index:5;backdrop-filter:saturate(1.6) blur(12px);background:color-mix(in srgb,var(--bg) 80%,transparent);border-bottom:1px solid var(--line)}
header.top .wrap{display:flex;align-items:center;justify-content:space-between;height:56px}
.logo{font-weight:700;color:var(--ink);letter-spacing:-.01em}.logo span{color:var(--acc)}
.btn{display:inline-flex;align-items:center;gap:8px;border-radius:999px;padding:10px 16px;font-weight:600;font-size:15px;border:1px solid var(--line);background:var(--card);color:var(--ink)}
.btn:hover{text-decoration:none;border-color:var(--acc)}
.btn.pri{background:linear-gradient(135deg,#2563eb,#0284c7);color:#fff;border:0;box-shadow:0 6px 20px rgba(37,99,235,.25)}
.btn.sm{padding:7px 12px;font-size:14px}
.hero{padding:40px 0 8px}.eyebrow{display:inline-block;font-size:13px;font-weight:600;color:var(--acc);background:var(--chip);border-radius:999px;padding:4px 10px}
h1{font-size:clamp(28px,5vw,44px);line-height:1.1;letter-spacing:-.025em;margin:14px 0 12px}
.lead{color:var(--mute);font-size:18px;max-width:640px;margin:0 0 20px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:24px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 16px;box-shadow:var(--shadow)}
.stat b{display:block;font-size:26px;letter-spacing:-.02em}.stat span{color:var(--mute);font-size:14px}
.bar{height:6px;background:var(--line);border-radius:9px;overflow:hidden;margin-top:8px}.bar i{display:block;height:100%;background:var(--ok);border-radius:9px}
.search{position:relative;margin:28px 0 12px}.search input{width:100%;font:inherit;font-size:17px;padding:15px 16px 15px 46px;border-radius:14px;border:1px solid var(--line);background:var(--card);color:var(--ink);box-shadow:var(--shadow);outline:none}
.search input:focus{border-color:var(--acc);box-shadow:0 0 0 4px color-mix(in srgb,var(--acc) 18%,transparent)}
.search:before{content:"";position:absolute;left:16px;top:50%;width:18px;height:18px;transform:translateY(-50%);opacity:.5;
background:no-repeat center/contain url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='%2364748b' stroke-width='2.2' viewBox='0 0 24 24'%3E%3Ccircle cx='11' cy='11' r='7'/%3E%3Cpath d='m20 20-3.5-3.5'/%3E%3C/svg%3E")}
h2{font-size:22px;letter-spacing:-.015em;margin:36px 0 12px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px}
.mc{display:flex;justify-content:space-between;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px;color:var(--ink);transition:.15s}
.mc:hover{text-decoration:none;border-color:var(--acc);transform:translateY(-1px)}
.mc small{color:var(--mute);display:block;font-size:13px}.pill{font-size:13px;font-weight:700;border-radius:999px;padding:3px 9px;background:var(--okbg);color:var(--ok);white-space:nowrap}
.pill.z{background:var(--chip);color:var(--no)}
.chips{display:flex;gap:8px;overflow-x:auto;padding:4px 0 8px;margin:8px -16px 0;padding-left:16px;scrollbar-width:none}
.chip{flex:none;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:7px 12px;font-size:14px;font-weight:500}
.chip b{color:var(--ok)}
.sec{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:18px;margin:16px 0;box-shadow:var(--shadow);scroll-margin-top:70px}
.sec-h{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between}.sec-h h2{margin:0;font-size:20px}
.sec-h .n{color:var(--mute);font-size:14px;font-weight:500}
.doc{display:grid;grid-template-columns:44px 1fr;gap:12px;padding:14px 0;border-top:1px solid var(--line)}
.doc:first-of-type{border-top:0}.av{width:44px;height:44px;border-radius:12px;display:grid;place-items:center;font-weight:700;font-size:15px;color:#fff}
.doc h3{margin:0;font-size:16px}.doc p{margin:2px 0 8px;color:var(--mute);font-size:14px}.acts{display:flex;flex-wrap:wrap;gap:8px}
.empty{color:var(--mute);padding:10px 0 4px}
.bell{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin-top:12px;padding:12px 14px;border-radius:14px;background:var(--chip)}
.bell span{font-size:14px;color:var(--mute)}
.crumb{font-size:14px;color:var(--mute);margin-top:20px}.crumb a{color:var(--mute)}
.how{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.how div{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px}
.how b{display:block;margin-bottom:4px}.how span{color:var(--mute);font-size:15px}
.fab{position:fixed;left:16px;right:16px;bottom:16px;z-index:6;justify-content:center;display:none}
@media(max-width:640px){.fab{display:flex}body{padding-bottom:84px}.hide-m{display:none}}
footer{color:var(--mute);font-size:13px;padding:40px 0 48px;border-top:1px solid var(--line);margin-top:48px}
"""
AV_COLORS = ["#2563eb", "#7c3aed", "#db2777", "#ea580c", "#059669", "#0891b2", "#4f46e5", "#c026d3"]
FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' "
           "font-size='90'%3E🩺%3C/text%3E%3C/svg%3E")


def page(title, desc, path, body, fab):
    return f"""<!doctype html><html lang="sl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<meta name="description" content="{e(desc)}"><meta name="google-site-verification" content="PwTt1UPX262GmMSqj9DdlXHXOj1tHu2SNKG2TQiBhpg">
<link rel="canonical" href="{BASE}/{path}"><link rel="icon" href="{FAVICON}">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:type" content="website">
<meta property="og:url" content="{BASE}/{path}"><meta name="theme-color" content="#2563eb">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>
<header class="top"><div class="wrap"><a class="logo" href="{BASE}/">Prosti<span>zdravniki</span></a>
<a class="btn sm pri hide-m" href="{fab}">🔔 Obvestila v Telegramu</a></div></header>
<main class="wrap">{body}</main>
<a class="btn pri fab" href="{fab}">🔔 Obvesti me, ko se sprosti mesto</a>
<footer><div class="wrap">Podatki: ZZZS prek <a href="https://zdravniki.sledilnik.org">Sledilnik</a> (CC BY 4.0), osveženo vsak dan.
Stanje se lahko spremeni — pred obiskom pokličite ambulanto. Neodvisna stran, ni povezana z ZZZS.</div></footer>
</body></html>"""


def tg_link(muni="", typ=""):
    """Deep link: the bot preselects municipality (m_<slug>) or subscribes in one tap (<type>_<slug>)."""
    return f"https://t.me/{BOT}" + (f"?start={typ or 'm'}_{tg_slug(muni)}" if muni else "")


def initials(name):
    p = [w for w in re.split(r"[\s-]+", name) if w]
    return (p[0][0] + (p[1][0] if len(p) > 1 else "")).upper()


def doc(d):
    color = AV_COLORS[sum(map(ord, d["name"])) % len(AV_COLORS)]
    addr = ", ".join(x for x in (d["address"], d["post"] or d["city"]) if x)
    acts = []
    if d["phone"]:
        tel = re.sub(r"[^\d+]", "", d["phone"].split(",")[0])
        acts.append(f'<a class="btn sm" href="tel:{e(tel)}">📞 {e(d["phone"])}</a>')
    link = (d["orderform"] or d["website"]).replace("http:// ", "").strip()
    if link.startswith("http"):
        acts.append(f'<a class="btn sm" href="{e(link)}" rel="nofollow noopener" target="_blank">🌐 Spletna stran</a>')
    note = f' · {e(d["note"])}' if d["note"] else ""
    return (f'<div class="doc"><div class="av" style="background:{color}">{e(initials(d["name"]))}</div><div>'
            f'<h3>{e(d["name"])}</h3><p>{e(d["inst"].title())}<br>{e(addr)}{note}</p><div class="acts">{"".join(acts)}</div></div></div>')


def muni_page(muni, ds, today):
    acc = [d for d in ds if d["accepts"] == "y"]
    present = [t for t in TYPES if any(d["type"] == t for d in ds)]
    stats, chips, secs = [], [], []
    for t in present:
        tl = [d for d in ds if d["type"] == t]
        ta = sorted((d for d in tl if d["accepts"] == "y"), key=lambda d: norm(d["name"]))
        chips.append(f'<a class="chip" href="#{t}">{ICON[t]} {SHORT[t]} <b>{len(ta)}</b></a>')
        if t in ("gp", "ped", "gyn", "den"):
            stats.append(f'<div class="stat"><b>{len(ta)}<span> / {len(tl)}</span></b><span>{ICON[t]} {SHORT[t]}</span>'
                         f'<div class="bar"><i style="width:{round(100 * len(ta) / len(tl))}%"></i></div></div>')
        body = "".join(doc(d) for d in ta) or '<div class="empty">Trenutno nihče ne sprejema novih pacientov.</div>'
        secs.append(f'<section class="sec" id="{t}"><div class="sec-h"><h2>{ICON[t]} {SHORT[t]}</h2>'
                    f'<span class="n">sprejema {len(ta)} od {len(tl)}</span></div>{body}'
                    f'<div class="bell"><span>Obvestimo vas, ko {SHORT[t].lower()} v občini {e(muni)} začne sprejemati.</span>'
                    f'<a class="btn sm pri" href="{tg_link(muni, t)}">🔔 Obvesti me</a></div></section>')
    return (f'<div class="crumb"><a href="../">Vse občine</a> › {e(muni)}</div>'
            f'<section class="hero"><span class="eyebrow">Stanje {today}</span>'
            f"<h1>Prosti zdravniki {e(muni)}</h1>"
            f'<p class="lead">V občini {e(muni)} trenutno sprejema nove paciente <b>{len(acc)}</b> od {len(ds)} zdravnikov. '
            f"Ko se sprosti novo mesto, vam pošljemo sporočilo v Telegram.</p>"
            f'<a class="btn pri" href="{tg_link(muni)}">🔔 Obvesti me za {e(muni)}</a></section>'
            f'<div class="stats">{"".join(stats)}</div><nav class="chips">{"".join(chips)}</nav>{"".join(secs)}')


def main():
    docs, _ = load()
    today = time.strftime("%-d. %-m. %Y")
    by_muni = {}
    for d in docs.values():
        if d["municipality"] and "?" not in d["municipality"]:
            by_muni.setdefault(d["municipality"], []).append(d)
    os.makedirs(OUT, exist_ok=True)
    urls, cards, gp_open = [""], [], []
    for muni in sorted(by_muni, key=norm):
        ds, s = by_muni[muni], slug(muni)
        acc = sum(1 for d in ds if d["accepts"] == "y")
        gp = sum(1 for d in ds if d["accepts"] == "y" and d["type"] == "gp")
        os.makedirs(os.path.join(OUT, s), exist_ok=True)
        with open(os.path.join(OUT, s, "index.html"), "w") as f:
            f.write(page(f"Prosti zdravniki {muni} ({today}) — kdo sprejema nove paciente",
                         f"Seznam zdravnikov v občini {muni}, ki sprejemajo nove paciente: družinski zdravnik, pediater, "
                         f"ginekolog, zobozdravnik. Brezplačno obvestilo v Telegramu.", f"{s}/",
                         muni_page(muni, ds, today), tg_link(muni)))
        urls.append(f"{s}/")
        card = (f'<a class="mc" href="{s}/" data-q="{e(norm(muni))}"><div>{e(muni)}<small>družinski: {gp}</small></div>'
                f'<span class="pill{"" if acc else " z"}">{acc} prostih</span></a>')
        cards.append(card)
        if gp:
            gp_open.append((gp, f'<a class="mc" href="{s}/"><div>{e(muni)}<small>vseh prostih: {acc}</small></div>'
                                f'<span class="pill">{gp} družinsk{"i" if gp == 1 else "ih"}</span></a>'))
    total = sum(1 for d in docs.values() if d["accepts"] == "y")
    tstats = "".join(
        f'<div class="stat"><b>{sum(1 for d in docs.values() if d["type"] == t and d["accepts"] == "y")}'
        f'<span> / {sum(1 for d in docs.values() if d["type"] == t)}</span></b><span>{ICON[t]} {SHORT[t]}</span></div>'
        for t in ("gp", "ped", "gyn", "den"))
    gp_cards = "".join(c for _, c in sorted(gp_open, key=lambda x: -x[0]))
    body = (f'<section class="hero"><span class="eyebrow">Stanje {today} · podatki ZZZS</span>'
            f"<h1>Kdo v vaši občini sprejema nove paciente?</h1>"
            f'<p class="lead">Družinski zdravniki, pediatri, ginekologi in zobozdravniki po vsej Sloveniji — '
            f"in brezplačno obvestilo v Telegramu, ko se v vaši občini sprosti mesto.</p>"
            f'<a class="btn pri" href="{tg_link()}">🔔 Vklopi obvestila</a></section>'
            f'<div class="stats">{tstats}</div>'
            f'<div class="search"><input id="q" type="search" placeholder="Poiščite občino, npr. Maribor" '
            f'autocomplete="off" aria-label="Poiščite občino"></div>'
            f'<h2 id="gph">Kje sprejemajo družinski zdravniki</h2><div class="grid" id="gp">{gp_cards}</div>'
            f'<h2>Vse občine ({len(cards)})</h2><div class="grid" id="all">{"".join(cards)}</div>'
            f'<h2>Kako deluje</h2><div class="how"><div><b>1. Izberite</b><span>vrsto zdravnika in občino v Telegram botu.</span></div>'
            f'<div><b>2. Počakajte</b><span>podatke ZZZS preverjamo vsak dan.</span></div>'
            f'<div><b>3. Pokličite</b><span>takoj, ko dobite sporočilo — prosta mesta hitro zmanjka.</span></div></div>'
            """<script>const q=document.getElementById('q'),n=s=>s.toLowerCase().normalize('NFKD').replace(/[\\u0300-\\u036f]/g,'');
q.addEventListener('input',()=>{const v=n(q.value.trim());document.querySelectorAll('#all .mc').forEach(a=>a.style.display=!v||a.dataset.q.includes(v)?'':'none');
['gp','gph'].forEach(i=>document.getElementById(i).style.display=v?'none':'')});</script>""")
    with open(os.path.join(OUT, "index.html"), "w") as f:
        f.write(page(f"Prosti zdravniki v Sloveniji ({today}) — kdo sprejema nove paciente",
                     "Kateri osebni zdravnik, pediater, ginekolog ali zobozdravnik sprejema nove paciente v vaši občini. "
                     "Brezplačno obvestilo v Telegramu.", "", body, tg_link()))
    with open(os.path.join(OUT, "sitemap.xml"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + "".join(f"<url><loc>{BASE}/{u}</loc></url>" for u in urls) + "</urlset>")
    with open(os.path.join(OUT, "robots.txt"), "w") as f:
        f.write(f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n")
    print(f"{len(urls) - 1} municipality pages, {total} accepting → {OUT}")


if __name__ == "__main__":
    main()
