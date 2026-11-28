# 업비트 실제 주문 (현물 급락 매수 계좌 따라하기)

`live/upbit_exec.py`는 모의 현물 계좌(`spot/status.json`)를 그대로 따라 업비트에 주문합니다.
모의 계좌가 사면 같은 코인을 시장가로 사고, 모의 계좌가 팔면 보유 수량 전부를 시장가로 팝니다.

## 안전장치
- 기본은 **모의 실행(DRY RUN)**. 실제 주문은 `config.json`의 `"dry_run": false` + 환경변수 `UPBIT_LIVE=1` + API 키가 모두 있어야만 나갑니다.
- 1회 주문 상한 `max_order_krw`, 총예산 `budget_krw`, 바닥선 `floor_krw`(아래로 내려가면 신규 매수 중단, `live/STOPPED` 생성).
- 긴급 정지: `live/STOP` 파일을 만들면 신규 매수 중단(청산 매도는 계속). 지우면 재개.
- 실행 시작 전부터 있던 모의 보유분은 따라 사지 않습니다.

## 준비 순서
1. 업비트 → 마이페이지 → Open API 관리에서 키 발급: **자산조회 + 주문하기만** 체크, **출금은 절대 체크하지 않기**.
2. 키를 쓸 컴퓨터(고정 IP)의 공인 IP를 키에 등록. 업비트 키는 등록된 IP에서만 작동합니다.
3. 그 컴퓨터에 이 저장소를 받고, 키를 저장소 **밖** 파일에 저장:
   `{"access": "...", "secret": "..."}` → 예) `~/.upbit_keys.json`, 그리고 `export UPBIT_KEY_FILE=~/.upbit_keys.json`
4. 조회만 해보기: `python3 live/upbit_exec.py --check` (잔고와 주문 가능 정보가 나오면 키·IP 정상)
5. 모의 실행으로 하루 지켜보기: `python3 live/upbit_exec.py` (로그: `live/log.txt`)
6. 실제 주문 켜기: `config.json`에서 `"dry_run": false`, 실행 시 `UPBIT_LIVE=1 python3 live/upbit_exec.py`
   모의 봇(`paper_futures.py --resume spot/status.json ...`)도 같은 컴퓨터에서 함께 돌아야 합니다.

## 기본 설정 (`config.json`)
예산 70,000원(약 $50) · 동시 4개 · 1회 최대 20,000원 · 바닥선 49,000원(약 $35) · 5초마다 확인.
