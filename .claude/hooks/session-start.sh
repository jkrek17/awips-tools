#!/bin/bash
# SessionStart hook: install what the pre-push checks in CLAUDE.md need, so
# they run in a fresh Claude Code on the web container. Web-only, synchronous,
# idempotent.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

# test_parser_golden.py, compare_py_js.py, verify_*.py and the GFE procedure
# all import numpy. Unpinned, matching README's `pip install numpy`.
python3 -m pip install --quiet numpy

# Pages CI runs html-validate over docs/ at exactly this version; see
# .github/workflows/pages.yml for why it is pinned.
if ! command -v html-validate >/dev/null 2>&1 \
   || ! html-validate --version 2>/dev/null | grep -q "11\.15\.0$"; then
  npm install -g --silent html-validate@11.15.0
fi

echo "session-start: numpy $(python3 -c 'import numpy; print(numpy.__version__)'), html-validate $(html-validate --version)"
