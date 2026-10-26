#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
  printf '%s\n' '먼저 bash setup.sh를 실행하세요.' >&2
  exit 1
fi
exec .venv/bin/python serve.py "$@"
