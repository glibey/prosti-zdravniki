"""Static SEO site: one page per municipality listing doctors that accept new patients, CTA to the bot.
Usage: python3 gen_site.py [out_dir]   (SITE_URL env sets the canonical base URL)"""
import html, os, sys, time
from zb import TYPES, load, norm

BOT = "ZdravnikAlarmBot"
BASE = os.environ.get("SITE_URL", "https://glibey.github.io/prosti-zdravniki").rstrip("/")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
e = html.escape
slug = lambda s: norm(s).replace(" ", "-").replace("/", "-")

CSS = """body{font:16px/1.5 system-ui,sans-serif;margin:0;color:#1d2430;background:#f6f7f9}
main{max-width:760px;margin:0 auto;padding:16px}h1{font-size:1.6em;line-height:1.25}h2{margin-top:1.6em}
.cta{display:block;background:#2a7de1;color:#fff;text-align:center;padding:14px;border-radius:10px;text-decoration:none;font-weight:600;margin:16px 0}
.d{background:#fff;border:1px solid #e1e4e8;border-radius:8px;padding:10px 12px;margin:8px 0}.d b{display:block}
.m{color:#5b6470;font-size:.92em}ul.c{columns:2;padding-left:18px}footer{color:#5b6470;font-size:.85em;margin:32px 0}
a{color:#1f63b8}"""


def page(title, desc, path, body):
    return f"""<!doctype html><html lang="sl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<meta name="description" content="{e(desc)}"><link rel="canonical" href="{BASE}/{path}"><style>{CSS}</style></head>
<body><main>{body}<footer>Podatki: ZZZS prek <a href="https://zdravniki.sledilnik.org">Sledilnik</a>
(CC BY 4.0). Stanje se lahko spremeni — pred obiskom pokličite ambulanto. Neodvisna stran, ni povezana z ZZZS.</footer>
</main></body></html>"""


def cta(muni=""):
    return (f'<a class="cta" href="https://t.me/{BOT}">🔔 Obvesti me v Telegramu, ko kdo{" v občini " + e(muni) if muni else ""} '
            f'začne sprejemati</a>')


def doc(d):
    m = ", ".join(x for x in (d["inst"], d["address"], d["post"] or d["city"], d["phone"]) if x)
    link = d["orderform"] or d["website"]
    return (f'<div class="d"><b>{e(d["name"])}</b><span class="m">{e(m)}</span>'
            + (f'<br><a class="m" href="{e(link)}" rel="nofollow">{e(link)}</a>' if link.startswith("http") else "") + "</div>")


def main():
    docs, _ = load()
    today = time.strftime("%-d. %-m. %Y")
    by_muni = {}
    for d in docs.values():
        if d["municipality"] and "?" not in d["municipality"]:
            by_muni.setdefault(d["municipality"], []).append(d)
    os.makedirs(OUT, exist_ok=True)
    urls, index = [""], []
    for muni in sorted(by_muni, key=norm):
        ds, s = by_muni[muni], slug(muni)
        acc = [d for d in ds if d["accepts"] == "y"]
        gp = sum(1 for d in acc if d["type"] == "gp")
        parts = [f"<h1>Prosti zdravniki {e(muni)} — kdo sprejema nove paciente</h1>",
                 f"<p>Stanje {today}: v občini {e(muni)} sprejema nove paciente <b>{len(acc)}</b> od {len(ds)} zdravnikov "
                 f"(družinskih zdravnikov: <b>{gp}</b>).</p>", cta(muni)]
        for t, (label, _) in TYPES.items():
            tl = [d for d in ds if d["type"] == t]
            if not tl:
                continue
            ta = sorted((d for d in tl if d["accepts"] == "y"), key=lambda d: norm(d["name"]))
            parts.append(f"<h2>{label} — sprejema {len(ta)} od {len(tl)}</h2>")
            parts += [doc(d) for d in ta] or ["<p>Trenutno nihče ne sprejema. Prijavite se na obvestilo zgoraj.</p>"]
        parts.append(cta(muni) + '<p><a href="../">← Vse občine</a></p>')
        os.makedirs(os.path.join(OUT, s), exist_ok=True)
        with open(os.path.join(OUT, s, "index.html"), "w") as f:
            f.write(page(f"Prosti zdravniki {muni} ({today}) — kdo sprejema nove paciente",
                         f"Seznam zdravnikov v občini {muni}, ki sprejemajo nove paciente: družinski zdravnik, pediater, "
                         f"ginekolog, zobozdravnik. Brezplačno obvestilo v Telegramu.", f"{s}/", "\n".join(parts)))
        urls.append(f"{s}/")
        index.append(f'<li><a href="{s}/">{e(muni)}</a> ({len(acc)})</li>')
    total = sum(1 for d in docs.values() if d["accepts"] == "y")
    body = (f"<h1>Prosti zdravniki v Sloveniji — kdo sprejema nove paciente</h1><p>Stanje {today}: nove paciente sprejema "
            f"<b>{total}</b> od {len(docs)} zdravnikov. Izberite občino ali se prijavite na obvestilo, ko kdo v vaši občini "
            f"začne sprejemati.</p>{cta()}<ul class=\"c\">{''.join(index)}</ul>")
    with open(os.path.join(OUT, "index.html"), "w") as f:
        f.write(page(f"Prosti zdravniki v Sloveniji ({today}) — kdo sprejema nove paciente",
                     "Kateri osebni zdravnik, pediater, ginekolog ali zobozdravnik sprejema nove paciente v vaši občini. "
                     "Brezplačno obvestilo v Telegramu.", "", body))
    with open(os.path.join(OUT, "sitemap.xml"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + "".join(f"<url><loc>{BASE}/{u}</loc></url>" for u in urls) + "</urlset>")
    with open(os.path.join(OUT, "robots.txt"), "w") as f:
        f.write(f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n")
    print(f"{len(urls) - 1} municipality pages, {total} accepting → {OUT}")


if __name__ == "__main__":
    main()
