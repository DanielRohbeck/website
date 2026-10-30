"""Build danielrohbeck.de (static site, English at /, German at /de/).

Usage (from the repo root):
    python3 src/site.py [out-dir] [preview-en.html] [preview-de.html]

- out-dir: defaults to docs/, which GitHub Pages serves. Contains index.html, de/, imprint/, privacy/,
  de/impressum/, de/datenschutz/, 404.html, assets/, fonts/, favicon.svg, robots.txt, CNAME, .nojekyll
  (sitemap.xml only when INDEXING is on).
- preview-*.html: optional single self-contained review files (imprint/privacy as in-page views).

Sources: texts in src/content.py (EN) and src/content_de.py (DE); photos, portrait and fonts in src/assets/.
Requires Pillow; fonttools + brotli for the Open Graph image.

Checks at the end of every page: no euro amounts, no external font/CDN requests, no review markers.
Additional terms that must never appear publicly are read from a file outside the repo
(env SITE_PRIVATE_TERMS, default ~/.danielrohbeck-private-terms.txt, one term per line).
"""
import base64, html, io, json, os, re, shutil, sys
from pathlib import Path

import content as _EN
import content_de as _DE
from content import IMPRINT, IMAGES, PORTRAIT, FONTS

SRC = Path(__file__).resolve().parent
ASSETS = SRC / "assets"
REPO = SRC.parent

# Language-dependent texts; set by use_lang() before rendering ("en" at /, "de" at /de/)
SITE, HOME, CONTACT, CASES, UI = _EN.SITE, _EN.HOME, _EN.CONTACT, _EN.CASES, _EN.UI
LANGS = {"en": _EN, "de": _DE}
# Optional review previews; the language chip of one preview links to the other
PREVIEW_URL = {"en": "", "de": ""}

# Link-only phase: every page carries noindex; robots.txt allows crawling (so search engines can
# see the noindex) but announces no sitemap. Set True to go public and indexed.
INDEXING = False
NOINDEX = "noindex,noarchive"


def use_lang(code):
    global SITE, HOME, CONTACT, CASES, UI
    m = LANGS[code]
    SITE, HOME, CONTACT, CASES, UI = m.SITE, m.HOME, m.CONTACT, m.CASES, m.UI


def other_lang():
    return "de" if UI["lang"] == "en" else "en"

BASE = f"https://{_EN.SITE['domain']}"
E = html.escape


def read_asset(name):
    return (ASSETS / name).read_bytes()


# ---------------------------------------------------------------- text helpers
def md(s):
    """escape, then **x** -> <b>x</b>"""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", E(s, quote=False))


# ---------------------------------------------------------------- render context
class Ctx:
    def __init__(self, preview, alt=""):
        self.preview = preview
        self.root = "" if preview else UI["home"]   # prefix for home links on sub pages
        self.alt = alt                               # same page in the other language

    def img(self, key, sizes, eager=False, alt=""):
        pos = f' style="object-position:{IMAGES[key]["pos"]}"' if IMAGES[key].get("pos") else ""
        if self.preview:
            return f'<img data-k="{key}" alt="{E(alt)}"{pos}>'
        ws = IMAGES[key]["widths"]
        srcset = ", ".join(f"/assets/img/{key}-{w}.jpg {w}w" for w in ws)
        mid = next((w for w in ws if w >= 1000), ws[-1])
        load = 'fetchpriority="high"' if eager else 'loading="lazy" decoding="async"'
        return f'<img src="/assets/img/{key}-{mid}.jpg" srcset="{srcset}" sizes="{sizes}" alt="{E(alt)}" {load}{pos}>'

    def portrait(self, cls, alt):
        # pt-sm (phone circle) uses a square crop around the head, pt-lg the full portrait aligned to the top
        sq = cls == "pt-sm"
        key, file, wh = ("portrait_sq", "portrait-sq.jpg", 'width="240" height="240"') if sq else ("portrait", "portrait.jpg", 'width="397" height="554"')
        src = f'data-k="{key}"' if self.preview else f'src="/assets/{file}"'
        return f'<img class="{cls}" {src} alt="{E(alt)}" {wh}>'

    def legal_href(self, which):
        return f"#{which}" if self.preview else UI["legal"][which]


def credit(key):
    return f'<span class="credit">{E(IMAGES[key]["credit"])}</span>'


def lang_chip(c):
    """DE | EN chip: current language as pill, the other as link (keeps the open case via site.js)."""
    me, other = UI["lang"], other_lang()
    tgt = ' target="_blank" rel="noopener"' if c.preview else ""
    link = (f'<a href="{E(c.alt)}" hreflang="{other}" lang="{other}" data-lang-base="{E(c.alt)}"'
            f' title="{E(UI["switch_title"])}"{tgt}>{other.upper()}</a>')
    pill = f'<b>{me.upper()}</b>'
    return f'<span class="lang">{link + " " + pill if me == "en" else pill + " " + link}</span>'


def bar(c, active=None, solid=False, home_href=None):
    h = home_href if home_href is not None else c.root
    cur = lambda n: ' aria-current="page"' if n == active else ""
    nav = (f'<nav class="nav" aria-label="{E(UI["nav_label"])}"><a href="{h}#work"{cur("work")}>{E(UI["nav_work"])}</a>'
           f'<a href="{h}#about">{E(UI["nav_about"])}</a><a href="{h}#contact">{E(UI["nav_contact"])}</a></nav>')
    return (f'<header class="bar{" solid" if solid else ""}"><a class="brand" href="{h}#top">Daniel Rohbeck</a>'
            f'{"" if solid else nav}{lang_chip(c)}</header>')


def hero_case(c, case):
    return f"""<section class="hero case">
  <div class="media">{c.img(case['img'], '100vw', eager=False)}</div>
  <div class="veil"></div>{credit(case['img'])}
  {bar(c, active='work', home_href='')}
  <div class="hero-in">
    <a class="back" href="#work">{E(UI['all_work'])}</a>
    <p class="eyebrow-w">{E(case['eyebrow'])}</p>
    <h1 tabindex="-1">{E(case['title'])}</h1>
    <p class="lead">{E(case['lead'])}</p>
  </div>
</section>"""


# ---------------------------------------------------------------- home
def nobreak(text):
    """Escape; words written with U+2011 get a normal hyphen and no line break (the fonts lack U+2011)."""
    return re.sub(r"(\S*‑\S*)", lambda m: f'<span class="nw">{m.group(1).replace(chr(0x2011), "-")}</span>', E(text))


def chapter(label, meta):
    """Light chapter separator: hairline with a short teal tick, label left, meta right."""
    return f'<div class="chap"><p class="eyebrow">{E(label)}</p><p class="chap-m">{E(meta)}</p></div>'


def home(c):
    k = "".join(f'<div class="kpi{" hl" if i == 0 else ""}"><div class="n{" word" if x.get("word") else ""}">{E(x["n"])}</div><p>{E(x["t"])}</p></div>'
                for i, x in enumerate(HOME["kpis"]))
    f = HOME["feature"]
    cards = "".join(
        f'<a class="card" href="#{x["case"]}"><div class="frame"><div class="media">'
        f'{c.img(CASES[x["case"]]["img"], "(min-width: 760px) 30vw, 88px")}</div>{credit(CASES[x["case"]]["img"])}</div>'
        f'<div><p class="ey">{E(x["years"])}<span class="w"> · {E(x["extra"])}</span></p>'
        f'<b class="ct">{E(x["title"])}<span class="w"> →</span></b></div></a>'
        for x in HOME["cards"])
    row = lambda t, sub, meta="": (f'<div class="row"><div><b class="rt">{E(t)}</b><p class="rs">{E(sub)}</p></div>'
                                    + (f'<span class="rm">{E(meta)}</span>' if meta else "") + "</div>")
    career = "".join(row(t, sub, yrs) for t, yrs, sub in HOME["career"])
    side = "".join(row(t, sub) for t, sub in HOME["side"])
    persona = "".join(row(t, sub) for t, sub in HOME["personality"])
    thread = "".join(f'<a class="step" href="#{x["case"]}"><span class="yr">{E(x["yr"])}</span><b>{E(x["name"])}</b>'
                     f'<span class="sc">{E(x["scale"])}</span></a>' for x in HOME["timeline"])
    return f"""<div class="view on" id="home" data-view="home">
<section class="hero home" id="top">
  <div class="media">{c.img('hero', '100vw', eager=True)}</div>
  <div class="veil"></div>{credit('hero')}
  {bar(c, home_href='')}
  <div class="hero-in">
    <div class="hero-txt">
      {c.portrait('pt-sm', 'Daniel Rohbeck')}
      <p class="eyebrow-w">{E(HOME['eyebrow'])}</p>
      <h1>{nobreak(HOME['headline'])}</h1>
    </div>
    {c.portrait('pt-lg', UI['portrait_alt'])}
  </div>
</section>
<section class="band" aria-label="{E(UI['key_figures'])}"><div class="wrap kpis">{k}</div></section>
<section class="work" id="work">
  <div class="wrap">
    {chapter(HOME['work_label'], HOME['work_meta'])}
    <div class="work-head"><h2 class="h-xl">{HOME['work_title']}</h2><p class="w">{E(HOME['work_lead'])}</p></div>
    <nav class="thread" aria-label="{E(UI['timeline'])}">{thread}</nav>
    <a class="feature" href="#{f['case']}">
      <div class="frame"><div class="media">{c.img('mbco', '(min-width: 1390px) 1280px, 92vw')}</div>{credit('mbco')}</div>
      <div class="fcard"><p class="eyebrow">{E(f['eyebrow'])}</p><h3>{E(f['title'])}<span class="n"> →</span></h3>
        <p class="fl">{E(f['lead'])}</p><p class="fm">{E(f['meta'])}</p></div>
    </a>
    <div class="cards">{cards}</div>
  </div>
</section>
<section class="about" id="about">
  <div class="wrap">
    {chapter(HOME['about_label'], HOME['about_meta'])}
    <div class="about-head"><h2 class="h-xl">{E(HOME['about_title'])}</h2><p>{E(HOME['about_lead'])}</p></div>
    <div class="about-grid">
      <div><h3 class="eyebrow">{E(UI['career'])}</h3><div class="rows">{career}</div><p class="edu">{E(HOME['education'])}</p></div>
      <div><h3 class="eyebrow">{E(UI['side'])}</h3><div class="rows">{side}</div>
        <h3 class="eyebrow grp">{E(UI['personality'])}</h3><div class="rows">{persona}</div></div>
    </div>
  </div>
</section>
</div>"""


# ---------------------------------------------------------------- case
def section(s, alt):
    head = f'<header><p class="eyebrow">{E(s["label"])}</p><h2>{E(s["title"])}</h2>'
    if s.get("note"):
        head += f'<p class="note">{E(s["note"])}</p>'
    head += "</header>"
    b = ""
    if s.get("points"):
        b += '<ul class="pts">' + "".join(f"<li>{md(p)}</li>" for p in s["points"]) + "</ul>"
    if s.get("tiles"):
        b += '<div class="tiles">' + "".join(f'<div class="tile"><h3>{E(h)}</h3><p>{E(p)}</p></div>' for h, p in s["tiles"]) + "</div>"
    if s.get("stages"):
        b += '<div class="stages">' + "".join(
            f'<div class="stage{" dashed" if g["dashed"] else ""}"><p class="k">{E(g["k"])}</p><h3>{E(g["h"])}</h3>'
            f'<p class="d">{E(g["p"])}</p><p class="st">● {E(g["st"])}</p></div>' for g in s["stages"]) + "</div>"
    if s.get("foundation"):
        b += f'<div class="found"><span>{E(UI["foundation"])}</span><p>{E(s["foundation"])}</p></div>'
    if s.get("bridge"):
        b += f'<p class="bridge"><span class="lbl">{E(UI["led_to"])}</span><span>{md(s["bridge"])}</span></p>'
    if s.get("full"):
        parts = "".join(f"<h4>{E(x[2:])}</h4>" if x.startswith("# ") else f"<p>{md(x)}</p>" for x in s["full"])
        b += (f'<details class="full"><summary><span class="pl" aria-hidden="true"></span>{E(s["full_label"])}</summary>'
              f'<div class="txt">{parts}</div></details>')
    return f'<section class="cs{" alt" if alt else ""}"><div class="wrap">{head}<div class="body">{b}</div></div></section>'


def case_view(c, slug, case):
    kp = "".join(f'<div class="kpi"><div class="n{" word" if x.get("word") else ""}">{E(x["n"])}</div><p>{E(x["t"])}</p></div>'
                 for x in case["kpis"])
    facts = "".join(f"<div><dt>{E(k)}</dt><dd>{E(v)}</dd></div>" for k, v in case["facts"])
    secs = "".join(section(s, i % 2 == 1) for i, s in enumerate(case["sections"]))
    last_alt = (len(case["sections"]) - 1) % 2 == 1
    src = ""
    if case.get("sources"):
        items = "".join(
            f'<li><a href="{E(r["href"])}" target="_blank" rel="noopener"><span class="out">{E(r["outlet"])}</span>'
            f'<span class="hl"{" lang=" + chr(34) + r["lang"] + chr(34) if r.get("lang") else ""}>{E(r["hl"])} <i>↗</i></span>'
            + (f'<span class="nt">{E(r["note"])}</span>' if r.get("note") else "") + "</a></li>" for r in case["sources"])
        src = (f'<section class="src{" alt" if last_alt else ""}"><div class="wrap"><header><p class="eyebrow">{E(UI["on_record"])}</p>'
               f'<h2>{E(UI["public_sources"])}</h2></header><div class="body"><p class="si">{E(case["src_intro"])}</p>'
               f'<ul>{items}</ul></div></div></section>')
    nid, ney = case["next"]
    nx = CASES[nid]
    nxt = (f'<section class="next"><a class="wrap" href="#{nid}"><div class="frame"><div class="media">'
           f'{c.img(nx["img"], "(min-width: 760px) 45vw, 100vw")}</div>{credit(nx["img"])}</div>'
           f'<div><p class="ey">{E(ney)}</p><h3>{E(nx["title"])} →</h3></div></a></section>')
    return f"""<article class="view" id="{slug}" data-view="case" aria-label="{E(UI['case_study'])}: {E(case['title'])}">
{hero_case(c, case)}
<section class="band" aria-label="{E(UI['key_figures'])}"><div class="wrap kpis k3">{kp}</div></section>
<section class="facts"><dl class="wrap">{facts}</dl></section>
{secs}{src}
<section class="learn"><div class="wrap"><p class="eyebrow">{E(UI['learning'])}</p><blockquote class="q"><span>{UI['q'][0]}</span>{E(case['learning'])}<span>{UI['q'][1]}</span></blockquote></div></section>
{nxt}
</article>"""


# ---------------------------------------------------------------- legal
def imprint_body(c):
    adr = "<br>".join(E(a) for a in IMPRINT["address"])
    return f"""<p class="eyebrow">{E(UI['imprint_eyebrow'])}</p>
<h1 tabindex="-1">{E(UI['imprint'])}</h1>
<div lang="de">
<p><b>Angaben gemäß § 5 DDG</b></p>
<p>{E(IMPRINT['name'])}<br>{adr}</p>
<h2>Kontakt</h2>
<p>E-Mail: {E(IMPRINT['email'])}</p>
<h2>Verantwortlich für den Inhalt nach § 18 Abs. 2 MStV</h2>
<p>{E(IMPRINT['name'])}, Anschrift wie oben.</p>
<h2>Haftung für Links</h2>
<p>Diese Seite verweist auf externe Websites Dritter. Für deren Inhalte ist stets der jeweilige Anbieter verantwortlich. Bei Bekanntwerden von Rechtsverletzungen entferne ich die betreffenden Links umgehend.</p>
<h2>Inhalte</h2>
<p>Diese Website ist ein persönliches Profil mit Arbeitsproben. Sie gibt meine eigene Sicht wieder und keine Stellungnahme eines früheren oder heutigen Arbeitgebers. Genannte Marken und Produktnamen gehören ihren jeweiligen Inhabern.</p>
<h2>Bildnachweise</h2>
<p>Fotos von Rodrigo Soares, Wolkensegler Agentur, Winston Chen, Daniel Stenholm und ein Segel-Foto über Unsplash (Unsplash-Lizenz). Portrait: privat.</p>
</div>"""


def privacy_body(c):
    return f"""<p class="eyebrow">{E(UI['privacy_eyebrow'])}</p>
<h1 tabindex="-1">{E(UI['privacy'])}</h1>
<div lang="de">
<p><b>Datenschutzerklärung</b> · Stand: Oktober 2026</p>
<h2>1. Verantwortlicher</h2>
<p>{E(IMPRINT['name'])}, Anschrift und E-Mail siehe <a class="in" href="{c.legal_href('imprint')}">Impressum</a>.</p>
<h2>2. Kurz gesagt</h2>
<ul><li>Keine Cookies, kein Tracking, keine Analyse-Tools, keine Werbung.</li>
<li>Schriften und Bilder werden von dieser Domain geladen, nicht von Google oder anderen Drittanbietern.</li>
<li>Es gibt kein Kontaktformular. Kontakt läuft über LinkedIn oder per E-Mail.</li></ul>
<h2>3. Hosting und Server-Protokolle</h2>
<p>Die Website wird über GitHub Pages bereitgestellt (GitHub, Inc., 88 Colin P. Kelly Jr. Street, San Francisco, CA 94107, USA). Beim Aufruf verarbeitet GitHub technisch notwendige Daten, insbesondere die IP-Adresse, Datum und Uhrzeit, die aufgerufene Seite, Referrer und Browser-Kennung, um die Seite auszuliefern und die Sicherheit des Dienstes zu gewährleisten. Rechtsgrundlage ist Art. 6 Abs. 1 lit. f DSGVO; mein berechtigtes Interesse liegt in einer sicheren und zuverlässigen Bereitstellung der Seite. Dabei können Daten in die USA übermittelt werden. GitHub ist nach dem EU-US Data Privacy Framework zertifiziert. Details: <a class="in" href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement" rel="noopener">GitHub General Privacy Statement</a>.</p>
<h2>4. Externe Links</h2>
<p>Die Seite verlinkt auf Presseartikel, LinkedIn und andere Websites. Erst wenn Sie einen Link anklicken, werden Daten an den jeweiligen Anbieter übertragen; dort gelten dessen Datenschutzbestimmungen.</p>
<h2>5. Kontakt per E-Mail oder LinkedIn</h2>
<p>Wenn Sie mich kontaktieren, verarbeite ich Ihre Angaben, um Ihre Anfrage zu beantworten (Art. 6 Abs. 1 lit. b bzw. f DSGVO), und lösche sie, sobald sie dafür nicht mehr nötig sind.</p>
<h2>6. Ihre Rechte</h2>
<p>Sie haben das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung, Datenübertragbarkeit und Widerspruch (Art. 15–21 DSGVO) sowie auf Beschwerde bei einer Datenschutz-Aufsichtsbehörde, etwa dem Landesbeauftragten für den Datenschutz und die Informationsfreiheit Baden-Württemberg.</p>
</div>"""


def legal_article(c, body):
    back = "#top" if c.preview else UI["home"]
    return f'<article class="legal"><a class="back" href="{back}">{E(UI["back_start"])}</a>\n{body}\n</article>'


# ---------------------------------------------------------------- shared
def cv_link(c):
    """Download button for the public CV (PDF in src/assets/cv/, built with the CV master in public mode)."""
    if c.preview or not UI.get("cv"):
        return ""
    return f'<a class="cta2" href="{UI["cv"]["href"]}" download>{E(UI["cv"]["label"])} ↓</a>'


def contact_footer(c):
    return f"""<section class="contact" id="contact">
  <p class="coord">{E(CONTACT['coord'])}</p>
  <h2>{E(CONTACT['title'])}</h2>
  <p class="sub">{E(CONTACT['text'])}</p>
  <div class="ctas"><a class="cta" href="{SITE['linkedin']}" target="_blank" rel="noopener">{E(CONTACT['cta'])} ↗</a>{cv_link(c)}</div>
</section>
<footer class="foot"><span>{E(UI['footer'])}</span>
<nav aria-label="{E(UI['legal_label'])}"><a href="{c.legal_href('imprint')}">{E(UI['imprint'])}</a><a href="{c.legal_href('privacy')}">{E(UI['privacy'])}</a></nav></footer>"""


CSS = r"""
:root{--navy:#10266E;--ink:#0E1E2A;--text:#3A4E60;--bg:#F7F8F8;--bg2:#EEF2F4;--teal:#35C6AE;--teal-t:#127A69;
--muted:#587085;--line:#C9D6DE;--line2:#E2E9EE;--band-t:#A9BDCD;--band-l:#2C4A5C;--gut:clamp(20px,4.5vw,56px);
--mono:"IBM Plex Mono",ui-monospace,Consolas,monospace;color-scheme:light}
*{box-sizing:border-box}
html{scroll-behavior:smooth;-webkit-text-size-adjust:100%}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
body{margin:0;background:var(--bg);color:var(--text);font-family:Archivo,Aptos,Calibri,system-ui,sans-serif;font-size:17px;line-height:1.6;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}a:hover{color:var(--teal-t)}
p,h1,h2,h3,h4,ul,dl,dd,blockquote{margin:0}
img{display:block;max-width:100%}
summary{list-style:none}summary::-webkit-details-marker{display:none}
:focus-visible{outline:2px solid var(--teal);outline-offset:3px;border-radius:2px}
h1:focus{outline:none}
.skip{position:absolute;left:-9999px;top:12px;z-index:10;background:#fff;color:var(--ink);padding:8px 14px;border-radius:6px;font-weight:600}.skip:focus{left:12px}
.wrap{max-width:1280px;margin:0 auto}
body{overflow-wrap:break-word}
html[lang=de] :is(.kpi p,.facts dd,.tile p,.stage .d,.step .sc){hyphens:auto;-webkit-hyphens:auto}
@media (max-width:759px){html[lang=de] :is(.pts li,.rs,.card .ct,.full p){hyphens:auto;-webkit-hyphens:auto}}
.eyebrow{font:500 12px/1.4 var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--teal-t)}
.js [data-view]:not(.on){display:none}

/* photos */
.media{position:absolute;inset:0;overflow:hidden;background:var(--navy)}
.media img{width:100%;height:100%;object-fit:cover;filter:saturate(1.35) brightness(1.12) contrast(1.04)}
.credit{position:absolute;left:6px;bottom:6px;z-index:1;max-width:calc(100% - 12px);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font:500 10px/1.3 Archivo,system-ui,sans-serif;color:#fff;background:rgba(14,30,42,.62);padding:2px 6px;border-radius:4px;pointer-events:none}

/* hero */
.hero{position:relative;background:var(--navy);color:#fff}
.hero.home{height:clamp(600px,92vh,780px)}
.hero.case{height:clamp(520px,80vh,720px)}
.hero .credit{left:4px;bottom:4px}
.veil{position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(90deg,rgba(16,38,110,.6) 0%,rgba(16,38,110,.35) 45%,rgba(16,38,110,0) 70%),linear-gradient(180deg,rgba(16,38,110,.55) 0%,rgba(16,38,110,0) 22%,rgba(16,38,110,.2) 50%,rgba(16,38,110,.85) 100%)}
.hero.case .veil{background:linear-gradient(90deg,rgba(16,38,110,.6) 0%,rgba(16,38,110,.35) 50%,rgba(16,38,110,0) 75%),linear-gradient(180deg,rgba(16,38,110,.55) 0%,rgba(16,38,110,0) 22%,rgba(16,38,110,.25) 50%,rgba(16,38,110,.85) 100%)}
.bar{position:absolute;top:0;left:0;right:0;z-index:2;display:flex;align-items:center;gap:28px;padding:0 var(--gut);height:76px;color:#fff}
.bar.solid{position:static;background:var(--ink)}
.bar a:hover{color:#BDEFE6}
.brand{font-stretch:72%;font-weight:700;font-size:22px;line-height:1}
.nav{display:flex;gap:28px;margin-left:auto;font-size:15px;font-weight:500}
.nav a{padding:4px 0;border-bottom:2px solid transparent}
.nav a[aria-current]{border-bottom-color:var(--teal)}
.lang{margin-left:auto;flex:none;display:inline-flex;align-items:center;gap:6px;font:500 11px var(--mono);letter-spacing:.08em;cursor:default}
.lang b{padding:3px 8px;border-radius:999px;background:var(--teal);color:var(--ink);font-weight:500}
.lang a{padding:3px 4px;opacity:.85;border-bottom:1px solid transparent}
.lang a:hover{opacity:1;color:#fff;border-bottom-color:var(--teal)}
.hero-in{position:absolute;z-index:1;left:var(--gut);right:var(--gut);bottom:clamp(32px,5vw,64px)}
.hero.home .hero-in{display:flex;gap:56px;align-items:flex-end;justify-content:space-between}
.hero.case .hero-in{max-width:980px}
.hero-txt{max-width:1000px}
.eyebrow-w{font:500 12px/1.4 var(--mono);letter-spacing:.16em;text-transform:uppercase;color:#fff;text-shadow:0 1px 8px rgba(16,38,110,.6)}
.hero h1{margin-top:20px;font-stretch:66%;font-weight:700;font-size:clamp(44px,7.4vw,96px);line-height:.96;letter-spacing:-.015em;text-wrap:balance;max-width:15ch}
.hero.home h1{max-width:20ch}
.nw{white-space:nowrap}
.hero.case h1{margin-top:16px;font-size:clamp(42px,6.6vw,88px);max-width:none}
.hero.case .eyebrow-w{margin-top:28px}
.back{display:inline-flex;font-weight:500;font-size:15px}
.lead{margin-top:20px;max-width:40ch;font-size:clamp(18px,1.7vw,22px);font-weight:300;line-height:1.4}
.pt-lg{flex:none;width:clamp(160px,17vw,220px);height:auto;aspect-ratio:4/5;object-fit:cover;object-position:50% 0%;border-radius:8px;border:4px solid var(--bg)}
.pt-sm{display:none;width:68px;height:68px;border-radius:50%;object-fit:cover;border:2px solid #fff;margin-bottom:20px}

/* key figures */
.band{background:var(--ink);padding:clamp(28px,4vw,44px) var(--gut)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,150px),1fr));gap:clamp(20px,3vw,40px)}
.kpis.k3{grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr))}
.kpi{border-left:2px solid var(--band-l);padding-left:clamp(12px,1.6vw,20px)}
.kpi.hl{border-left-color:var(--teal)}
.kpi .n{font-stretch:70%;font-weight:700;font-size:clamp(40px,5vw,60px);line-height:1;color:#fff}
.k3 .kpi .n{line-height:1.02}
.kpi .n.word{font-size:clamp(26px,2.6vw,36px);hyphens:manual;-webkit-hyphens:manual}
.kpi p{margin-top:8px;font-size:15px;color:var(--band-t)}
.k3 .kpi p{margin-top:10px;max-width:30ch}

/* work */
.work{padding:clamp(56px,9vw,112px) var(--gut) 0}
.work-head{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:20px 40px}
.work-head p{max-width:40ch}
.h-xl{font-stretch:70%;font-weight:700;font-size:clamp(40px,5.4vw,64px);line-height:1;color:var(--ink)}
.feature{display:block;position:relative;margin-top:clamp(28px,4vw,48px)}
.feature .frame{position:relative;height:clamp(260px,44vw,560px);border-radius:12px;overflow:hidden}
.fcard{position:absolute;right:32px;bottom:32px;width:460px;padding:32px;border-radius:10px;background:var(--bg)}
.fcard .eyebrow{font-size:11px;letter-spacing:.14em}
.fcard h3{margin-top:12px;font-stretch:70%;font-weight:700;font-size:44px;line-height:1;color:var(--ink)}
.fcard h3 .n{display:none}
.fcard .fl{margin-top:14px}
.fcard .fm{margin-top:18px;font:500 12px var(--mono);color:var(--ink)}
.feature:hover h3,.card:hover .ct,.next a:hover h3{color:var(--teal-t)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:32px;margin-top:32px}
.card{display:flex;flex-direction:column;gap:18px}
.card .frame{position:relative;height:400px;border-radius:10px;overflow:hidden}
.card .ey{font:500 11px var(--mono);letter-spacing:.12em;color:var(--muted)}
.card .ct{display:block;margin-top:6px;font-stretch:72%;font-weight:700;font-size:28px;line-height:1.08;color:var(--ink)}

/* about */
.about{padding:clamp(72px,9vw,112px) var(--gut)}
.about-head{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:20px 40px;margin-bottom:clamp(40px,5vw,64px)}
.about-head .h-xl{max-width:16ch;text-wrap:balance}
.about-head p{max-width:40ch}
.about-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:clamp(48px,6vw,80px)}
.about-grid h3.eyebrow{font-size:12px}

/* chapter separator */
.chap{position:relative;display:flex;justify-content:space-between;align-items:baseline;gap:16px;border-top:1px solid var(--line);padding-top:18px;margin-bottom:clamp(28px,3.5vw,44px)}
.chap::before{content:"";position:absolute;left:0;top:-2px;width:28px;height:3px;background:var(--teal)}
.chap-m{font:500 12px var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}

/* timeline */
.thread{position:relative;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));margin:clamp(36px,4.5vw,56px) 0 clamp(8px,1.6vw,24px)}
.thread::before{content:"";position:absolute;left:0;right:0;top:7px;height:2px;background:linear-gradient(90deg,var(--line),var(--teal))}
.step{position:relative;padding-top:32px;padding-right:12px;display:grid;gap:2px}
.step::before{content:"";position:absolute;left:0;top:0;width:16px;height:16px;border-radius:50%;background:var(--bg);border:2px solid var(--teal);box-sizing:border-box}
.step:last-child::before{background:var(--teal)}
.step .yr{font:500 12px var(--mono);letter-spacing:.08em;color:var(--teal-t)}
.step b{font-stretch:72%;font-weight:700;font-size:clamp(19px,2vw,26px);line-height:1.1;color:var(--ink)}
.step .sc{font-size:14px;color:var(--muted)}
.step:hover b{color:var(--teal-t)}
/* about lists: one row style for career, side projects and personality */
.rows{margin-top:20px}
.row{display:flex;justify-content:space-between;align-items:baseline;gap:20px;padding:16px 0;border-top:1px solid var(--line)}
.row:last-child{border-bottom:1px solid var(--line)}
.rt{display:block;font-stretch:72%;font-weight:700;font-size:22px;line-height:1.15;color:var(--ink)}
.rs{margin-top:4px;font-size:15px;line-height:1.5;max-width:52ch}
.rm{flex:none;font:500 13px var(--mono);color:var(--muted);white-space:nowrap}
.grp{margin-top:clamp(40px,4.5vw,56px)}
.edu{margin-top:16px;font-size:14px;color:var(--muted)}

/* case */
.facts{padding:40px var(--gut);border-bottom:1px solid var(--line)}
.facts dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:24px 40px}
.facts dt{font:500 11px var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.facts dd{margin:6px 0 0;color:var(--ink);font-size:15px;line-height:1.45}
.cs{padding:clamp(56px,8vw,104px) var(--gut)}
.cs.alt,.src.alt{background:var(--bg2)}
.cs .wrap,.src .wrap{display:flex;flex-wrap:wrap;gap:24px clamp(32px,6vw,96px)}
.cs header,.src header{flex:1 1 240px;max-width:360px}
.cs h2,.src h2{margin-top:12px;font-stretch:70%;font-weight:700;font-size:clamp(30px,3.4vw,42px);line-height:1.02;color:var(--ink);text-wrap:balance}
.note{margin-top:14px;font-size:14px;color:var(--muted)}
.body{flex:3 1 520px;min-width:0}
.body b{color:var(--ink);font-weight:600}
.pts{list-style:none;padding:0;display:grid;gap:14px}
.pts li{position:relative;padding-left:26px;max-width:62ch}
.pts li::before{content:"";position:absolute;left:0;top:.55em;width:10px;height:10px;border-radius:50%;box-shadow:inset 0 0 0 2px var(--teal);background:rgba(53,198,174,.15)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:16px;margin-top:28px}
.tiles:first-child{margin-top:0}
.tile{background:#fff;border:1px solid var(--line2);border-radius:10px;padding:22px}
.tile::before{content:"";display:block;width:28px;height:3px;background:var(--teal);margin-bottom:16px}
.tile h3{font-size:17px;font-weight:600;line-height:1.4;color:var(--ink)}
.tile p{margin-top:6px;font-size:15px;line-height:1.55}
.stages{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:12px}
.stage{background:#fff;border-radius:10px;padding:20px;border-top:3px solid var(--teal)}
.stage.dashed{border-top-style:dashed}
.stage .k{font:500 11px var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.stage h3{margin-top:10px;font-size:17px;font-weight:600;line-height:1.4;color:var(--ink)}
.stage .d{margin-top:8px;font-size:15px;line-height:1.5}
.stage .st{margin-top:14px;font:500 11px var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--teal-t)}
.found{margin-top:12px;border-radius:10px;background:rgba(53,198,174,.14);padding:18px 20px;display:flex;flex-wrap:wrap;gap:6px 20px}
.found span{flex:none;width:8rem;font:500 11px var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--teal-t);padding-top:3px}
.found p{flex:1 1 300px;font-size:15px}
.bridge{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline;margin-top:28px;padding:16px 18px;border-radius:10px;border:1px dashed var(--teal);font-size:15px;max-width:66ch}
.lbl{font:500 11px var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--teal-t)}
.full{margin-top:28px;border-top:1px solid var(--line)}
.full summary{cursor:pointer;padding-top:18px;font-weight:600;color:var(--ink);display:inline-flex;align-items:center;gap:10px}
.full summary:hover{color:var(--teal-t)}
.pl{display:grid;place-items:center;width:24px;height:24px;border-radius:50%;border:1px solid var(--line);color:var(--teal-t);font-weight:400;line-height:1}
.pl::before{content:"+"}.full[open] .pl::before{content:"−"}
.full .txt{padding-top:18px;display:grid;gap:1em;max-width:66ch}
.full h4{font-size:17px;font-weight:600;color:var(--ink);margin-top:.4em}
.src{padding:0 var(--gut) clamp(56px,8vw,104px)}
.src .wrap{border-top:1px solid var(--line);padding-top:clamp(40px,5vw,64px)}
.si{font-size:15px;max-width:60ch}
.src ul{list-style:none;padding:0;margin-top:14px}
.src li a{display:grid;gap:3px;padding:12px 0;border-top:1px solid var(--line2)}
.out{font:500 11px var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.src .hl{color:var(--ink);font-weight:500;line-height:1.35}
.src .hl i{font-style:normal;color:var(--teal-t)}
.src a:hover .hl{color:var(--teal-t)}
.nt{font-size:13px;color:var(--muted)}
.learn{background:var(--ink);padding:clamp(64px,9vw,120px) var(--gut)}
.learn .wrap{max-width:960px}
.learn .eyebrow{color:var(--teal)}
.q{margin-top:18px;font-stretch:70%;font-weight:600;font-size:clamp(30px,3.6vw,46px);line-height:1.12;color:#fff;text-wrap:balance}
.q span{color:var(--teal)}
.next{padding:clamp(56px,8vw,104px) var(--gut)}
.next a{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:clamp(20px,4vw,56px);align-items:center}
.next .frame{position:relative;height:clamp(200px,24vw,320px);border-radius:10px;overflow:hidden}
.next .ey{font:500 12px var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.next h3{margin-top:12px;font-stretch:70%;font-weight:700;font-size:clamp(32px,4vw,52px);line-height:1.02;color:var(--ink)}

/* contact, footer */
.contact{background:var(--ink);padding:clamp(64px,9vw,96px) var(--gut);text-align:center}
.coord{font:500 12px var(--mono);letter-spacing:.16em;color:var(--teal)}
.contact h2{margin-top:18px;font-stretch:66%;font-weight:700;font-size:clamp(56px,9vw,112px);line-height:.95;color:#fff}
.contact .sub{margin:20px auto 0;max-width:34ch;font-size:clamp(17px,1.6vw,20px);font-weight:300;color:var(--band-t)}
.ctas{display:flex;flex-wrap:wrap;justify-content:center;gap:12px;margin-top:32px}
.cta2{display:inline-flex;padding:15px 27px;border-radius:999px;border:1px solid var(--teal);color:#fff;font-weight:600;transition:background .15s}
.cta2:hover{color:var(--ink);background:var(--teal)}
.cta{display:inline-flex;padding:16px 28px;border-radius:999px;background:var(--teal);color:var(--ink);font-weight:600;transition:background .15s}
.cta:hover{color:var(--ink);background:#5DD6C2}
.foot{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px 28px;padding:24px var(--gut) 32px;font-size:13px;color:var(--muted)}
.foot nav{display:flex;gap:16px}

/* legal */
.legal{max-width:820px;margin:0 auto;padding:clamp(48px,7vw,96px) var(--gut)}
.legal>.eyebrow{margin-top:32px}
.legal h1{margin:14px 0 36px;font-stretch:66%;font-weight:700;font-size:clamp(44px,6vw,72px);line-height:1;color:var(--ink)}
.legal p,.legal ul{margin-bottom:14px}
.legal ul{padding-left:1.2em}
.legal h2{font-size:20px;line-height:1.3;color:var(--ink);margin:40px 0 10px}
.legal b{color:var(--ink)}
.legal a.in{color:var(--teal-t);text-decoration:underline;text-underline-offset:3px}

/* phone layout (design breakpoint 760 px) */
@media (max-width:759px){
  .nav,.w,.fcard .fl,.fcard .fm{display:none}
  .pt-lg{display:none}.pt-sm{display:block}
  .hero.home .hero-in{display:block}
  .fcard{position:static;width:auto;padding:0;background:none;margin-top:14px}
  .fcard .eyebrow{color:var(--muted);letter-spacing:0}
  .fcard h3{margin-top:0;font-size:28px;line-height:1.05}
  .fcard h3 .n{display:inline}
  .cards{grid-template-columns:minmax(0,1fr);gap:20px}
  .card{display:grid;grid-template-columns:88px minmax(0,1fr);gap:16px;align-items:center}
  .card .frame{height:88px;border-radius:8px}
  .card .credit{display:none}
  .card .ey{letter-spacing:0}
  .card .ct{margin-top:0;font-size:19px;line-height:1.1}
  .facts dl{grid-template-columns:repeat(2,minmax(0,1fr));gap:20px 24px}
  .rt{font-size:20px}.rs{font-size:14.5px}
  .step{padding-right:6px}.step b{font-size:16px}.step .yr{font-size:10.5px;letter-spacing:0}.step .sc{font-size:12px;line-height:1.35}
  .chap-m{font-size:11px}
}
"""

JS = r"""(function(){
var d=document,views=[].slice.call(d.querySelectorAll('[data-view]')),
    subs=views.filter(function(v){return v.dataset.view!=='home'}).map(function(v){return v.id});
function show(id){var sw=false;views.forEach(function(v){var on=id?v.id===id:v.dataset.view==='home';if(on!==v.classList.contains('on'))sw=true;v.classList.toggle('on',on)});return sw}
function langLinks(id){[].forEach.call(d.querySelectorAll('a[data-lang-base]'),function(a){var b=a.getAttribute('data-lang-base');if(b.charAt(0)!=='#')a.setAttribute('href',b+(id&&id!=='top'?'#'+id:''))})}
function route(id){
  if(typeof id!=='string')id=decodeURIComponent((location.hash||'').slice(1));
  langLinks(id);
  if(subs.indexOf(id)>-1){show(id);window.scrollTo({top:0,behavior:'instant'});var h=d.getElementById(id).querySelector('h1');if(h)h.focus({preventScroll:true});return}
  var sw=show(null),el=id&&id!=='top'?d.getElementById(id):null;
  if(el)requestAnimationFrame(function(){el.scrollIntoView({behavior:sw?'instant':'smooth'})});
  else window.scrollTo({top:0,behavior:sw?'instant':'smooth'});
}
d.addEventListener('click',function(e){
  if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
  var a=e.target.closest&&e.target.closest('a[href^="#"]');if(!a)return;
  var id=a.getAttribute('href').slice(1);if(id&&!d.getElementById(id))return;
  e.preventDefault();try{if(location.hash!=='#'+id)history.pushState(null,'','#'+id)}catch(x){}
  route(id);
});
window.addEventListener('hashchange',function(){route()});
window.addEventListener('popstate',function(){route()});
route();
})();
"""


def font_css(preview, fontdata):
    def src(name):
        if preview:
            return "data:font/woff2;base64," + base64.b64encode(fontdata[name]).decode()
        return f"/fonts/{name}"
    latin = "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD"
    ext = "U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C4,U+2113,U+2C60-2C7F,U+A720-A7FF"
    out = []
    for f, ur in (("archivo-latin-wdth.woff2", latin), ("archivo-latin-ext-wdth.woff2", ext)):
        out.append(f'@font-face{{font-family:"Archivo";font-style:normal;font-display:swap;font-weight:300 800;font-stretch:62% 125%;src:url({src(f)}) format("woff2");unicode-range:{ur}}}')
    for w in (400, 500):
        for f, ur in ((f"ibm-plex-mono-latin-{w}.woff2", latin), (f"ibm-plex-mono-latin-ext-{w}.woff2", ext)):
            if preview and "ext" in f:
                continue
            out.append(f'@font-face{{font-family:"IBM Plex Mono";font-style:normal;font-display:swap;font-weight:{w};src:url({src(f)}) format("woff2");unicode-range:{ur}}}')
    return "\n".join(out)


FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#10266E"/>
<text x="32" y="40" text-anchor="middle" font-family="Arial Narrow,Arial,sans-serif" font-weight="700" font-size="28" fill="#fff">DR</text>
<rect x="18" y="46" width="28" height="4" fill="#35C6AE"/></svg>"""


def head(title, desc, path, extra="", robots=None, alt_paths=None):
    """alt_paths: {"en": "/...", "de": "/de/..."} for hreflang alternates."""
    url = BASE + path
    lang = UI["lang"]
    alts = ""
    if alt_paths:
        alts = "".join(f'<link rel="alternate" hreflang="{k}" href="{BASE}{v}">\n' for k, v in alt_paths.items())
        alts += f'<link rel="alternate" hreflang="x-default" href="{BASE}{alt_paths["en"]}">\n'
    og = "og-image.jpg" if lang == "en" else f"og-image-{lang}.jpg"
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{E(title)}</title>
<meta name="description" content="{E(desc)}">
<link rel="canonical" href="{url}">
{alts}{f'<meta name="robots" content="{robots}">' if robots else ''}
<meta name="theme-color" content="#10266E">
<meta property="og:type" content="profile">
<meta property="og:locale" content="{UI['locale']}">
<meta property="og:title" content="{E(title)}">
<meta property="og:description" content="{E(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{BASE}/assets/{og}">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
<link rel="preload" href="/fonts/archivo-latin-wdth.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/assets/site.css">
<script>document.documentElement.classList.add('js')</script>
{extra}</head>
"""


# ---------------------------------------------------------------- images
PORTRAIT_SQ_BOX = (72, 2, 338, 268)   # head crop in the 397x554 portrait


def load_photo(spec):
    """Open a photo from src/assets/ and apply an optional crop box (left, top, right, bottom) in source pixels."""
    from PIL import Image
    im = Image.open(ASSETS / spec["file"]).convert("RGB")
    return im.crop(spec["crop"]) if spec.get("crop") else im


def portrait_square():
    from PIL import Image
    im = Image.open(ASSETS / PORTRAIT).convert("RGB")
    return im.crop(PORTRAIT_SQ_BOX).resize((240, 240), Image.LANCZOS)


def make_images(out):
    from PIL import Image
    d = out / "assets" / "img"; d.mkdir(parents=True)
    for key, spec in IMAGES.items():
        im = load_photo(spec)
        for w in spec["widths"]:
            r = im if w >= im.width else im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
            r.save(d / f"{key}-{w}.jpg", "JPEG", quality=74 if w >= 1600 else 78, optimize=True, progressive=True)
    (out / "assets" / "portrait.jpg").write_bytes(read_asset(PORTRAIT))
    portrait_square().save(out / "assets" / "portrait-sq.jpg", "JPEG", quality=86, optimize=True)


def preview_images():
    from PIL import Image
    res = {}
    for key, spec in IMAGES.items():
        im = load_photo(spec)
        w = 1400 if key in ("hero", "mbco") else 1100
        im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
        b = io.BytesIO(); im.save(b, "JPEG", quality=70, optimize=True, progressive=True)
        res[key] = "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()
    res["portrait"] = "data:image/jpeg;base64," + base64.b64encode(read_asset(PORTRAIT)).decode()
    b = io.BytesIO(); portrait_square().save(b, "JPEG", quality=86)
    res["portrait_sq"] = "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()
    return res


def make_og(out, fontdata, lines, name, icon=True):
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageEnhance
        from fontTools.ttLib import TTFont
        from fontTools.varLib.instancer import instantiateVariableFont
    except ImportError:
        print("Pillow/fonttools missing: og-image skipped"); return

    def font(name, size, axes=None):
        f = TTFont(io.BytesIO(fontdata[name]))
        if axes:
            f = instantiateVariableFont(f, axes)
        f.flavor = None; b = io.BytesIO(); f.save(b); b.seek(0)
        return ImageFont.truetype(b, size)

    W, H = 1200, 630
    im = load_photo(IMAGES["hero"])
    s = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    im = im.crop(((im.width - W) // 2, (im.height - H) // 2, (im.width - W) // 2 + W, (im.height - H) // 2 + H))
    im = ImageEnhance.Contrast(ImageEnhance.Brightness(ImageEnhance.Color(im).enhance(1.35)).enhance(1.12)).enhance(1.04)
    veil = Image.new("RGBA", (W, H))
    px = veil.load()
    for x in range(W):
        a = .72 if x < W * .4 else max(0, .72 - (x - W * .4) / (W * .45) * .6)
        for y in range(H):
            px[x, y] = (16, 38, 110, int(255 * min(.9, a + (y / H) * .25)))
    img = Image.alpha_composite(im.convert("RGBA"), veil).convert("RGB")
    d = ImageDraw.Draw(img)
    p = Image.open(ASSETS / PORTRAIT).convert("RGB")
    pw, ph = 300, 375
    s = max(pw / p.width, ph / p.height)
    p = p.resize((round(p.width * s), round(p.height * s)), Image.LANCZOS).crop((0, 0, pw, ph))
    x0, y0 = W - 72 - pw, H - 72 - ph
    d.rounded_rectangle((x0 - 6, y0 - 6, x0 + pw + 6, y0 + ph + 6), 12, fill="#F7F8F8")
    mask = Image.new("L", p.size, 0); ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw, ph), 8, fill=255)
    img.paste(p, (x0, y0), mask)
    mono = font("ibm-plex-mono-latin-500.woff2", 22)
    big = font("archivo-latin-wdth.woff2", 104, {"wght": 700, "wdth": 66})
    lead = font("archivo-latin-wdth.woff2", 30, {"wght": 300, "wdth": 100})
    d.text((72, 120), "PRODUCT & PLATFORM LEADER", font=mono, fill="#FFFFFF")
    d.text((68, 168), "Daniel", font=big, fill="#FFFFFF"); d.text((68, 268), "Rohbeck", font=big, fill="#FFFFFF")
    d.rectangle((72, 395, 172, 401), fill="#35C6AE")
    for i, line in enumerate(lines):
        d.text((72, 430 + i * 42), line, font=lead, fill="#FFFFFF")
    d.text((72, 540), SITE["domain"], font=mono, fill="#BDEFE6")
    img.save(out / "assets" / name, "JPEG", quality=86, optimize=True)
    if not icon:
        return

    ic = Image.new("RGB", (180, 180), "#10266E"); di = ImageDraw.Draw(ic)
    f = font("archivo-latin-wdth.woff2", 84, {"wght": 700, "wdth": 70})
    bb = di.textbbox((0, 0), "DR", font=f)
    di.text(((180 - (bb[2] - bb[0])) / 2 - bb[0], 40 - bb[1]), "DR", font=f, fill="#FFFFFF")
    di.rectangle((55, 132, 125, 140), fill="#35C6AE")
    ic.save(out / "assets" / "apple-touch-icon.png")


# ---------------------------------------------------------------- page assembly
def body_main(c):
    views = home(c) + "\n" + "\n".join(case_view(c, slug, case) for slug, case in CASES.items())
    if c.preview:
        for which, fn in (("imprint", imprint_body), ("privacy", privacy_body)):
            views += (f'\n<div class="view" id="{which}" data-view="legal">{bar(c, solid=True, home_href="")}'
                      f'{legal_article(c, fn(c))}</div>')
    return (f'<a class="skip" href="#work">{E(UI["skip"])}</a>\n<main>\n' + views + "\n</main>\n" + contact_footer(c))


def private_terms():
    p = Path(os.environ.get("SITE_PRIVATE_TERMS", Path.home() / ".danielrohbeck-private-terms.txt"))
    if not p.exists():
        print(f"WARNING: {p} not found, private term check skipped")
        return []
    return [t.strip() for t in p.read_text(encoding="utf-8").splitlines() if t.strip() and not t.startswith("#")]


PRIVATE = None


def public_checks(text, name):
    global PRIVATE
    if PRIVATE is None:
        PRIVATE = private_terms()
    text = re.sub(r"data:[a-z/0-9+.-]+;base64,[A-Za-z0-9+/=]+", "", text)
    for bad in PRIVATE + ["claude.ai", "unsplash.com/photo", "googleapis", "gstatic", "to confirm"]:
        if bad.lower() in text.lower():
            raise SystemExit(f"{name}: public check failed (term from {'private list' if bad in PRIVATE else 'generic list'})")
    if re.search(r"(€|EUR)\s?\d|\d\s?(€|EUR|Mio\b|million euro)", text, re.I):
        raise SystemExit(f"{name}: public check failed: euro amount")


def page_paths(code):
    m = LANGS[code].UI
    return {"home": m["home"], "imprint": m["legal"]["imprint"], "privacy": m["legal"]["privacy"]}


def write(out, path, text, name):
    public_checks(text, name)
    f = out / "index.html" if path == "/" else out / path.strip("/") / "index.html"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


def build_site(out, fontdata):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True); (out / "fonts").mkdir()
    for name, data in fontdata.items():
        (out / "fonts" / name).write_bytes(data)
    make_images(out)
    if (ASSETS / "cv").is_dir():
        shutil.copytree(ASSETS / "cv", out / "assets" / "cv")
    (out / "assets" / "site.css").write_text(font_css(False, fontdata) + CSS, encoding="utf-8")
    (out / "assets" / "site.js").write_text(JS, encoding="utf-8")
    hero_ws = IMAGES["hero"]["widths"]
    preload = f'<link rel="preload" as="image" imagesrcset="{", ".join(f"/assets/img/hero-{w}.jpg {w}w" for w in hero_ws)}" imagesizes="100vw">\n'
    robots_home = None if INDEXING else NOINDEX
    robots_sub = "noindex,follow" if INDEXING else NOINDEX

    for code in ("en", "de"):
        use_lang(code)
        mine, theirs = page_paths(code), page_paths(other_lang())
        alt_of = lambda key: {code: mine[key], other_lang(): theirs[key]}
        c = Ctx(preview=False, alt=theirs["home"])
        ld = {"@context": "https://schema.org", "@type": "Person", "name": "Daniel Rohbeck", "url": BASE + mine["home"],
              "jobTitle": SITE["job_title"], "image": BASE + "/assets/portrait.jpg", "sameAs": [SITE["linkedin"]],
              "address": {"@type": "PostalAddress", "addressRegion": "Stuttgart area", "addressCountry": "DE"}}
        extra = preload + f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>\n'
        page = (head(SITE["title"], SITE["description"], mine["home"], extra, robots=robots_home, alt_paths=alt_of("home"))
                + "<body>\n" + body_main(c).replace(f'href="{mine["home"]}#', 'href="#')
                + '\n<script src="/assets/site.js"></script>\n</body>\n</html>\n')
        write(out, mine["home"], page, f"{code} home")

        for which, fn in (("imprint", imprint_body), ("privacy", privacy_body)):
            cl = Ctx(preview=False, alt=theirs[which])
            title = UI[which]
            p = (head(f"{title} · Daniel Rohbeck", f"{title} · {SITE['domain']}", mine[which], robots=robots_sub,
                      alt_paths=alt_of(which))
                 + "<body>\n" + bar(cl, solid=True, home_href=mine["home"]) + "\n<main>\n" + legal_article(cl, fn(cl))
                 + "\n</main>\n" + contact_footer(cl) + "\n</body>\n</html>\n")
            write(out, mine[which], p, f"{code} {which}")
        make_og(out, fontdata, UI["og_lines"], "og-image.jpg" if code == "en" else f"og-image-{code}.jpg", icon=(code == "en"))

    use_lang("en")
    c = Ctx(preview=False, alt="/de/")
    nf = ('<article class="legal"><a class="back" href="/">← Back to start</a><p class="eyebrow">404</p>'
          '<h1>Page not found</h1><p>This page does not exist. <a class="in" href="/">Back to the start page</a>.</p>'
          '<p lang="de">Diese Seite gibt es nicht. <a class="in" href="/de/">Zur deutschen Startseite</a>.</p></article>')
    p404 = (head("Not found · Daniel Rohbeck", "Not found", "/404.html", robots="noindex" if INDEXING else NOINDEX)
            + "<body>\n" + bar(c, solid=True, home_href="/") + "\n<main>\n" + nf + "\n</main>\n"
            + contact_footer(c) + "\n</body>\n</html>\n")
    public_checks(p404, "404")
    (out / "404.html").write_text(p404, encoding="utf-8")

    (out / "favicon.svg").write_text(FAVICON, encoding="utf-8")
    if INDEXING:
        (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {BASE}/sitemap.xml\n")
        alts = (f'<xhtml:link rel="alternate" hreflang="en" href="{BASE}/"/>'
                f'<xhtml:link rel="alternate" hreflang="de" href="{BASE}/de/"/>')
        (out / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
            f"  <url><loc>{BASE}/</loc>{alts}</url>\n  <url><loc>{BASE}/de/</loc>{alts}</url>\n</urlset>\n")
    else:
        # noindex cannot be set inside a PDF and GitHub Pages sends no X-Robots-Tag, so the CV is blocked here
        (out / "robots.txt").write_text("User-agent: *\nAllow: /\nDisallow: /assets/cv/\n")
    (out / "CNAME").write_text(_EN.SITE["domain"] + "\n")
    (out / ".nojekyll").write_text("")
    print("site ->", out, "(indexing on)" if INDEXING else "(link-only: noindex)")


def build_preview(path, fontdata, code):
    use_lang(code)
    c = Ctx(preview=True, alt=PREVIEW_URL[other_lang()] or "#")
    imgs = preview_images()
    js_img = ("(function(){var I=" + json.dumps(imgs) + ";[].forEach.call(document.querySelectorAll('img[data-k]'),"
              "function(i){i.src=I[i.dataset.k]})})();\n")
    # Artifact fragment: the host wraps it in its own doctype/head/body skeleton.
    title = "Daniel Rohbeck" if code == "en" else "Daniel Rohbeck (DE)"
    page = f"""<title>{title}</title>
<style>{font_css(True, fontdata)}{CSS}</style>
<script>document.documentElement.classList.add('js');document.documentElement.lang='{code}'</script>
{body_main(c)}
<script>{js_img}{JS}</script>
"""
    public_checks(page.replace(PREVIEW_URL[other_lang()], "") if PREVIEW_URL[other_lang()] else page, f"preview {code}")
    Path(path).write_text(page, encoding="utf-8")
    print("preview ->", path, f"{len(page) / 1e6:.1f} MB")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "docs"
    fontdata = {name: read_asset(f"fonts/{name}") for name in FONTS}
    build_site(out, fontdata)
    for code, p in zip(("en", "de"), sys.argv[2:4]):
        build_preview(p, fontdata, code)
