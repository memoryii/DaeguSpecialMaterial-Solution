# 대구특수금속 MES LOT 분석

제공받은 MES 엑셀과 화면 전사 CSV를 읽어 LOT별 수량·불량 현황과 연결 가능성을 점검하는 Jupyter Notebook입니다.

## 시작하기

1. 운영자가 서버를 시작한 후 전달하는 Notebook 주소를 Windows의 Edge 또는 Chrome에서 엽니다.
2. 처음 접속할 때 운영자가 별도로 전달한 접속 토큰을 입력합니다.
3. `Daegu_MES_quality_analysis.ipynb`에서 **Run → Run All Cells**를 누르면 위에서 아래까지 분석을 실행합니다.
4. PC에 Python이나 Git을 설치할 필요는 없습니다.


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
- [입력 자료와 추가 데이터](docs/data-guide.md)
