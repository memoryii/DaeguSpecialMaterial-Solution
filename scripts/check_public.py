#!/usr/bin/env python3
"""Check the explicit public source file list, including Notebook outputs."""
from pathlib import Path
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    '.gitignore', 'README.md', 'requirements.txt', 'requirements-tested.txt',
    'Daegu_MES_quality_analysis.ipynb', 'serve.py', 'setup.sh', 'start.sh',
    'scripts/check_public.py', 'docs/user-guide.md', 'docs/server-setup.md',
    'docs/data-guide.md',
}

def check():
    errors = []
    for name in sorted(ALLOWED):
        p = ROOT / name
        if not p.is_file():
            errors.append(f'누락: {name}')
            continue
        text = p.read_text(encoding='utf-8')
        if re.search(r'\b(?:PD|PR|TM)\d{8,}\b', text):
            errors.append(f'실제 식별번호 패턴: {name}')
        if re.search(r'\b(?:ghp_|github_pat_)[A-Za-z0-9_]{15,}', text):
            errors.append(f'GitHub 자격증명 패턴: {name}')
        if name.endswith('.ipynb'):
            notebook = json.loads(text)
            for i, cell in enumerate(notebook['cells'], 1):
                if cell.get('outputs') or cell.get('execution_count') is not None:
                    errors.append(f'실행 출력 또는 실행횟수가 남음: 셀 {i}')
                if cell.get('attachments'):
                    errors.append(f'첨부 이미지가 남음: 셀 {i}')
    if (ROOT / '.git').is_dir():
        tracked = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, check=True, capture_output=True).stdout.decode().split('\0')
        for name in filter(None, tracked):
            if name not in ALLOWED:
                errors.append(f'공개 허용 목록 외 Git 파일: {name}')
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f'공개 대상 {len(ALLOWED)}개 파일 확인: Notebook 실행 출력 없음. 실제 원본·토큰은 수동으로도 확인하세요.')
    return 0

if __name__ == '__main__':
    raise SystemExit(check())
