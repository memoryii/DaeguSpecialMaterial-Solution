#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10 이상이 필요합니다."'
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
printf '%s\n' '설치 완료. private 입력을 준비한 뒤 ./start.sh --local-only 또는 ./start.sh를 실행하세요.'
