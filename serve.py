#!/usr/bin/env python3
"""Run the MES notebook in a private work directory, optionally through ngrok.

The Jupyter file-browser root is NOT an operating-system sandbox. An authenticated
notebook user can execute Python with the permissions of the account running this
process. Never run this as a privileged account on a production host.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
import traceback
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


NOTEBOOK_NAME = "Daegu_MES_quality_analysis.ipynb"
KERNEL_NAME = "daegu-mes-private"
REPOSITORY = Path(__file__).resolve().parent
PRIVATE_HOME = Path.home() / "daegu_mes_private"


class LaunchError(Exception):
    """An actionable startup error; its message must not contain credentials."""


class StopRequested(BaseException):
    def __init__(self, signum: int):
        self.signum = signum


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Loopback probes must not send the Jupyter credential through an HTTP proxy.
HTTP = build_opener(ProxyHandler({}), NoRedirect())


def arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="개인 폴더의 MES 데이터를 JupyterLab에서 실행합니다."
    )
    parser.add_argument("--local-only", action="store_true", help="ngrok 없이 localhost에서만 실행")
    parser.add_argument("--port", type=int, default=8888)
    parser.add_argument("--domain", help="계정에 연결된 ngrok 도메인 (https://와 경로 제외)")
    parser.add_argument("--data-dir", type=Path, default=PRIVATE_HOME / "inputs")
    parser.add_argument("--output-dir", type=Path, default=PRIVATE_HOME / "outputs")
    parser.add_argument("--state-dir", type=Path, default=PRIVATE_HOME / "runtime")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port는 1~65535 범위여야 합니다.")
    if args.local_only and args.domain:
        parser.error("--domain은 ngrok 모드에서만 사용할 수 있습니다.")
    if args.domain:
        parsed = urlsplit("https://" + args.domain)
        if (
            not parsed.hostname
            or parsed.netloc != args.domain
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or ":" in args.domain
            or any(c.isspace() for c in args.domain)
        ):
            parser.error("--domain에는 도메인 이름만 입력하세요. 예: example.ngrok.app")
    for name in ("data_dir", "output_dir", "state_dir"):
        path = getattr(args, name).expanduser().resolve()
        if path == REPOSITORY or REPOSITORY in path.parents:
            parser.error(f"--{name.replace('_', '-')}는 공개 저장소 밖의 개인 폴더로 지정하세요.")
        setattr(args, name, path)
    paths = (args.data_dir, args.output_dir, args.state_dir)
    for index, first in enumerate(paths):
        for second in paths[index + 1 :]:
            if first == second or first in second.parents or second in first.parents:
                parser.error("입력·출력·실행 상태 폴더는 서로 같거나 포함하지 않는 별도 경로로 지정하세요.")
    return args


def private_directory(path: Path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise LaunchError(f"폴더 경로가 아닙니다: {path}")
    if os.name == "posix":
        path.chmod(0o700)


def private_open(path: Path, mode="w"):
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if mode == "a" else os.O_TRUNC)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    if os.name == "posix":
        os.fchmod(fd, 0o600)
    return os.fdopen(fd, mode, encoding="utf-8")


def private_write(path: Path, text: str):
    with private_open(path) as file:
        file.write(text)


@contextmanager
def state_lock(state: Path):
    """OS-owned lock is released even after an unclean process exit."""
    path = state / "serve.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    if os.name == "posix":
        os.fchmod(fd, 0o600)
    file = os.fdopen(fd, "r+b", buffering=0)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            if path.stat().st_size == 0:
                file.write(b"\0")
            file.seek(0)
            try:
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise LaunchError(f"이 상태 폴더를 사용하는 서버가 이미 실행 중입니다: {state}") from exc
        else:
            import fcntl

            try:
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise LaunchError(f"이 상태 폴더를 사용하는 서버가 이미 실행 중입니다: {state}") from exc
        acquired = True
        yield
    finally:
        if acquired and os.name == "nt":
            import msvcrt

            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        file.close()


def ensure_inputs(args):
    if not args.data_dir.exists():
        private_directory(args.data_dir)
        raise LaunchError(
            f"입력 폴더를 만들었습니다: {args.data_dir}\n"
            "기업에서 받은 원본 XLSX/CSV와 필요한 inputs 하위 폴더를 이곳에 복사한 뒤 다시 실행하세요."
        )
    if not args.data_dir.is_dir():
        raise LaunchError(f"입력 경로가 폴더가 아닙니다: {args.data_dir}")
    if not any(
        item.is_file() and item.suffix.lower() in {".xlsx", ".xls", ".csv", ".tsv", ".parquet"}
        for item in args.data_dir.rglob("*")
    ):
        raise LaunchError(
            f"분석 입력 파일이 없습니다: {args.data_dir}\n"
            "기업 원본 XLSX/CSV와 필요한 inputs 하위 폴더를 복사하세요. 파일별 요구사항은 README를 확인하세요."
        )


def prepare_notebook(work: Path, state: Path, run_id: str):
    source = REPOSITORY / NOTEBOOK_NAME
    if not source.is_file():
        raise LaunchError(f"공개 노트북 템플릿이 없습니다: {source}")
    try:
        notebook = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(notebook.get("cells"), list) or notebook.get("nbformat") != 4:
            raise ValueError("not a version-4 notebook")
        for cell in notebook["cells"]:
            if cell.get("cell_type") == "code":
                cell["execution_count"] = None
                cell["outputs"] = []
        notebook.get("metadata", {}).pop("widgets", None)
        notebook.setdefault("metadata", {})["kernelspec"] = {
            "name": KERNEL_NAME,
            "display_name": "Python (MES private)",
            "language": "python",
        }
    except (ValueError, TypeError, AttributeError) as exc:
        raise LaunchError("공개 노트북 템플릿의 JSON 형식을 확인하세요.") from exc
    destination = work / NOTEBOOK_NAME
    if destination.exists():
        if destination.is_symlink() or not destination.is_file():
            raise LaunchError(f"작업 노트북 경로가 일반 파일이 아닙니다: {destination}")
        backups = state / "backups"
        private_directory(backups)
        private_write(backups / f"{run_id}_{NOTEBOOK_NAME}", destination.read_text(encoding="utf-8"))
    private_write(destination, json.dumps(notebook, ensure_ascii=False, indent=1) + "\n")


def prepare_kernel(jupyter_data: Path):
    """Bind this notebook to the launcher's Python, not a user's old python3 spec."""
    kernel_dir = jupyter_data / "kernels" / KERNEL_NAME
    private_directory(kernel_dir)
    specification = {
        "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        "display_name": "Python (MES private)",
        "language": "python",
    }
    private_write(kernel_dir / "kernel.json", json.dumps(specification, indent=2) + "\n")


def write_config(path: Path, args, work: Path, token_file: Path):
    # Explicit settings override permissive inherited user settings. An empty
    # allow_origin keeps same-origin checks; it is not the wildcard '*'.
    settings = {
        "ServerApp.ip": "127.0.0.1",
        "ServerApp.port": args.port,
        "ServerApp.port_retries": 0,
        "ServerApp.open_browser": False,
        "ServerApp.root_dir": str(work),
        "ServerApp.default_url": f"/lab/tree/{NOTEBOOK_NAME}",
        "ServerApp.allow_remote_access": not args.local_only,
        "ServerApp.trust_xheaders": not args.local_only,
        "ServerApp.allow_origin": "",
        "ServerApp.allow_origin_pat": "",
        "ServerApp.allow_credentials": False,
        "ServerApp.disable_check_xsrf": False,
        "ServerApp.allow_unauthenticated_access": False,
        "ServerApp.use_redirect_file": False,
        "ServerApp.allow_root": bool(hasattr(os, "geteuid") and os.geteuid() == 0),
        "PasswordIdentityProvider.hashed_password": "",
        "PasswordIdentityProvider.password_required": False,
        "PasswordIdentityProvider.allow_password_change": False,
        "MappingKernelManager.default_kernel_name": KERNEL_NAME,
    }
    lines = ["from pathlib import Path", "c = get_config()"]
    lines.extend(f"c.{key} = {value!r}" for key, value in settings.items())
    lines.extend(
        [
            f"c.IdentityProvider.token = Path({str(token_file)!r}).read_text(encoding='utf-8').strip()",
            "if not c.IdentityProvider.token:",
            "    raise RuntimeError('A nonempty Jupyter token is required')",
        ]
    )
    private_write(path, "\n".join(lines) + "\n")


def request(base: str, endpoint: str, token=None, method="GET"):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "token " + token
    req = Request(base + endpoint, headers=headers, method=method)
    try:
        with HTTP.open(req, timeout=2) as response:
            return response.status, response.headers, response.read()
    except HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def await_jupyter(process, base: str, token: str, log_path: Path):
    endpoint = "/api/contents/" + quote(NOTEBOOK_NAME) + "?content=0"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise LaunchError(f"JupyterLab이 시작 중 종료되었습니다. 개인 로그: {log_path}")
        try:
            status, _, body = request(base, endpoint, token)
            if status == 200:
                model = json.loads(body)
                if model.get("name") != NOTEBOOK_NAME or model.get("type") != "notebook":
                    raise LaunchError("Jupyter 작업 폴더의 노트북 확인에 실패했습니다.")
                anonymous_status, headers, _ = request(base, endpoint)
                denied = anonymous_status in {401, 403} or (
                    anonymous_status in {302, 303}
                    and urlsplit(headers.get("Location", "")).path == "/login"
                )
                if not denied:
                    raise LaunchError("인증 없는 접근이 차단되지 않아 서버 공개를 중단합니다.")
                lab_status, _, _ = request(base, f"/lab/tree/{NOTEBOOK_NAME}", token)
                if lab_status != 200:
                    raise LaunchError(f"JupyterLab 화면 준비 확인 실패 (HTTP {lab_status}).")
                return
        except (URLError, ConnectionError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(0.25)
    raise LaunchError(f"60초 내 JupyterLab 응답을 확인하지 못했습니다. 개인 로그: {log_path}")


def stop_jupyter(process, base: str, token: str):
    if process is None or process.poll() is not None:
        return
    try:
        request(base, "/api/shutdown", token, method="POST")
        process.wait(timeout=5)
        return
    except (Exception, subprocess.TimeoutExpired):
        pass
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=5)
    except ProcessLookupError:
        return
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)


def run(args):
    ensure_inputs(args)
    if importlib.util.find_spec("jupyterlab") is None:
        raise LaunchError("JupyterLab이 없습니다. 이 Python 환경에서 pip install -r requirements.txt를 실행하세요.")
    if importlib.util.find_spec("ipykernel") is None:
        raise LaunchError("ipykernel이 없습니다. 이 Python 환경에서 pip install -r requirements.txt를 실행하세요.")
    if not args.local_only:
        if not os.environ.get("NGROK_AUTHTOKEN", "").strip():
            raise LaunchError("NGROK_AUTHTOKEN 환경변수가 없습니다. 계정의 authtoken을 설정하거나 --local-only를 사용하세요.")
        if importlib.util.find_spec("ngrok") is None:
            raise LaunchError("공식 ngrok SDK가 없습니다. pip install -r requirements.txt를 실행하세요.")
    for path in (args.state_dir, args.output_dir):
        private_directory(path)
    with state_lock(args.state_dir):
        return run_locked(args)


def run_locked(args):
    # Check the fixed port first. Jupyter also has port_retries=0, preventing a
    # tunnel from accidentally forwarding to a different service on this port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", args.port))
        except OSError as exc:
            raise LaunchError(f"127.0.0.1:{args.port} 포트를 사용할 수 없습니다. 다른 --port를 지정하세요.") from exc
    state = args.state_dir
    work = state / "work"
    runtime = state / "jupyter_runtime"
    config_dir = state / "config"
    jupyter_data = state / "jupyter_data"
    for path in (work, runtime, config_dir, jupyter_data, state / "ipython"):
        private_directory(path)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + secrets.token_hex(3)
    prepare_notebook(work, state, run_id)
    prepare_kernel(jupyter_data)
    token = secrets.token_urlsafe(32)
    token_file = state / "jupyter_token.txt"
    private_write(token_file, token + "\n")
    config_path = config_dir / "mes_jupyter_config.py"
    write_config(config_path, args, work, token_file)
    log_path = state / f"jupyter_{run_id}.log"
    status_path = state / "server_status.json"
    base = f"http://127.0.0.1:{args.port}"
    environment = os.environ.copy()
    environment.update(
        MES_DATA_DIR=str(args.data_dir),
        MES_OUTPUT_DIR=str(args.output_dir),
        MES_STATE_DIR=str(state),
        MES_REPOSITORY_DIR=str(REPOSITORY),
        JUPYTER_CONFIG_DIR=str(config_dir),
        JUPYTER_RUNTIME_DIR=str(runtime),
        JUPYTER_DATA_DIR=str(jupyter_data),
        JUPYTER_PATH=str(jupyter_data)
        + (os.pathsep + environment["JUPYTER_PATH"] if environment.get("JUPYTER_PATH") else ""),
        IPYTHONDIR=str(state / "ipython"),
        PYTHONUNBUFFERED="1",
        PATH=str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", ""),
    )
    # The notebook kernel needs data paths, not the tunnel-account credential.
    for name in ("NGROK_AUTHTOKEN", "JUPYTER_TOKEN", "JUPYTER_TOKEN_FILE", "JUPYTER_PASSWORD"):
        environment.pop(name, None)
    process = None
    ngrok = None
    listener_url = None
    exit_code = 1
    status = {"status": "starting", "mode": "local" if args.local_only else "ngrok", "port": args.port}

    def save_status():
        private_write(status_path, json.dumps(status, ensure_ascii=False, indent=2) + "\n")

    previous_handlers = {}

    def stop(signum, _frame):
        raise StopRequested(signum)

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, stop)
    with private_open(log_path) as log:
        try:
            save_status()
            print(f"JupyterLab 준비 중: {base}", flush=True)
            process = subprocess.Popen(
                [sys.executable, "-m", "jupyterlab", f"--config={config_path}"],
                cwd=work,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=os.name == "posix",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
            await_jupyter(process, base, token, log_path)
            print("localhost 준비 확인: 인증된 Notebook API와 Lab 화면 응답 정상; 인증 없는 API 접근 차단.", flush=True)
            public_base = base
            if not args.local_only:
                import ngrok as ngrok_sdk

                ngrok = ngrok_sdk
                options = {"authtoken_from_env": True}
                if args.domain:
                    options["domain"] = args.domain
                try:
                    with redirect_stdout(log), redirect_stderr(log):
                        listener = ngrok.forward(f"127.0.0.1:{args.port}", **options)
                        listener_url = listener.url()
                    if urlsplit(listener_url).scheme != "https":
                        raise ValueError("The ngrok listener must use HTTPS")
                    public_base = listener_url.rstrip("/")
                except Exception as exc:
                    traceback.print_exc(file=log)
                    log.flush()
                    raise LaunchError(f"ngrok 연결에 실패했습니다. 계정·도메인·네트워크를 확인하세요. 개인 로그: {log_path}") from exc
            url = public_base + f"/lab/tree/{NOTEBOOK_NAME}"
            status.update(status="ready", notebook_url=url, token_file=str(token_file), log_file=str(log_path), jupyter_pid=process.pid)
            save_status()
            print(f"{'로컬' if args.local_only else '공개'} Notebook URL: {url}", flush=True)
            print(f"로그인 토큰 파일: {token_file}", flush=True)
            print("토큰 파일의 값을 로그인 화면에 입력하세요. 토큰은 이 콘솔에 출력하지 않습니다.", flush=True)
            print(f"입력: {args.data_dir}\n분석 결과: {args.output_dir}\n개인 로그: {log_path}", flush=True)
            print("Ctrl+C로 JupyterLab과 터널을 함께 종료합니다.", flush=True)
            while process.poll() is None:
                time.sleep(0.5)
            raise LaunchError(f"JupyterLab이 종료되었습니다 (종료 코드 {process.returncode}). 개인 로그: {log_path}")
        except StopRequested as exc:
            exit_code = 128 + exc.signum
            print("종료 요청을 받았습니다. 서버와 터널을 정리합니다.", flush=True)
        except Exception:
            traceback.print_exc(file=log)
            log.flush()
            raise
        finally:
            # Avoid a second signal interrupting the cleanup of the first one.
            for signum in previous_handlers:
                signal.signal(signum, signal.SIG_IGN)
            try:
                if ngrok is not None and listener_url:
                    try:
                        with redirect_stdout(log), redirect_stderr(log):
                            ngrok.disconnect(listener_url)
                    except Exception:
                        traceback.print_exc(file=log)
                stop_jupyter(process, base, token)
                status["status"] = "stopped" if exit_code != 1 else "failed"
                save_status()
            finally:
                for signum, handler in previous_handlers.items():
                    signal.signal(signum, handler)
    return exit_code


def main(argv=None):
    # POSIX files produced by the launcher and its Jupyter child default to 0600;
    # directories default to 0700. Windows users need a private user-profile path
    # and appropriate NTFS ACLs; chmod is not a Windows ACL implementation.
    if os.name == "posix":
        os.umask(0o077)
    try:
        return run(arguments(argv))
    except LaunchError as exc:
        print(f"실행 오류: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"경로 또는 실행 설정 오류 ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
