#!/usr/bin/env python3
"""Update a ZIP deployment from a pinned public commit and restart its server.

Company inputs, outputs, Python environment, and working notebooks are preserved.
Authentication stays enabled. Run this on the existing Linux deployment host.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import getpass
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener, urlopen
import zipfile

REPOSITORY = "memoryii/DaeguSpecialMaterial-Solution"
NOTEBOOK = "Daegu_MES_quality_analysis.ipynb"
PUBLIC_FILES = {
    ".gitignore", "README.md", "requirements.txt", "requirements-tested.txt",
    NOTEBOOK, "serve.py", "setup.sh", "start.sh", "scripts/check_public.py",
    "docs/user-guide.md", "docs/server-setup.md", "docs/data-guide.md",
    "src/__init__.py", "src/mes_analysis.py", "scripts/update_deployment.py",
}
EXECUTABLE = {"serve.py", "setup.sh", "start.sh", "scripts/check_public.py", "scripts/update_deployment.py"}
MAX_ARCHIVE_BYTES = 10 * 1024 * 1024


class UpdateError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Never send the local Jupyter credential through a proxy or HTTP redirect.
LOCAL_HTTP = build_opener(ProxyHandler({}), NoRedirect())


def arguments(argv=None):
    parser = argparse.ArgumentParser(description="기존 MES 배포본을 지정한 GitHub 커밋으로 업데이트합니다.")
    parser.add_argument("--revision", required=True, help="검증된 GitHub 커밋 SHA (40자리)")
    parser.add_argument("--repository-dir", type=Path, default=Path.cwd())
    parser.add_argument("--private-dir", type=Path, default=Path.home() / "daegu_mes_private")
    parser.add_argument("--local-only", action="store_true", help="ngrok 없이 localhost에서만 재시작")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-fA-F]{40}", args.revision):
        parser.error("--revision에는 40자리 커밋 SHA를 입력하세요.")
    args.revision = args.revision.lower()
    args.repository_dir = args.repository_dir.expanduser().resolve()
    args.private_dir = args.private_dir.expanduser().resolve()
    if args.repository_dir.is_relative_to(args.private_dir) or args.private_dir.is_relative_to(args.repository_dir):
        parser.error("코드와 비공개 자료 폴더는 서로 포함되지 않아야 합니다.")
    return args


def private_dir(path):
    if path.is_symlink():
        raise UpdateError(f"실행 상태 폴더는 심볼릭 링크를 사용할 수 없습니다: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


@contextmanager
def lock_file(path, blocking=False):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "a+b") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError as exc:
            raise UpdateError("다른 업데이트 또는 서버 작업이 진행 중입니다.") from exc
        yield


def launcher_running(state):
    try:
        with lock_file(state / "serve.lock"):
            return False
    except UpdateError:
        return True


def check_destination(repo):
    for name in PUBLIC_FILES:
        path = repo / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise UpdateError(f"공개 코드 위치에 충돌하는 파일이 있습니다: {name}")
        parent = path.parent
        while parent != repo:
            if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                raise UpdateError(f"공개 코드 폴더 경로를 확인하세요: {parent}")
            parent = parent.parent
    if not os.access(repo, os.W_OK):
        raise UpdateError("코드 폴더에 쓰기 권한이 없습니다.")


def validate_installation(args):
    repo = args.repository_dir
    if not (repo / "serve.py").is_file() or not (repo / NOTEBOOK).is_file():
        raise UpdateError("기존 repository 폴더로 이동한 뒤 실행하세요.")
    check_destination(repo)
    python = repo / ".venv/bin/python"
    if not python.is_file():
        raise UpdateError("기존 .venv/bin/python이 없습니다. 설치된 배포 폴더를 지정하세요.")
    probe = subprocess.run(
        [str(python), "-c", "import sys; assert sys.version_info >= (3,10); import pandas,openpyxl,matplotlib,jupyterlab,ipykernel,ngrok"],
        capture_output=True, text=True,
    )
    if probe.returncode:
        raise UpdateError("기존 .venv의 Python 3.10 이상 및 분석·Jupyter·ngrok 패키지를 확인하세요.")
    inputs = args.private_dir / "inputs"
    if not (inputs / "analysis_config.json").is_file():
        raise UpdateError(f"기존 입력 설정이 없습니다: {inputs / 'analysis_config.json'}")
    state = args.private_dir / "runtime"
    private_dir(state)
    return python, inputs, args.private_dir / "outputs", state


def parse_archive(raw):
    """Read only the reviewed public paths; never extract archive paths."""
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise UpdateError("다운로드 파일이 허용 크기를 초과했습니다.")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise UpdateError("압축파일에 중복 경로가 있습니다.")
            roots = {name.split("/", 1)[0] for name in names if name}
            if len(roots) != 1:
                raise UpdateError("GitHub 소스 압축파일 구조가 예상과 다릅니다.")
            root = roots.pop()
            payload = {}
            total = 0
            for name in sorted(PUBLIC_FILES):
                entry = root + "/" + name
                info = archive.getinfo(entry)
                total += info.file_size
                if total > MAX_ARCHIVE_BYTES or info.is_dir():
                    raise UpdateError("공개 소스 파일 크기 또는 형식을 확인하세요.")
                raw_file = archive.read(entry)
                text = raw_file.decode("utf-8")
                if name.endswith(".py"):
                    compile(text, name, "exec")
                if name == NOTEBOOK:
                    nb = json.loads(text)
                    if nb.get("nbformat") != 4 or not isinstance(nb.get("cells"), list):
                        raise UpdateError("Notebook 형식이 올바르지 않습니다.")
                    for cell in nb["cells"]:
                        if cell.get("outputs") or cell.get("execution_count") is not None or cell.get("attachments"):
                            raise UpdateError("공개 Notebook에 실행 결과 또는 첨부물이 포함되어 있습니다.")
                        if cell.get("cell_type") == "code":
                            compile("".join(cell["source"]), NOTEBOOK, "exec")
                payload[name] = raw_file
            return payload
    except (KeyError, UnicodeError, ValueError, SyntaxError, zipfile.BadZipFile) as exc:
        raise UpdateError("다운로드한 소스의 파일 구성 또는 문법 확인에 실패했습니다.") from exc


def download_source(revision):
    url = f"https://codeload.github.com/{REPOSITORY}/zip/{revision}"
    request = Request(url, headers={"User-Agent": "Daegu-MES-Deployment-Updater"})
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read(MAX_ARCHIVE_BYTES + 1)
    except (OSError, URLError) as exc:
        raise UpdateError("GitHub 소스 다운로드에 실패했습니다. 서버의 HTTPS 연결을 확인하세요.") from exc
    return parse_archive(raw)


def local_request(base, endpoint, token, method="GET"):
    request = Request(base + endpoint, method=method, headers={"Authorization": "token " + token, "Accept": "application/json"})
    try:
        with LOCAL_HTTP.open(request, timeout=3) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except HTTPError as exc:
        raise UpdateError(f"기존 Jupyter 인증/API 확인 실패 (HTTP {exc.code}).") from exc


def stop_existing(state, repo):
    locked = launcher_running(state)
    status_file = state / "server_status.json"
    if not status_file.is_file():
        if locked:
            raise UpdateError("서버가 실행 중이지만 상태 파일이 없어 안전하게 중지할 수 없습니다.")
        return
    try:
        status = json.loads(status_file.read_text())
        if status.get("status") not in {"ready", "starting"}:
            if locked:
                raise UpdateError("기존 서버가 정리 중입니다. 종료된 뒤 다시 실행하세요.")
            return
        if status.get("repository_dir") and Path(status["repository_dir"]).resolve() != repo:
            raise UpdateError("상태 파일이 다른 코드 폴더의 서버를 가리킵니다. 중지하지 않았습니다.")
        port = status["port"]
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("invalid port")
        token = (state / "jupyter_token.txt").read_text().strip()
        if not token:
            raise ValueError("missing token")
        base = f"http://127.0.0.1:{port}"
        _, notebook = local_request(base, "/api/contents/" + quote(NOTEBOOK) + "?content=0", token)
        if notebook.get("name") != NOTEBOOK or notebook.get("type") != "notebook":
            raise UpdateError("현재 Jupyter가 이 프로젝트의 Notebook을 제공하는지 확인할 수 없습니다.")
    except (OSError, URLError, ValueError, KeyError, UpdateError) as exc:
        if not locked and not isinstance(exc, UpdateError):
            return
        raise UpdateError("기존 서버를 확인할 수 없어 중지·파일 변경을 수행하지 않았습니다. 실행 상태를 확인하세요.") from exc
    _, kernels = local_request(base, "/api/kernels", token)
    if any(kernel.get("execution_state") == "busy" for kernel in kernels):
        raise UpdateError("Notebook 분석이 실행 중입니다. 셀 실행이 끝난 뒤 업데이트하세요.")
    print("기존 MES 서버를 종료합니다. 입력과 결과 파일은 유지합니다.", flush=True)
    local_request(base, "/api/shutdown", token, method="POST")
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if not launcher_running(state):
            return
        time.sleep(0.25)
    raise UpdateError("기존 실행기의 종료를 확인하지 못했습니다. 소스는 변경하지 않았습니다.")


def install_source(repo, payload, backup):
    """Backup before writing; roll back this function's writes on failure."""
    private_dir(backup)
    existing = {}
    for name in sorted(PUBLIC_FILES):
        target = repo / name
        existing[name] = target.exists()
        if target.exists():
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(target, saved)
    written = []
    try:
        for name, raw in payload.items():
            target = repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as file:
                temporary = Path(file.name)
                file.write(raw)
            try:
                temporary.chmod(0o755 if name in EXECUTABLE else 0o644)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            written.append(name)
    except Exception:
        for name in reversed(written):
            if existing[name]:
                shutil.copy2(backup / name, repo / name)
            else:
                (repo / name).unlink(missing_ok=True)
        raise


def start_server(python, repo, inputs, outputs, state, authtoken, local_only):
    log_path = state / "deployment_start.log"
    if log_path.is_symlink():
        raise UpdateError("배포 로그 경로가 심볼릭 링크입니다.")
    environment = os.environ.copy()
    if authtoken:
        environment["NGROK_AUTHTOKEN"] = authtoken
    elif local_only:
        environment.pop("NGROK_AUTHTOKEN", None)
    args = [str(python), str(repo / "serve.py"), "--port", "0", "--data-dir", str(inputs), "--output-dir", str(outputs), "--state-dir", str(state)]
    if local_only:
        args.append("--local-only")
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(args, cwd=repo, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    status_path = state / "server_status.json"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise UpdateError(f"새 서버가 종료되었습니다. 비공개 로그를 확인하세요: {log_path}")
        try:
            status = json.loads(status_path.read_text())
            if status.get("launcher_pid") == process.pid and status.get("status") == "ready":
                print("업데이트와 서버 시작 완료.")
                print("Notebook URL:", status["notebook_url"])
                token = (state / "jupyter_token.txt").read_text().strip()
                if not token:
                    raise UpdateError("로그인 토큰 파일이 비어 있습니다.")
                print("자동 로그인 링크 (접속 담당자에게만 전달):")
                print(status["notebook_url"] + "?" + urlencode({"token": token}))
                print("Jupyter 왼쪽에서 data/와 outputs/를 열 수 있습니다.")
                return True
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    print("서버 시작 요청은 전달됐지만 준비 완료는 아직 확인되지 않았습니다.")
    print("로그 확인:", log_path)
    print("서버 상태:", status_path)
    return False


def run(args):
    os.umask(0o077)
    python, inputs, outputs, state = validate_installation(args)
    with lock_file(state / "update.lock"):
        print("지정한 GitHub 커밋의 공개 소스를 확인합니다.", flush=True)
        payload = download_source(args.revision)
        authtoken = ""
        if not args.local_only:
            authtoken = os.environ.get("NGROK_AUTHTOKEN", "").strip()
            if not authtoken:
                if not sys.stdin.isatty():
                    raise UpdateError("Abyss의 대화형 터미널에서 실행하여 ngrok 토큰을 입력하세요.")
                authtoken = getpass.getpass("ngrok authtoken: ").strip()
            if not authtoken:
                raise UpdateError("ngrok 토큰이 입력되지 않아 기존 서버를 변경하지 않았습니다.")
        stop_existing(state, args.repository_dir)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + secrets.token_hex(3)
        backup = state / "source_backups" / run_id
        with lock_file(state / "serve.lock"):
            check_destination(args.repository_dir)
            install_source(args.repository_dir, payload, backup)
        print("이전 소스 백업:", backup, flush=True)
        start_server(python, args.repository_dir, inputs, outputs, state, authtoken, args.local_only)
        return 0


def main(argv=None):
    try:
        return run(arguments(argv))
    except KeyboardInterrupt:
        print("업데이트를 중단했습니다.", file=sys.stderr)
        return 130
    except (UpdateError, OSError, ValueError) as exc:
        print(f"업데이트 오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
