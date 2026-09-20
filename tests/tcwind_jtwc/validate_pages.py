#!/usr/bin/env python3
"""Structural validation for an Apps Script HTML page.

Fails loudly rather than vacuously: a truncated file that yields zero script
blocks previously "passed" node --check on an empty string.
"""
import re, subprocess, sys, tempfile, os

def check(path):
    raw = open(path).read()
    # Strip HTML comments before counting tags: Theme.html's own header comment
    # explains where to include it and names <head>, which a naive count reads
    # as an unclosed tag.
    s = re.sub(r'<!--.*?-->', '', raw, flags=re.S)
    errs = []
    # Vortex.html and friends are fragments included into a page, not pages.
    fragment = not re.search(r'<html(?=[\s>])', s, re.I)
    if not fragment and not s.rstrip().endswith('</html>'):
        errs.append("file does not end with </html> - truncated?")
    if fragment and not re.search(r'</(script|style)\s*>\s*$', s):
        errs.append("fragment does not end with </script> or </style> - truncated?")
    for t in ('html', 'head', 'body', 'script', 'style'):
        o = len(re.findall(r'<%s(?=[\s>])' % t, s, re.I))
        c = len(re.findall(r'</%s\s*>' % t, s, re.I))
        if t == 'body':
            o = len(re.findall(r'^<body(?=[\s>])', s, re.I | re.M))
        if o != c:
            errs.append("<%s> unbalanced: %d open, %d close" % (t, o, c))
    blocks = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', s, re.S)
    style_only = fragment and not re.search(r'<script(?=[\s>])', s)
    if style_only:
        pass                      # a stylesheet fragment has no JS to check
    elif not blocks:
        errs.append("NO inline script blocks extracted - cannot validate JS")
    else:
        js = re.sub(r'<\?[!=]?=?.*?\?>', '0', "\n;\n".join(blocks), flags=re.S)
        if not js.strip():
            errs.append("script blocks are empty after scriptlet stripping")
        else:
            f = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False)
            f.write(js); f.close()
            r = subprocess.run(['node', '--check', f.name],
                               capture_output=True, text=True)
            os.unlink(f.name)
            if r.returncode:
                errs.append("JS syntax: " + r.stderr.strip().splitlines()[0])
    name = os.path.basename(path)
    if errs:
        print("FAIL %-16s %d bytes" % (name, len(raw)))
        for e in errs:
            print("       - " + e)
        return False
    kind = "style fragment" if style_only else "%d script block(s)" % len(blocks)
    print("ok   %-16s %d bytes, %s" % (name, len(raw), kind))
    return True

sys.exit(0 if all([check(p) for p in sys.argv[1:]]) else 1)
