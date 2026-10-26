# 서버와 ngrok 실행 안내

## 준비물

- 계속 켜 둘 Linux 서버와 Python 3.10 이상
- 이 저장소와 별도로 전달한 비공개 입력 폴더
- ngrok 계정의 authtoken
- 코드 수정본을 업로드할 경우 해당 GitHub 저장소의 쓰기 권한

GitHub 저장소 생성·업로드와 ngrok 터널 연결은 서로 다른 작업입니다. ngrok 주소를 만들려면 서버에서 프로세스가 계속 실행되어야 합니다. 임시 작업 환경을 영구 운영 서버로 가정하지 않습니다.

## 설치와 입력 배치

```bash
git clone https://github.com/memoryii/DaeguSpecialMaterial-Solution.git
cd DaeguSpecialMaterial-Solution
bash setup.sh
mkdir -p "$HOME/daegu_mes_private"
chmod 700 "$HOME/daegu_mes_private"
```

별도 입력 자료의 `inputs/` 폴더를 `~/daegu_mes_private/inputs/`에 복사합니다. `analysis_config.json`, 엑셀, 전사 CSV, 근거 이미지의 상대 위치를 유지합니다. 원본은 읽기만 하며 변경하지 않습니다.

기본 `python3`가 3.10 미만이고 Conda를 사용하는 서버에서는 `setup.sh` 대신 프로젝트 폴더에서 다음으로 전용 환경을 만듭니다. 새 환경을 처음 만들 때만 실행합니다.

```bash
conda create -y -p "$PWD/.venv" python=3.11 pip
.venv/bin/python -m pip install -r requirements.txt
```

```bash
bash start.sh --local-only --port 0
```

localhost에서 Jupyter 서버가 준비되면 터미널에 Notebook URL과 접속 토큰 파일 경로가 표시됩니다. 접속 토큰은 파일에서 읽어 담당자에게 별도 전달하거나 아래의 자동 로그인 링크를 사용합니다.

Jupyter의 파일 목록에는 Notebook, `data/`, `outputs/`, `src/`가 표시됩니다. `data/`와 `outputs/`는 각각 지정된 비공개 입력·출력 폴더를 연결하여 보여줍니다. 토큰·로그·서버 설정은 파일 목록 밖에 둡니다. 동일한 이름의 일반 폴더나 다른 대상의 링크가 이미 있으면 덮어쓰지 않고 중단합니다.

## ngrok 연결

```bash
read -rsp 'ngrok authtoken: ' NGROK_AUTHTOKEN
printf '\n'
export NGROK_AUTHTOKEN
bash start.sh --port 0
```

이미 본인 계정에 할당된 ngrok 도메인이 있으면 다음처럼 지정합니다. 기존 GSB 서비스의 도메인은 별도 확인 없이 재사용하지 않습니다.

```bash
bash start.sh --domain your-assigned-domain.ngrok-free.app
```

`--port 0`은 사용 가능한 포트를 자동 선택합니다. 특정 포트가 필요할 때만 번호를 지정합니다.

```bash
bash start.sh --port 8890
```

다른 입력·출력 위치도 지정할 수 있습니다.

```bash
bash start.sh \
  --data-dir /absolute/private/inputs \
  --output-dir /absolute/private/outputs \
  --state-dir /absolute/private/runtime
```

## 계속 실행하기

터미널 종료 후에도 유지하려면 서버에 `tmux`가 설치된 경우 새 세션을 만들고 그 안에서 실행합니다.

```bash
tmux new -s daegu-mes
# 새 세션 안에서 저장소로 이동한 뒤 위의 ngrok 연결 명령 실행
```

`Ctrl+B` 다음 `D`로 세션을 빠져나옵니다. 다시 연결할 때는 `tmux attach -t daegu-mes`를 실행합니다. 서버가 재부팅되거나 프로세스가 종료되면 다시 시작해야 합니다. 자동 재시작이나 고정 도메인이 설정되었다고 가정하지 않습니다.

중지는 실행 터미널에서 `Ctrl+C`입니다. 실행기가 자신이 시작한 Jupyter 프로세스와 터널을 정리합니다.

## 자동 로그인 링크

서버가 준비된 뒤 운영자 터미널에서 실행합니다. 이 링크에는 로그인 정보가 포함되므로 공개 README나 GitHub에 넣지 않습니다. 서버를 재시작한 뒤에는 새 링크를 확인합니다.

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from urllib.parse import urlencode
runtime = Path.home() / 'daegu_mes_private/runtime'
state = json.loads((runtime / 'server_status.json').read_text())
assert state['status'] == 'ready', '서버 실행 상태를 확인하세요.'
token = (runtime / 'jupyter_token.txt').read_text().strip()
print(state['notebook_url'] + '?' + urlencode({'token': token}))
PY
```

## 기존 ZIP 설치본 업데이트

`scripts/update_deployment.py`는 이 저장소의 확정된 커밋을 받아 코드만 갱신합니다. `.venv`·입력자료·기존 결과는 유지합니다. 실행 중인 커널이 바쁘면 중단하며, 준비가 끝난 뒤 해당 Jupyter 서버의 인증된 종료 API로 서버를 종료하고 새 코드로 다시 시작합니다. 기존 소스는 `runtime/source_backups/`, 작업 Notebook과 분석 모듈은 `runtime/backups/`에 보존합니다.

운영자는 새 버전의 업데이트 스크립트를 받은 뒤 기존 `repository/` 폴더에서 실행합니다. `COMMIT_SHA`는 배포할 버전의 40자리 커밋으로 바꿉니다.

```bash
.venv/bin/python /absolute/path/update_deployment.py --revision COMMIT_SHA
```

ngrok 인증 토큰을 요구하면 서버 터미널에 입력합니다. 기존 입력자료를 다시 업로드할 필요는 없습니다. 실행 성공 시 새 접속 주소와 자동 로그인 링크가 표시됩니다. 업데이트 스크립트는 비밀번호·토큰을 소스나 명령 인자에 저장하지 않습니다. 서버 재부팅 후 자동 재시작을 설정하는 작업은 포함하지 않습니다.

## GitHub 수정본 업로드

프로젝트 저장소는 [memoryii/DaeguSpecialMaterial-Solution](https://github.com/memoryii/DaeguSpecialMaterial-Solution)입니다. 이 저장소를 클론한 폴더에서 `python3 scripts/check_public.py`로 공개 대상 파일을 검사합니다. 파일별로 staging하고 커밋에 원본 엑셀·CSV·이미지·분석 결과·토큰이 없는지 확인합니다. 기존 GSB 저장소를 덮어쓰지 않습니다.

저장소 쓰기 권한과 Git 인증이 설정된 환경에서 수정한 코드만 커밋하여 업로드합니다.

```bash
python3 scripts/check_public.py
git add .gitignore README.md requirements.txt requirements-tested.txt \
  Daegu_MES_quality_analysis.ipynb serve.py setup.sh start.sh scripts src docs
git diff --cached --stat
git commit -m "Update MES LOT analysis and notebook server"
git push origin HEAD
```

위 명령은 GitHub에서 클론한 `DaeguSpecialMaterial-Solution/` 폴더 안에서 실행합니다. Git에 사용자 이름과 이메일이 설정되어 있어야 합니다. 배포 패키지의 `private_data/`를 저장소에 추가하지 않습니다. GitHub에서 새로 클론한 사본에도 서버 입력 데이터는 별도로 배치해야 합니다.

Jupyter의 root 디렉터리 지정은 운영체제 파일 권한의 격리가 아닙니다. 공유 대상자가 코드 실행 권한을 갖는 환경이므로 승인된 담당자용 서버 계정을 사용합니다.
