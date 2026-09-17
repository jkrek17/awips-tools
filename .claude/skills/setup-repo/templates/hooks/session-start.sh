#!/bin/bash
# SessionStart hook: install what the pre-push checks in CLAUDE.md need, so
# they run in a fresh Claude Code on the web container. Web-only, synchronous,
# idempotent. Runs once per container; the result is cached.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Python packages the tests import. Pin only if the repo does.
{{PIP_INSTALL_LINE}}   # e.g. python3 -m pip install --quiet numpy

# Node tools the checks shell out to. Pin to what CI pins.
{{NPM_INSTALL_LINE}}   # e.g. npm install -g --silent html-validate@11.15.0

# Anything the checks need in the environment for the whole session.
# echo 'export PYTHONPATH="."' >> "$CLAUDE_ENV_FILE"

echo "session-start: dependencies ready"
