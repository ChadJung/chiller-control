# Chiller Control System

산업용 냉동기 RS-485 Modbus RTU 원격 제어 시스템.
PC에서 웹서버를 실행하고, 스마트폰 브라우저로 냉동기를 실시간 모니터링/제어합니다.

## 시스템 구성도

```
[냉동기] ──RS-485──> [Waveshare WiFi 게이트웨이] ──Wi-Fi──> [PC: FastAPI 서버]
                                                                │ Wi-Fi
                                                          [스마트폰 브라우저]
```

> 테스트 시에는 게이트웨이 대신 PC 내장 Modbus 시뮬레이터를 사용합니다.

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| Modbus 통신 | pymodbus 3.7 (RTU / TCP) |
| 백엔드 API | FastAPI + uvicorn |
| 실시간 통신 | WebSocket |
| DB | SQLite (aiosqlite + SQLAlchemy) |
| 프론트엔드 | Vanilla HTML/JS (빌드 도구 불필요) |

## 빠른 시작 (테스트베드)

### 1. 의존성 설치

```bash
cd chiller-control
pip install -r requirements.txt
```

### 2. 시뮬레이터 실행 (가상 냉동기)

```bash
cd backend
python simulator.py
```

- `127.0.0.1:5020`에서 Modbus TCP 서버 시작
- 온도, 압력, 압축기 등 실제 냉동기 동작을 시뮬레이션

### 3. 웹서버 실행 (새 터미널)

```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8888
```

### 4. 브라우저 접속

- PC: `http://localhost:8888`
- 스마트폰 (같은 Wi-Fi): `http://<PC의 IP>:8888`

## 주요 기능

- **Dashboard** - 온도, 압력, 장비상태 실시간 모니터링 (2초 주기)
- **Control** - 전원 ON/OFF, 운전모드 변경, 설정온도 조정, 알람 리셋
- **History** - 온도/압력 추이 실시간 차트
- **Alarms** - 알람 이력 및 제어 감사 로그
- **Registers** - 전체 Modbus 레지스터 실시간 뷰

## 실제 냉동기 연결

### 필요 장비

- RS-485 to WiFi 게이트웨이 (Waveshare RS485 to WiFi/ETH 권장, $15~30)
- RS-485 케이블 (A, B, GND 3선)

### 설정 변경

`backend/.env` 파일 수정:

```ini
MODBUS_MODE=tcp
MODBUS_TCP_HOST=192.168.x.x    # 게이트웨이 IP로 변경
MODBUS_TCP_PORT=502             # 게이트웨이 포트 (보통 502)
```

### 레지스터 맵 교체

냉동기 제조사 매뉴얼의 레지스터 주소표를 기반으로 YAML 파일을 작성합니다:

```
backend/register_maps/chiller_default.yaml  ← 이 파일을 수정하거나 새 파일 생성
```

`.env`에서 `REGISTER_MAP_FILE` 경로를 변경하면 됩니다.

## 프로젝트 구조

```
chiller-control/
├── requirements.txt                  # Python 의존성
├── backend/
│   ├── .env                          # 환경설정 (Modbus 주소, DB 등)
│   ├── main.py                       # FastAPI 서버 진입점
│   ├── config.py                     # pydantic-settings 설정
│   ├── simulator.py                  # Modbus 시뮬레이터 (테스트용)
│   ├── modbus/
│   │   ├── client.py                 # Modbus 연결 관리 (TCP/RTU 자동전환)
│   │   ├── register_map.py           # YAML 레지스터 맵 로더
│   │   ├── parser.py                 # raw 값 → 공학단위 변환
│   │   └── poller.py                 # 폴링 그룹별 스케줄러
│   ├── api/routers/
│   │   ├── registers.py              # GET /api/registers
│   │   ├── control.py                # POST /api/control/write
│   │   ├── history.py                # GET /api/history/{id}
│   │   └── alarms.py                 # GET /api/alarms
│   ├── db/
│   │   ├── database.py               # SQLAlchemy async 세션
│   │   ├── models.py                 # ORM 모델 (이력, 알람, 감사로그)
│   │   └── crud.py                   # DB CRUD 헬퍼
│   └── register_maps/
│       └── chiller_default.yaml      # 냉동기 레지스터 맵 정의
├── frontend/
│   └── dist/
│       └── index.html                # 웹 UI (단일 파일, 빌드 불필요)
```

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/status` | 시스템 상태 |
| GET | `/api/registers` | 전체 레지스터 현재값 |
| GET | `/api/registers/{id}` | 단일 레지스터 조회 |
| GET | `/api/registers/meta/all` | 레지스터 맵 메타데이터 |
| POST | `/api/control/write` | 레지스터 쓰기 (제어) |
| GET | `/api/history/{id}` | 레지스터 이력 조회 |
| GET | `/api/history/controls/log` | 제어 감사 로그 |
| GET | `/api/alarms` | 알람 이력 |
| GET | `/api/alarms/current` | 현재 알람 상태 |
| WS | `/ws/realtime` | 실시간 WebSocket 스트림 |

---

## 현재 상태 & TODO (2026-06-03 현장 방문 기준)

### 진행 중: 실기기 통신 디버깅 — "일산 대교빌딩" 냉동기

현장 게이트웨이(`192.168.24.31:5000`, `rtu_over_tcp`)에 연결해 실사 테스트했으나,
**데이터 수신은 아직 실패**. 현재까지 좁혀진 상태는 아래와 같음.

**✅ 정상으로 확인된 것**
- 네트워크 → 게이트웨이 TCP 연결 정상 (ping, 포트 5000/80 open)
- **장비(D_CH60)까지 도달 확인** — Modbus exception 응답이 옴 (`0x82`/`0x81` 에코).
  케이블 분리 시 응답이 사라지는 것으로 *장비 발신*임을 검증.
- 본체 통신 설정: **Unit ID 1, Baud 19200, 8N1** (게이트웨이 설정과 일치)
- 레지스터 맵 주소 변환(0-based)은 X30 매뉴얼(엑셀/PDF)과 정확히 일치

**❌ 문제: 정상값(OK) 수신 0건**
- 모든 주소가 `Illegal Data Address`(FC2) / `Illegal Function`(FC1) / timeout
- 특히 `운전상태`(FC2 addr 0/1/2 = 10001~10003)가 모두 *Illegal Data Address*
  → **0,1,2가 전부 없으므로 단순 off-by-one도 아님**
- 통신이 간헐 불안정 (몇 요청 burst 후 연결 끊김, WinError 1236 재연결 거부)

**핵심 의문:** 장비 화면 모델명은 **`D_CH60`**, 보유 문서는 **LGC-X30 / LSM-X30**.
동일 계열이라면 맵이 같아야 하는데 OK가 0건 → 주소 오프셋 또는 다른 메모리맵 의심.

### TODO (다음 작업 — 문서 탐독 + 프로토콜 디버깅)

- [ ] `docs/X30 통신프로토콜*.xls` / `*.pdf` 정밀 재검토 — 주소 베이스/오프셋 가정 재확인
- [ ] **D_CH60 ≠ LGC-X30 가능성** 조사 (별도 통신 프로토콜 문서 확보)
- [ ] 전 주소 brute-force 스캔(FC1~4, 0~199)으로 **OK 나오는 주소 1개라도 탐색** → 오프셋 역산
- [ ] **RTU framer ↔ Modbus-TCP(socket) framer** 비교 (게이트웨이 동작모드 영향 확인)
- [ ] 통신 안정화: 재연결 간격(backoff)·timeout 튜닝, burst 후 끊김 원인 규명
- [ ] 엑셀 `Message List` 시트(237개) 기반 운전/경보/이상 **메시지 코드 → 한글 디코딩** 맵 작성

### 이번 세션에서 수정/추가한 것

- **reconnect storm 버그 수정** — `modbus/client.py`에 `reconnect_delay=0`(pymodbus 자동재연결 끔),
  `device_manager.stop_all()`을 async로 바꿔 소켓 close를 await (reload 시 좀비 연결 누적 방지)
- **프론트엔드 API_BASE same-origin화** — `frontend/dist/index.html`의 `:8888` 하드코딩 제거
  (백엔드가 서빙하는 포트로 자동 호출). 모델 드롭다운이 비던 문제 해결
- **레지스터 맵 보강** — 엑셀 원본에만 있던 `30051 펌프 압력(AI1)`을 X30 맵에 추가
- **X30 시뮬레이터 추가** — `backend/x30_simulator.py` (흡수식 사이클, RTU-over-TCP)

### 진단 도구 (`backend/diag_*.py`)

현장 디버깅용 단독 스크립트. 게이트웨이 IP/포트는 파일 상단 상수로 하드코딩.

| 스크립트 | 용도 |
|----------|------|
| `diag_gateway.py` | framer(RTU/SOCKET) × unit_id 조합 프로브 |
| `diag_sweep.py` | FC별 대표 주소 스윕 |
| `diag_offset.py` | 0-based vs 1-based 주소 비교 |
| `diag_quality.py` | FC2 주소 0~N 스윕 + 응답률(OK/EXC/TIMEOUT) 측정 |
| `diag_cable.py` | 케이블 분리 검증 (응답이 장비 발신인지 확인) |
