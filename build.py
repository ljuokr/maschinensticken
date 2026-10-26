#!/usr/bin/env python3
"""Baut aus content.json, style.css, assets/ und fonts/ eine einzelne HTML-Datei.

Gleiches Geruest wie die Keramikdruck-Seite. Bilder werden als WebP eingebettet,
die Schrift auf die tatsaechlich benutzten Zeichen reduziert. Ergebnis laeuft per
Doppelklick, ohne Server und ohne Netz (nur Videos laden auf Klick von extern).

    python3 build.py
"""

import base64
import html
import io
import json
import re
from pathlib import Path

from PIL import Image
from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

ROOT = Path(__file__).parent
OUT = ROOT / "maschinensticken.html"

CONTENT = ROOT / "content.json"
STYLE = ROOT / "style.css"
ASSETS = ROOT / "assets"
FONTS = ROOT / "fonts"

WEBP_QUALITY = 86


# --------------------------------------------------------------------------- Bilder


def embed_image(src: str) -> str:
    """'/assets/x.png' -> data-URI mit WebP. Lossless nur, wenn es kleiner ausfaellt."""
    path = ASSETS / Path(src).name
    img = Image.open(path)
    if getattr(img, "is_animated", False) and path.suffix == ".webp":
        # Animierte WebP unverändert einbetten, sonst ginge beim Umrechnen die Animation verloren.
        return "data:image/webp;base64," + base64.b64encode(path.read_bytes()).decode()
    variants = []
    for lossless in (False, True):
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=WEBP_QUALITY, lossless=lossless, method=6)
        variants.append(buf.getvalue())
    data = min(variants, key=len)
    return "data:image/webp;base64," + base64.b64encode(data).decode()


# --------------------------------------------------------------------------- Schrift


def embed_font(path: Path, text: str) -> str:
    """Lato auf die vorkommenden Zeichen reduzieren und als WOFF2 einbetten."""
    font = TTFont(path)
    options = Options()
    options.flavor = "woff2"
    options.layout_features = ["kern", "liga"]
    options.desubroutinize = True
    options.drop_tables += ["GSUB", "GPOS"]
    subsetter = Subsetter(options=options)
    subsetter.populate(text=text)
    subsetter.subset(font)
    buf = io.BytesIO()
    font.save(buf)
    return "data:font/woff2;base64," + base64.b64encode(buf.getvalue()).decode()


# --------------------------------------------------------------------------- Links


def rewrite_links(markup: str) -> str:
    """Seitenlinks der alten Routen auf die Hash-Navigation der Einzeldatei umbiegen."""
    return re.sub(r'href="/([a-z0-9-]+)(?:#([^"]+))?"', lambda m: f'href="#{m[1]}{"/" + m[2] if m[2] else ""}"', markup)


def mark_todos(markup: str) -> str:
    """Offene Punkte sichtbar hervorheben, bis sie am Geraet geklaert sind."""
    return re.sub(r"\[VOR ORT PRUEFEN:\s*([^\]]+)\]", r'<mark class="todo">Vor Ort prüfen: \1</mark>', markup)


def label_cells(table: str) -> str:
    """Spaltentitel als data-label an jede Zelle, damit die Tabelle auf dem Handy gestapelt lesbar bleibt."""
    heads = [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<th[^>]*scope=\"col\"[^>]*>(.*?)</th>", table, flags=re.S)]
    if not heads:
        return table

    def row(m: re.Match) -> str:
        labels = iter(heads)

        def cell(c: re.Match) -> str:
            label = next(labels, "")
            return f'<td data-label="{html.escape(label)}"' if c[1] == "td" else c[0]

        return re.sub(r"<(td|th)\b", cell, m[0])

    return re.sub(r"<tbody>.*?</tbody>", lambda b: re.sub(r"<tr>.*?</tr>", row, b[0], flags=re.S), table, flags=re.S)


def wrap_tables(markup: str) -> str:
    """Breite Tabellen scrollen auf dem Tablet im eigenen Rahmen, auf dem Handy werden sie gestapelt."""
    return re.sub(
        r"<table\b.*?</table>",
        lambda m: '<div class="table-scroll" tabindex="0" role="region" '
        f'aria-label="Tabelle, bei Bedarf seitlich verschiebbar">{label_cells(m[0])}</div>',
        markup,
        flags=re.S,
    )


# --------------------------------------------------------------------------- Bausteine


ICONS = {
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "chevron": '<path d="m6 9 6 6 6-6"/>',
    "play": '<path d="M6 3v18l15-9Z"/>',
    "download": '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
}


def icon(name: str, size: int = 22, cls: str = "") -> str:
    return (
        f'<svg class="{cls}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true">{ICONS[name]}</svg>'
    )


def embed_inline_images(markup: str) -> str:
    """Bilder in HTML-Bloecken (src="/assets/x.png") genauso einbetten wie Bildbloecke."""
    return re.sub(r'src="/assets/([^"]+)"', lambda m: f'src="{embed_image(m[1])}"', markup)


def render_block(block: dict) -> str:
    kind = block["type"]
    if kind == "html":
        return f'<div class="prose-content">{wrap_tables(mark_todos(rewrite_links(embed_inline_images(block["html"]))))}</div>'
    if kind == "image":
        img = (
            f'<img src="{embed_image(block["src"])}" alt="{html.escape(block.get("alt") or "")}" '
            f'width="{block["width"]}" height="{block["height"]}" loading="lazy">'
        )
        if block.get("href"):
            img = f'<a href="{html.escape(block["href"])}">{img}</a>'
        return f"<figure>{img}</figure>"
    if kind == "video":
        # Anbieter steht im Button, weil erst der Klick eine Verbindung dorthin aufbaut.
        # Vorschaubild eingebettet, damit vor dem Klick nichts vom Anbieter geladen wird.
        poster = f' mit-bild" style="--poster:url({embed_image(block["poster"])})' if block.get("poster") else ""
        return f"""<div class="video-block"><button type="button" class="video-load{poster}" data-src="{html.escape(block["src"])}" data-title="{html.escape(block.get("title") or "")}">
{icon("play", 30)}<span>{html.escape(block.get("label") or "Video abspielen")}</span><small>Video von {html.escape(block["provider"])} laden</small></button></div>"""
    if kind == "schritte":
        # Bebilderte Kurzanleitung. Ohne Skript und im Druck stehen alle Schritte untereinander,
        # mit Skript einer aufs Mal, weitergeschaltet von Hand oder mit «Abspielen».
        total = len(block["schritte"])
        items = []
        for nr, step in enumerate(block["schritte"], 1):
            width, height = Image.open(ASSETS / Path(step["bild"]).name).size
            items.append(
                f'<li class="schritt-karte"><figure><img src="{embed_image(step["bild"])}" '
                f'alt="{html.escape(step["alt"])}" width="{width}" height="{height}" loading="lazy"></figure>'
                f'<div class="schritt-text"><p class="schritt-nr">Schritt {nr} von {total}: '
                f'<strong>{html.escape(step["titel"])}</strong></p><p>{step["html"]}</p></div></li>'
            )
        return (
            f'<div class="schritte"><ol class="schritte-liste" aria-live="polite">{"".join(items)}</ol>'
            '<div class="schritte-steuerung" hidden>'
            '<button type="button" class="schritt-zurueck">Zurück</button>'
            '<button type="button" class="schritt-weiter">Weiter</button>'
            '<span class="schritte-punkte" aria-hidden="true"></span>'
            '<button type="button" class="schritt-abspielen">Abspielen</button></div>'
            f'<p class="bildquelle">{block["quelle"]}</p></div>'
        )
    return ""


def render_section(section: dict, slug: str) -> str:
    cells = "".join(
        f'<div class="content-cell">{"".join(render_block(b) for b in cell["blocks"])}</div>'
        for cell in section["cells"]
    )
    anchor = section.get("anchor") or section["id"]
    # Suchtreffer springen die Section an, darum haengen die Metadaten hier dran.
    meta = f'data-title="{html.escape(section.get("title") or "")}" data-anchor="{anchor}"'

    if section.get("accordion"):
        return f"""<details class="lesson" id="{anchor}" {meta}>
<summary class="lesson-title"><span class="lesson-heading"><span>{html.escape(section["title"])}</span></span>{icon("chevron", 20, "lesson-icon")}</summary>
<div class="lesson-content">{cells}</div></details>"""

    classes = "content-section"
    if section.get("gallery"):
        classes += " image-gallery"
    if section.get("layout"):
        classes += " " + section["layout"]
    style = f' style="--columns:{len(section["cells"])}"' if section.get("gallery") else ""
    return f'<section class="{classes}" id="{section["id"]}"{style} {meta}>{cells}</section>'


def render_page(page: dict, first: bool) -> str:
    sections = "".join(render_section(s, page["slug"]) for s in page["sections"])
    return (
        f'<article class="page article page-{page["slug"]}" id="page-{page["slug"]}" '
        f'data-slug="{page["slug"]}" data-label="{html.escape(page["label"])}" '
        f'data-page-title="{html.escape(page["title"])}"{"" if first else " hidden"}>{sections}</article>'
    )


# --------------------------------------------------------------------------- Seitengerüst


SCRIPT = """
const pages = [...document.querySelectorAll('.page')];
const navLinks = [...document.querySelectorAll('.site-navigation a')];
const body = document.body;

function show(slug, anchor) {
  const page = pages.find(p => p.dataset.slug === slug) || pages[0];
  const changed = page.hidden;
  pages.forEach(p => { p.hidden = p !== page; });
  navLinks.forEach(a => a.setAttribute('aria-current', a.hash.slice(1).split('/')[0] === page.dataset.slug ? 'page' : 'false'));
  document.title = page.dataset.pageTitle;
  document.querySelector('.bar-title').textContent = page.dataset.label;
  body.classList.remove('nav-open');
  // Seitenwechsel springt direkt, sonst laufen zwei Smooth-Scrolls gegeneinander.
  if (!anchor) { window.scrollTo({ top: 0, behavior: 'instant' }); return; }
  const target = page.querySelector('#' + CSS.escape(anchor));
  if (!target) return;
  const lesson = target.closest('details');
  if (lesson) lesson.open = true;
  requestAnimationFrame(() => target.scrollIntoView({ block: 'start', behavior: changed ? 'instant' : 'smooth' }));
}

function route() {
  const [slug, anchor] = decodeURIComponent(location.hash.slice(1)).split('/');
  show(slug, anchor);
}
addEventListener('hashchange', route);
route();

// Navigation mobil
document.querySelector('.mobile-menu').onclick = () => body.classList.toggle('nav-open');

// Suche ueber die Abschnitte, die ohnehin schon im Dokument stehen
const search = document.querySelector('.site-search');
const field = document.getElementById('search-input');
const count = document.querySelector('.search-count');
const list = document.querySelector('.site-search ul');
const sections = pages.flatMap(p => [...p.querySelectorAll('[data-anchor]')].map(s => ({
  node: s, page: p, text: (s.dataset.title + ' ' + s.textContent).toLocaleLowerCase('de')
})));

document.querySelector('.search-toggle').onclick = function () {
  const open = search.hidden;
  search.hidden = !open;
  this.setAttribute('aria-expanded', open);
  this.setAttribute('aria-label', open ? 'Suche schliessen' : 'Website durchsuchen');
  this.innerHTML = open ? ICON_X : ICON_SEARCH;
  if (open) field.focus();
};
field.oninput = () => {
  const term = field.value.toLocaleLowerCase('de').trim();
  count.hidden = list.hidden = !term;
  list.textContent = '';
  if (!term) return;
  const hits = sections.filter(s => s.text.includes(term));
  count.textContent = hits.length + ' Treffer';
  for (const hit of hits) {
    const li = document.createElement('li');
    const a = document.createElement('a');
    a.href = '#' + hit.page.dataset.slug + '/' + hit.node.dataset.anchor;
    a.innerHTML = '<strong></strong><span></span>';
    a.firstChild.textContent = hit.node.dataset.title || hit.page.dataset.pageTitle;
    a.lastChild.textContent = hit.page.dataset.label;
    a.onclick = () => { search.hidden = true; field.value = ''; };
    li.append(a);
    list.append(li);
  }
};
field.onkeydown = e => { if (e.key === 'Escape') document.querySelector('.search-toggle').click(); };

// Video erst auf Klick laden
document.addEventListener('click', e => {
  const button = e.target.closest('.video-load');
  if (!button) return;
  const frame = document.createElement('iframe');
  frame.src = button.dataset.src;
  frame.title = button.dataset.title;
  frame.allow = 'fullscreen';
  frame.allowFullscreen = true;
  button.replaceWith(frame);
});

// Bebilderte Kurzanleitungen: ein Schritt aufs Mal, von Hand oder abgespielt
document.querySelectorAll('.schritte').forEach(box => {
  const items = [...box.querySelectorAll('.schritt-karte')];
  const bar = box.querySelector('.schritte-steuerung');
  const back = bar.querySelector('.schritt-zurueck');
  const next = bar.querySelector('.schritt-weiter');
  const play = bar.querySelector('.schritt-abspielen');
  const dots = bar.querySelector('.schritte-punkte');
  dots.innerHTML = items.map(() => '<i></i>').join('');
  let cur = 0, timer = null;
  const go = i => {
    cur = (i + items.length) % items.length;
    items.forEach((li, k) => { li.hidden = k !== cur; });
    [...dots.children].forEach((d, k) => d.classList.toggle('aktiv', k === cur));
    back.setAttribute('aria-disabled', cur === 0);
    next.textContent = cur === items.length - 1 ? 'Von vorn' : 'Weiter';
  };
  const stop = () => { clearInterval(timer); timer = null; play.textContent = 'Abspielen'; };
  back.onclick = () => { stop(); if (cur > 0) go(cur - 1); };
  next.onclick = () => { stop(); go(cur + 1); };
  play.onclick = () => {
    if (timer) return stop();
    play.textContent = 'Anhalten';
    if (cur === items.length - 1) go(0);
    timer = setInterval(() => (cur === items.length - 1 ? stop() : go(cur + 1)), 3500);
  };
  box.addEventListener('keydown', e => {
    if (e.key === 'ArrowRight') next.click();
    if (e.key === 'ArrowLeft') back.click();
  });
  bar.hidden = false;
  go(0);
});

// Beim Drucken alles aufklappen
addEventListener('beforeprint', () => document.querySelectorAll('details').forEach(d => d.open = true));
"""


def build() -> None:
    pages = json.loads(CONTENT.read_text())
    body = "".join(render_page(p, i == 0) for i, p in enumerate(pages))

    nav = "".join(
        f'<a href="#{p["slug"]}"{" class=sub" if p.get("sub") else ""}>{html.escape(p["label"])}</a>'
        for p in pages
    )

    script = SCRIPT.replace("ICON_SEARCH", repr(icon("search"))).replace("ICON_X", repr(icon("x")))

    page = f"""<!DOCTYPE html>
<html lang="de-CH">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(pages[0]["title"])}</title>
<link rel="icon" href="data:image/svg+xml;base64,{base64.b64encode((ROOT / "favicon.svg").read_bytes()).decode()}">
<style>__STYLE__</style>
</head>
<body>
<a href="#main" class="skip-link">Zum Inhalt springen</a>
<nav class="site-sidebar" aria-label="Hauptnavigation">
<div class="brand"><a href="#maschinensticken">MASCHINENSTICKEN</a></div>
<div class="site-navigation">{nav}</div>
<div class="download"><a class="download-link" href="maschinensticken.html" download="maschinensticken.html">{icon("download", 17)}<span>Anleitung als HTML herunterladen</span></a></div>
</nav>
<div class="site-main">
<header class="utility-bar">
<button class="mobile-menu icon-button" aria-label="Navigation &ouml;ffnen">{icon("menu", 23)}</button>
<span class="bar-title" aria-hidden="true"></span>
<button class="icon-button search-toggle" aria-label="Website durchsuchen" aria-expanded="false">{icon("search")}</button>
</header>
<section class="site-search" aria-label="Website durchsuchen" hidden>
<label for="search-input">Website durchsuchen</label>
<input id="search-input" type="search" placeholder="Suchbegriff eingeben &hellip;">
<output class="search-count" hidden></output>
<ul hidden></ul>
</section>
<main id="main">{body}</main>
</div>
<script>{script}</script>
</body>
</html>"""

    # Schrift erst jetzt, wenn feststeht, welche Zeichen wirklich vorkommen.
    text = re.sub(r"<[^>]+>", " ", page) + "".join(chr(c) for c in range(32, 127))
    style = STYLE.read_text().replace(
        "/* Maschinensticken",
        "@font-face{font-family:Lato;font-weight:400;font-style:normal;font-display:swap;"
        f'src:url("{embed_font(FONTS / "Lato-Regular.ttf", text)}") format("woff2")}}\n'
        "@font-face{font-family:Lato;font-weight:700 900;font-style:normal;font-display:swap;"
        f'src:url("{embed_font(FONTS / "Lato-Bold.ttf", text)}") format("woff2")}}\n'
        "/* Maschinensticken",
        1,
    )
    page = page.replace("__STYLE__", style)

    OUT.write_text(page)
    print(f"{OUT.name}: {len(page.encode()) / 1024 / 1024:.2f} MB, {len(pages)} Seiten")


if __name__ == "__main__":
    build()
