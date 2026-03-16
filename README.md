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
