#!/usr/bin/env python3
"""Structural validation for an Apps Script HTML page.

Fails loudly rather than vacuously: a truncated file that yields zero script
blocks previously "passed" node --check on an empty string.
"""
import re, subprocess, sys, tempfile, os

def check(path):
    s = open(path).read()
    errs = []
    # Vortex.html and friends are fragments included into a page, not pages.
    fragment = not re.search(r'<html(?=[\s>])', s, re.I)
    if not fragment and not s.rstrip().endswith('</html>'):
        errs.append("file does not end with </html> - truncated?")
    if fragment and not s.rstrip().endswith('</script>'):
        errs.append("fragment does not end with </script> - truncated?")
    for t in ('html', 'head', 'body', 'script', 'style'):
        o = len(re.findall(r'<%s(?=[\s>])' % t, s, re.I))
        c = len(re.findall(r'</%s\s*>' % t, s, re.I))
        if t == 'body':
            o = len(re.findall(r'^<body(?=[\s>])', s, re.I | re.M))
        if o != c:
            errs.append("<%s> unbalanced: %d open, %d close" % (t, o, c))
    blocks = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', s, re.S)
    if not blocks:
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
        print("FAIL %-16s %d bytes" % (name, len(s)))
        for e in errs:
            print("       - " + e)
        return False
    print("ok   %-16s %d bytes, %d script block(s)" % (name, len(s), len(blocks)))
    return True

sys.exit(0 if all([check(p) for p in sys.argv[1:]]) else 1)
