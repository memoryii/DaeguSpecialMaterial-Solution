# 대구특수금속 MES LOT 분석

제공받은 MES 엑셀과 화면 전사 CSV를 읽어 LOT별 수량·불량 현황과 연결 가능성을 점검하는 Jupyter Notebook입니다.

## 회사 담당자 실행

운영자가 서버를 시작한 후 전달하는 Notebook 주소를 Windows의 Edge 또는 Chrome에서 엽니다. 처음 접속할 때 운영자가 별도로 전달한 접속 토큰을 입력합니다. `Daegu_MES_quality_analysis.ipynb`에서 **Run → Run All Cells**를 누르면 위에서 아래까지 분석을 실행합니다. PC에 Python이나 Git을 설치할 필요는 없습니다.

GitHub 화면은 코드 열람용입니다. 실제 실행은 별도 JupyterLab 서버에서 합니다. 이 저장소에 준비된 코드가 있다는 사실만으로 공개 실행 서버가 운영되는 것은 아닙니다. ngrok 주소는 서버 실행과 연결 성공 후 생성됩니다.

## 구현 범위

| 단계 | 처리 내용 |
|---|---|
| 입력 | 원본 엑셀 2개와 스크린샷을 옮긴 CSV·출처 이미지 읽기 |
| 구조 정리 | 파일·시트·컬럼·행 수 및 기록된 기간 확인 |
| 전처리·검증 | 연결키 문자열 보존, 수량·시각 검증, 누락·중복 확인 |
| 연결 점검 | 지시번호·작업순서·실적순번·LOT NO에 따른 제공 기록의 대응 확인 |
| 기초 집계 | 상세 LOT별 양품·불량, 공정 집계 및 자재 소요량 검산 |
| 시각화 | 확인된 LOT 수량, 공정별 불량수량, 기록 경과시간 |
| 저장 | 실행별 CSV·PNG·JSON, 원본 파일의 실행 전후 SHA-256 비교 |

현재 수령 자료의 기초 분석을 재현하는 구현입니다. 공정 사이의 모든 LOT 계보를 자동 복원하거나, 최종검사 불량을 선행 LOT에 임의 배분하거나, 불량 예측모델을 학습하지 않습니다. 자료의 범위와 추가 요청사항은 Notebook 실행 결과에 함께 표시합니다.

## 운영자 빠른 시작

Python 3.10 이상을 사용하는 Linux 서버에서 실행합니다.

```bash
git clone https://github.com/memoryii/DaeguSpecialMaterial-Solution.git
cd DaeguSpecialMaterial-Solution
bash setup.sh
```

별도로 전달받은 비공개 입력 폴더를 `~/daegu_mes_private/inputs/`에 준비합니다. 필요한 파일명과 데이터별 설정은 그 폴더의 `analysis_config.json`에 있습니다. GitHub에서 원본 파일을 다운로드하는 구조가 아닙니다.

```bash
# 로컬 접속으로 먼저 확인
bash start.sh --local-only
```

ngrok 계정의 인증 토큰은 서버 터미널에서 비공개로 설정합니다. 토큰을 코드·문서·채팅에 붙이지 않습니다.

```bash
read -rsp 'ngrok authtoken: ' NGROK_AUTHTOKEN
printf '\n'
export NGROK_AUTHTOKEN
bash start.sh
```

실행 후 출력되는 `https://.../lab/tree/Daegu_MES_quality_analysis.ipynb` 주소와 별도 접속 토큰을 회사 담당자에게 전달합니다. 기존 GSB 주소를 재사용하거나 변경하지 않습니다.

## 코드와 회사 데이터 분리

- 저장소: 실행 결과가 비어 있는 Notebook, 서버 실행 코드, 설치·사용 안내.
- `~/daegu_mes_private/inputs/`: 원본 엑셀·화면 전사 CSV·이미지·분석 설정.
- `~/daegu_mes_private/outputs/`: 매 실행의 분석 결과.
- `~/daegu_mes_private/runtime/`: Jupyter 실행 사본·접속 토큰·로그.

`serve.py`는 Notebook을 비공개 작업 폴더로 복사해 실행합니다. GitHub용 원본 Notebook에 회사 데이터 출력이 자동 저장되는 것을 피하기 위한 구성입니다. 공개 Notebook을 저장소 안에서 직접 실행·저장한 경우에는 업로드 전에 실행 결과를 비워야 합니다.

공개본 검사:

```bash
python3 scripts/check_public.py
```

## 문서

- [회사 담당자 사용 안내](docs/user-guide.md)
- [서버와 ngrok 실행 안내](docs/server-setup.md)
- [입력 자료와 추가 데이터](docs/data-guide.md)

## 참고 문서

서버 연결은 [ngrok Python SDK](https://ngrok.github.io/ngrok-python/)와 [Jupyter Server 인증](https://jupyter-server.readthedocs.io/en/latest/operators/security.html)의 공개 API를 사용합니다. Jupyter 접속자는 서버 계정 권한으로 코드를 실행할 수 있으므로 접속 주소와 인증 토큰은 승인된 담당자에게만 전달합니다.
