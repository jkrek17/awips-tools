#!/usr/bin/env python3
"""Build the projects index page at the root of the public web site.

Run by .github/workflows/site_publish.yml after the site is assembled and the
other projects' folders are copied forward. Every top-level folder with an
index.html becomes an entry, titled by that page's <title> and described by
its <meta name="description">; an index.html one level further down (lsr/next/,
phillies/offseason/) is listed under its parent. A title that starts with
"[test: name]" is shown with a "test" tag. Nothing is hand-maintained: a
project shows up the next time the site publishes after its folder lands in
the public repository, and fixes its own entry by fixing its own <title> and
description.

The page uses the wxmap.pro house style (light and dark with a theme switch,
and its landing page's animated low as the hero) and the self-hosted IBM Plex
fonts published under cyclone/fonts/.

Usage:
    python3 tools/build_site_index.py SITE_DIR      # writes SITE_DIR/index.html
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

FONTS = 'cyclone/fonts/'
TEST_TAG = re.compile(r'^\[test(?::\s*([^\]]*))?\]\s*', re.I)


class PageMeta(HTMLParser):
    """The <title> text and the meta description of one page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ''
        self.description = ''
        self._in_title = False
        self._title_done = False  # only the first <title>; inline SVGs carry their own

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'title' and not self._title_done:
            self._in_title = True
        elif tag == 'meta' and not self.description:
            name = (a.get('name') or a.get('property') or '').lower()
            if name in ('description', 'og:description'):
                self.description = (a.get('content') or '').strip()

    def handle_endtag(self, tag):
        if tag == 'title' and self._in_title:
            self._in_title = False
            self._title_done = True

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def read_page(page: Path, folder: str) -> dict:
    meta = PageMeta()
    try:
        meta.feed(page.read_text(encoding='utf-8', errors='replace'))
    except Exception as e:  # a malformed page still gets listed by its folder name
        print(f'{page}: {e}', file=sys.stderr)
    title = ' '.join(meta.title.split()) or folder
    test = TEST_TAG.match(title)
    if test:
        title = title[test.end():] or folder
    return {
        'href': folder + '/',
        'title': title,
        'description': ' '.join(meta.description.split()),
        'test': ('test: ' + test.group(1).strip() if test.group(1) else 'test') if test else '',
    }


def collect(site: Path) -> list[dict]:
    projects = []
    for d in sorted(p for p in site.iterdir() if p.is_dir() and not p.name.startswith('.')):
        if not (d / 'index.html').is_file():
            continue
        entry = read_page(d / 'index.html', d.name)
        entry['children'] = [
            read_page(c / 'index.html', f'{d.name}/{c.name}')
            for c in sorted(p for p in d.iterdir() if p.is_dir() and not p.name.startswith('.'))
            if (c / 'index.html').is_file()
        ]
        projects.append(entry)
    return projects


def render_entry(e: dict, cls: str) -> str:
    e_ = {k: html.escape(v) for k, v in e.items() if isinstance(v, str)}
    tag = f' <span class="tag">{e_["test"]}</span>' if e['test'] else ''
    desc = f'\n      <p>{e_["description"]}</p>' if e['description'] else ''
    return (f'<li class="{cls}">\n'
            f'      <a href="{e_["href"]}"><span class="name">{e_["title"]}</span>{tag}'
            f'<span class="path">/{e_["href"]}</span></a>{desc}')


# The wxmap.pro house style (jkrek17/wxmap.pro assets/tokens.css, house.css,
# theme.css and home.css), inlined so the page stays one file. Plex Sans
# Condensed is not published here, so headings use Plex Sans.
FONT_FACES = ''.join(
    f'@font-face {{ font-family: "IBM Plex {fam}"; font-weight: {w}; font-display: swap; '
    f'src: url("{FONTS}IBMPlex{fam}-{name}-Latin1.woff2") format("woff2"); }}\n'
    for fam, w, name in [('Sans', 400, 'Regular'), ('Sans', 500, 'Medium'), ('Sans', 600, 'SemiBold'),
                         ('Mono', 400, 'Regular'), ('Mono', 500, 'Medium')])

DARK = """--bg: #08121d; --surface: #0e1b29; --surface-2: #142536; --border: #22364b; --border-strong: #35506b;
    --text: #e4ecf3; --text-2: #a7b7c7; --text-3: #7d90a4;
    --accent: #5cb8e0; --accent-strong: #84cbea; --on-accent: #06121c;
    --calm: #4f7e9c; --gale: #e8be3a; --storm: #f07a42; --hurricane: #e2508f;
    color-scheme: dark;"""

CSS = FONT_FACES + """
:root {
  --bg: #f4f6f8; --surface: #ffffff; --surface-2: #e9eef3; --border: #d3dbe4; --border-strong: #aebccb;
  --text: #0e2236; --text-2: #43566b; --text-3: #6b7c8f;
  --accent: #0a6c96; --accent-strong: #08577a; --on-accent: #ffffff;
  --calm: #8fb3c9; --gale: #c99a06; --storm: #d4561c; --hurricane: #b3155c;
  --sans: "IBM Plex Sans", -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace;
  --step--1: 0.8125rem; --step-2: 1.75rem; --step-3: clamp(2.25rem, 1.4rem + 3.6vw, 3.5rem);
  --radius: 10px; --radius-sm: 6px; --page: 1120px;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    """ + DARK + """
  }
}
:root[data-theme="dark"] {
    """ + DARK + """
}
*, *::before, *::after { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 400 1rem/1.6 var(--sans); -webkit-font-smoothing: antialiased; }
h1, h2 { font-weight: 600; line-height: 1.1; letter-spacing: -0.015em; text-wrap: balance; margin: 0; }
p { margin: 0; }
a { color: var(--accent); text-underline-offset: 3px; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 4px; }
.wrap { max-width: var(--page); margin: 0 auto; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
.eyebrow { font: 500 var(--step--1)/1.2 var(--mono); letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-3); }

.sitebar { border-bottom: 1px solid var(--border); background: var(--surface); }
.sitebar .wrap { display: flex; align-items: center; gap: 16px; padding-block: 12px; }
.brand { display: flex; align-items: center; gap: 10px; color: var(--text); text-decoration: none; font: 600 1.125rem/1 var(--sans); }
.brand svg { width: 26px; height: 26px; flex: none; }
.brand .tld { color: var(--text-3); font-weight: 400; }
.sitebar nav { margin-left: auto; display: flex; align-items: center; gap: 4px; }
.sitebar nav a { color: var(--text-2); text-decoration: none; padding: 6px 10px; border-radius: var(--radius-sm); font-size: 0.9375rem; }
.sitebar nav a:hover { color: var(--text); background: var(--surface-2); }
.theme { display: inline-flex; border: 1px solid var(--border); border-radius: 999px; padding: 2px; background: var(--bg); }
.theme button { border: 0; background: transparent; color: var(--text-3); cursor: pointer; width: 30px; height: 26px; border-radius: 999px; display: grid; place-items: center; }
.theme button svg { width: 15px; height: 15px; }
.theme button[aria-pressed="true"] { background: var(--surface); color: var(--text); box-shadow: 0 0 0 1px var(--border); }

.btn { display: inline-flex; align-items: center; gap: 8px; padding: 11px 18px; border-radius: var(--radius-sm); font: 600 0.9375rem/1 var(--sans); text-decoration: none; border: 1px solid transparent; }
.btn-primary { background: var(--accent); color: var(--on-accent); }
.btn-primary:hover { background: var(--accent-strong); color: var(--on-accent); }
.btn-quiet { color: var(--text); border-color: var(--border-strong); }
.btn-quiet:hover { background: var(--surface-2); color: var(--text); }
.scale { display: flex; flex-wrap: wrap; gap: 6px 14px; font: 500 var(--step--1)/1.2 var(--mono); color: var(--text-2); }
.scale span { display: inline-flex; align-items: center; gap: 6px; }
.scale i { width: 18px; height: 6px; border-radius: 3px; display: inline-block; }

.hero { background: var(--surface); border-bottom: 1px solid var(--border); }
.hero-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr); gap: 48px; align-items: center; padding-block: 64px 72px; }
.hero-copy { display: flex; flex-direction: column; gap: 20px; min-width: 0; }
.hero h1 { font-size: var(--step-3); max-width: 15ch; }
.lede { font-size: 1.125rem; color: var(--text-2); max-width: 46ch; }
.actions { display: flex; flex-wrap: wrap; gap: 10px; }
.hero-figure { margin: 0; display: flex; flex-direction: column; gap: 10px; min-width: 0; }
#hero-flow { width: 100%; aspect-ratio: 5 / 4; max-width: 100%; display: block; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); }
.hero-figure figcaption { font-size: var(--step--1); color: var(--text-3); }

.projects .wrap { padding-block: 64px 72px; display: flex; flex-direction: column; gap: 12px; }
.projects h2 { font-size: var(--step-2); }
.projects .count { color: var(--text-2); }
.grid { list-style: none; margin: 20px 0 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr)); gap: 16px; }
li.project { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px 20px; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
li.project:hover { border-color: var(--border-strong); }
li a { color: inherit; text-decoration: none; display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 8px; }
.name { color: var(--accent); font-weight: 600; font-size: 1.0625rem; }
a:hover .name, a:focus-visible .name { text-decoration: underline; text-underline-offset: 3px; }
.path { color: var(--text-3); font: 0.8125rem var(--mono); }
.tag { color: var(--gale); border: 1px solid currentColor; border-radius: 4px; padding: 0 5px; font: 500 0.6875rem/1.1rem var(--mono); text-transform: uppercase; letter-spacing: 0.04em; }
li p { color: var(--text-2); font-size: 0.9375rem; line-height: 1.5; }
li.project > ul { list-style: none; margin: 6px 0 0; padding: 10px 0 0; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 8px; }
li.sub .name { font-weight: 500; font-size: 0.9375rem; }
li.sub p { font-size: 0.875rem; color: var(--text-3); }

.sitefoot { border-top: 1px solid var(--border); color: var(--text-3); font-size: var(--step--1); }
.sitefoot .wrap { display: flex; flex-wrap: wrap; gap: 8px 24px; justify-content: space-between; padding-block: 28px 40px; }

@media (max-width: 860px) {
  .hero-grid { grid-template-columns: minmax(0, 1fr); gap: 32px; padding-block: 40px 48px; }
  .projects .wrap { padding-block: 48px; }
}
@media (max-width: 480px) { .sitebar nav > a { display: none; } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }
"""

# wxmap.pro assets/theme.js: system, light or dark, kept per browser.
THEME_JS = """
(function () {
  var KEY = 'wxmap-theme', root = document.documentElement;
  function read() { try { return localStorage.getItem(KEY) || 'system'; } catch (e) { return 'system'; } }
  function apply(mode) {
    if (mode === 'light' || mode === 'dark') root.setAttribute('data-theme', mode);
    else root.removeAttribute('data-theme');
    document.querySelectorAll('[data-theme-set]').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-theme-set') === mode));
    });
  }
  apply(read());
  document.addEventListener('DOMContentLoaded', function () {
    apply(read());
    document.querySelectorAll('[data-theme-set]').forEach(function (b) {
      b.addEventListener('click', function () {
        var mode = b.getAttribute('data-theme-set');
        try { localStorage.setItem(KEY, mode); } catch (e) { /* follow system only */ }
        apply(mode);
        document.dispatchEvent(new CustomEvent('wxmap-theme'));
      });
    });
  });
})();
"""

# wxmap.pro assets/hero.js: wind particles around an idealised mid-latitude low,
# coloured on the 34/48/64 kt scale. An illustration, not forecast data.
HERO_JS = """
(function () {
  var canvas = document.getElementById('hero-flow');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');
  var still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var W = 0, H = 0, dpr = 1, parts = [], colors = {}, cx = 0, cy = 0, R = 1, running = true;
  function token(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function readColors() {
    colors = { calm: token('--calm'), gale: token('--gale'), storm: token('--storm'), hurricane: token('--hurricane'), bg: token('--surface'), iso: token('--border-strong'), ink: token('--text-3') };
  }
  // Rankine-like vortex with westerly steering, a stronger south-west flank and
  // inflow toward the centre. Speeds in kt; screen y points down.
  function wind(x, y) {
    var dx = (x - cx) / R, dy = (y - cy) / R;
    var r = Math.sqrt(dx * dx + dy * dy) + 1e-6, vmax = 70, rm = 0.32;
    var vt = r < rm ? vmax * r / rm : vmax * Math.pow(rm / r, 0.62);
    vt *= 1 + 0.18 * Math.max(0, (-dx - dy) / r);
    var u = vt * dy / r - 0.22 * vt * dx / r + 14;
    var v = -vt * dx / r - 0.22 * vt * dy / r;
    return [u, v, Math.sqrt(u * u + v * v)];
  }
  function colorFor(s) { return s >= 64 ? colors.hurricane : s >= 48 ? colors.storm : s >= 34 ? colors.gale : colors.calm; }
  function spawn(p) { p.x = Math.random() * W; p.y = Math.random() * H; p.age = Math.random() * 80 | 0; return p; }
  function paintBase() { ctx.globalAlpha = 1; ctx.fillStyle = colors.bg; ctx.fillRect(0, 0, W, H); }
  function resize() {
    var box = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2); W = box.width; H = box.height;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cx = W * 0.56; cy = H * 0.5; R = Math.min(W, H) * 0.55;
    var n = Math.round(Math.min(1400, W * H / 260));
    parts = []; for (var i = 0; i < n; i++) parts.push(spawn({}));
    readColors(); paintBase();
  }
  function isobars() {
    ctx.save(); ctx.strokeStyle = colors.iso; ctx.lineWidth = 1; ctx.globalAlpha = 0.9;
    ctx.fillStyle = colors.ink; ctx.font = '500 11px "IBM Plex Mono", monospace';
    var labels = [972, 980, 988, 996, 1004];
    for (var k = 0; k < labels.length; k++) {
      var rr = R * (0.16 + k * 0.2);
      ctx.beginPath(); ctx.ellipse(cx - k * R * 0.03, cy + k * R * 0.015, rr * 1.18, rr * 0.92, -0.25, 0, Math.PI * 2); ctx.stroke();
      ctx.fillText(String(labels[k]), cx - k * R * 0.03 + rr * 1.1 + 4, cy + k * R * 0.015 - rr * 0.3);
    }
    ctx.font = '600 22px "IBM Plex Sans", sans-serif'; ctx.fillStyle = colors.hurricane; ctx.globalAlpha = 1;
    ctx.fillText('L', cx - 6, cy + 8);
    ctx.restore();
  }
  function step() {
    ctx.globalAlpha = 0.09; ctx.fillStyle = colors.bg; ctx.fillRect(0, 0, W, H);
    ctx.globalAlpha = 0.9; ctx.lineWidth = 1.3; ctx.lineCap = 'round';
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i], w = wind(p.x, p.y), nx = p.x + w[0] * 0.035, ny = p.y + w[1] * 0.035;
      ctx.strokeStyle = colorFor(w[2]);
      ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(nx, ny); ctx.stroke();
      p.x = nx; p.y = ny; p.age++;
      if (p.age > 90 || nx < -5 || ny < -5 || nx > W + 5 || ny > H + 5) spawn(p).age = 0;
    }
  }
  function settle() { for (var i = 0; i < 60; i++) step(); isobars(); }
  function frame() { step(); isobars(); if (!still && running) requestAnimationFrame(frame); }
  resize();
  if (still) settle(); else requestAnimationFrame(frame);
  window.addEventListener('resize', function () { resize(); if (still) settle(); });
  document.addEventListener('wxmap-theme', function () { readColors(); paintBase(); if (still) settle(); });
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () { readColors(); paintBase(); if (still) settle(); });
  document.addEventListener('visibilitychange', function () { running = !document.hidden; if (running && !still) requestAnimationFrame(frame); });
})();
"""

MARK = ('<svg viewBox="0 0 32 32" aria-hidden="true">'
        '<circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" stroke-width="1.6" opacity=".35"/>'
        '<circle cx="16" cy="16" r="9" fill="none" stroke="currentColor" stroke-width="1.6" opacity=".6"/>'
        '<circle cx="16" cy="16" r="4" fill="var(--accent)"/></svg>')
FAVICON = ('data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 32 32%22%3E'
           '%3Ccircle cx=%2216%22 cy=%2216%22 r=%2213%22 fill=%22none%22 stroke=%22%230a6c96%22 stroke-width=%222%22 opacity=%22.5%22/%3E'
           '%3Ccircle cx=%2216%22 cy=%2216%22 r=%225%22 fill=%22%230a6c96%22/%3E%3C/svg%3E')
THEME_SWITCH = """<div class="theme" role="group" aria-label="Colour theme">
        <button type="button" data-theme-set="system" aria-label="Use system theme" title="System"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="3" width="12" height="8" rx="1.5"/><path d="M6 14h4"/></svg></button>
        <button type="button" data-theme-set="light" aria-label="Use light theme" title="Light"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="3"/><path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1"/></svg></button>
        <button type="button" data-theme-set="dark" aria-label="Use dark theme" title="Dark"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M13 9.5A5.5 5.5 0 0 1 6.5 3a5.5 5.5 0 1 0 6.5 6.5z"/></svg></button>
      </div>"""


def render(projects: list[dict]) -> str:
    items = []
    for p in projects:
        li = render_entry(p, 'project')
        if p['children']:
            kids = '\n'.join('          ' + render_entry(c, 'sub') + '</li>' for c in p['children'])
            li += f'\n        <ul>\n{kids}\n        </ul>'
        items.append('        ' + li + '\n        </li>')
    body = '\n'.join(items) or '        <li class="project"><p>No projects published yet.</p></li>'
    n = len(projects)
    count = f'{n} project{"" if n == 1 else "s"}, each listed by its own page title and description.'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Projects</title>
<meta name="description" content="Every project published on this site.">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<script>
// The live map used to be the root page and keeps its view in the hash (and
// test data in ?data=), so old links with either go on to the map. #projects
// is this page's own anchor.
if ((location.hash.length > 1 && location.hash !== '#projects') || /[?&]data=/.test(location.search)) location.replace('cyclone/' + location.search + location.hash);
</script>
<link rel="icon" href="{FAVICON}">
<style>
{CSS}</style>
<script>{THEME_JS}</script>
</head>
<body>

<header class="sitebar">
  <div class="wrap">
    <a class="brand" href="./" aria-label="Projects home">{MARK}<span>jkrek17<span class="tld">/projects</span></span></a>
    <nav aria-label="Site">
      <a href="#projects">Projects</a>
      <a href="https://wxmap.pro/">wxmap.pro</a>
      {THEME_SWITCH}
    </nav>
  </div>
</header>

<main>
  <section class="hero">
    <div class="wrap hero-grid">
      <div class="hero-copy">
        <p class="eyebrow">Marine forecasting · tools and research</p>
        <h1>Forecast tools, live maps and the studies behind them.</h1>
        <p class="lede">Ocean wind and cyclone guidance, verification scores, and the research that tunes them, published here as they are built.</p>
        <div class="actions">
          <a class="btn btn-primary" href="#projects">Browse projects
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M8 3v10M4 9l4 4 4-4"/></svg></a>
          <a class="btn btn-quiet" href="https://wxmap.pro/">Open wxmap.pro</a>
        </div>
        <div class="scale" aria-label="Wind scale">
          <span><i style="background:var(--calm)"></i>&lt;34 kt</span>
          <span><i style="background:var(--gale)"></i>Gale 34–47</span>
          <span><i style="background:var(--storm)"></i>Storm 48–63</span>
          <span><i style="background:var(--hurricane)"></i>Hurricane force 64+</span>
        </div>
      </div>
      <figure class="hero-figure">
        <canvas id="hero-flow" aria-label="Animated wind particles circling a deep low, coloured by wind speed"></canvas>
        <figcaption>Illustration: an idealised 968&nbsp;mb North Atlantic low, coloured on the wind scale.</figcaption>
      </figure>
    </div>
  </section>

  <section class="projects" id="projects" aria-labelledby="projects-h">
    <div class="wrap">
      <p class="eyebrow">Published here</p>
      <h2 id="projects-h">Projects</h2>
      <p class="count">{count}</p>
      <ul class="grid">
{body}
      </ul>
    </div>
  </section>
</main>

<footer class="sitefoot">
  <div class="wrap">
    <p>Experimental guidance, not an official forecast. For warnings see the <a href="https://ocean.weather.gov/">Ocean Prediction Center</a>.</p>
    <p>jkrek17.github.io/web</p>
  </div>
</footer>

<script>{HERO_JS}</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('site', type=Path, help='the assembled site directory')
    args = ap.parse_args()
    projects = collect(args.site)
    (args.site / 'index.html').write_text(render(projects), encoding='utf-8')
    for p in projects:
        print(f"{p['href']:<16} {p['title']}" + ''.join(f"\n  {c['href']:<14} {c['title']}" for c in p['children']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
