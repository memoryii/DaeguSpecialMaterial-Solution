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

```bash
bash start.sh --local-only
```

localhost에서 Jupyter 서버가 준비되면 터미널에 Notebook URL과 접속 토큰 파일 경로가 표시됩니다. 접속 토큰은 파일에서 읽어 담당자에게 별도 전달합니다. 비밀번호·인증을 끄는 옵션은 제공하지 않습니다.

## ngrok 연결

```bash
read -rsp 'ngrok authtoken: ' NGROK_AUTHTOKEN
printf '\n'
export NGROK_AUTHTOKEN
bash start.sh
```

이미 본인 계정에 할당된 ngrok 도메인이 있으면 다음처럼 지정합니다. 기존 GSB 서비스의 도메인은 별도 확인 없이 재사용하지 않습니다.

```bash
bash start.sh --domain your-assigned-domain.ngrok-free.app
```

기존 서버와 충돌하면 포트를 바꿉니다.

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

## GitHub 수정본 업로드

프로젝트 저장소는 [memoryii/DaeguSpecialMaterial-Solution](https://github.com/memoryii/DaeguSpecialMaterial-Solution)입니다. 이 저장소를 클론한 폴더에서 `python3 scripts/check_public.py`로 공개 대상 파일을 검사합니다. 파일별로 staging하고 커밋에 원본 엑셀·CSV·이미지·분석 결과·토큰이 없는지 확인합니다. 기존 GSB 저장소를 덮어쓰지 않습니다.

저장소 쓰기 권한과 Git 인증이 설정된 환경에서 수정한 코드만 커밋하여 업로드합니다.

```bash
python3 scripts/check_public.py
git add .gitignore README.md requirements.txt requirements-tested.txt \
  Daegu_MES_quality_analysis.ipynb serve.py setup.sh start.sh scripts docs
git diff --cached --stat
git commit -m "Update MES LOT analysis and notebook server"
git push origin HEAD
```

위 명령은 GitHub에서 클론한 `DaeguSpecialMaterial-Solution/` 폴더 안에서 실행합니다. Git에 사용자 이름과 이메일이 설정되어 있어야 합니다. 배포 패키지의 `private_data/`를 저장소에 추가하지 않습니다. GitHub에서 새로 클론한 사본에도 서버 입력 데이터는 별도로 배치해야 합니다.

Jupyter의 root 디렉터리 지정은 운영체제 파일 권한의 격리가 아닙니다. 공유 대상자가 코드 실행 권한을 갖는 환경이므로 승인된 담당자용 서버 계정을 사용합니다.
