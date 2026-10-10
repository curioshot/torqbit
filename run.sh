#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

# `python -m pip`, never `.venv/bin/pip`: the venv's console scripts carry a
# shebang pointing at the interpreter that created it. Move the project
# directory and every one of them breaks, while `-m pip` keeps working.
if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
  echo "The virtualenv is broken (moved with the project?). Recreating it..."
  rm -rf .venv
  python3 -m venv .venv
fi

.venv/bin/python -m pip install -q -r requirements.txt
exec .venv/bin/python main.py "$@"
