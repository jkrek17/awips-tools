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

The page uses the live map's dark theme and its self-hosted IBM Plex fonts,
which are published under cyclone/fonts/.

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


def render(projects: list[dict]) -> str:
    items = []
    for p in projects:
        li = render_entry(p, 'project')
        if p['children']:
            kids = '\n'.join('        ' + render_entry(c, 'sub') + '</li>' for c in p['children'])
            li += f'\n      <ul>\n{kids}\n      </ul>'
        items.append('    ' + li + '\n    </li>')
    body = '\n'.join(items) or '    <li class="project"><p>No projects published yet.</p></li>'
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Projects</title>
<meta name="description" content="Every project published on this site.">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<script>
// The live map used to be the root page and keeps its view in the hash (and
// test data in ?data=), so old links with either go on to the map.
if (location.hash.length > 1 || /[?&]data=/.test(location.search)) location.replace('cyclone/' + location.search + location.hash);
</script>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 16 16%22%3E%3Crect x=%222%22 y=%222%22 width=%2212%22 height=%2212%22 rx=%222%22 fill=%22none%22 stroke=%22%237fb0ee%22 stroke-width=%221.2%22/%3E%3Cpath d=%22M5 6h6M5 8h6M5 10h4%22 stroke=%22%237fb0ee%22/%3E%3C/svg%3E">
<style>
@font-face {{ font-family: "IBM Plex Sans"; font-weight: 400; font-display: swap; src: url("{FONTS}IBMPlexSans-Regular-Latin1.woff2") format("woff2"); }}
@font-face {{ font-family: "IBM Plex Sans"; font-weight: 600; font-display: swap; src: url("{FONTS}IBMPlexSans-SemiBold-Latin1.woff2") format("woff2"); }}
@font-face {{ font-family: "IBM Plex Mono"; font-weight: 400; font-display: swap; src: url("{FONTS}IBMPlexMono-Regular-Latin1.woff2") format("woff2"); }}
:root {{
  --bg: #17181b; --raise: #222328; --rule: #34353b; --rule-strong: #4a4b52;
  --text: #e9e8e3; --muted: #a8a6a0; --faint: #94928c; --accent: #7fb0ee; --warn: #e8c46a;
  --sans: "IBM Plex Sans", -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace;
  color-scheme: dark;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--text); font: 15px/1.5 var(--sans); }}
main {{ max-width: 720px; margin: 0 auto; padding: 48px 16px 64px; }}
h1 {{ font-size: 18px; font-weight: 600; margin: 0 0 4px; }}
.lede {{ color: var(--muted); margin: 0 0 24px; }}
ul {{ list-style: none; margin: 0; padding: 0; }}
li.project {{ border-top: 1px solid var(--rule); padding: 12px 0; }}
li.project:last-child {{ border-bottom: 1px solid var(--rule); }}
li.project > ul {{ margin: 8px 0 0 12px; padding-left: 12px; border-left: 1px solid var(--rule-strong); }}
li.sub {{ padding: 4px 0; }}
a {{ color: inherit; text-decoration: none; display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 8px; }}
.name {{ color: var(--accent); font-weight: 600; }}
li.sub .name {{ font-weight: 400; }}
a:hover .name, a:focus-visible .name {{ text-decoration: underline; }}
a:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }}
.path {{ color: var(--faint); font: 13px var(--mono); }}
.tag {{ color: var(--warn); border: 1px solid currentColor; border-radius: 4px; padding: 0 4px; font: 11px/16px var(--mono); }}
li p {{ color: var(--muted); margin: 4px 0 0; font-size: 13px; }}
</style>
</head>
<body>
<main>
  <h1>Projects</h1>
  <p class="lede">Everything published on this site.</p>
  <ul>
{body}
  </ul>
</main>
</body>
</html>
'''


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
