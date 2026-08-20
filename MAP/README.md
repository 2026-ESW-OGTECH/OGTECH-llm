# SafeAid 오프라인 지도·STM32 센서 앱

Jetson Xavier NX에서 STM32F401RE 센서 허브의 GPS·온습도·기압·CO·RTC·물리 버튼을 받아 7인치 화면에
표시하고, 오프라인 보행 지도에서 경로·트레일 이탈·일출몰·베이스캠프 귀환 권고 시각을 계산하는 로컬 앱이다.
센서·버튼·전원 gate의 실제 하드웨어 동작은 모두 아직 `[미검증]`이며, 아래 내용은 현재 소스 코드의 계약이다.

## 화면 두 개

| URL | 용도 |
|---|---|
| `http://127.0.0.1:8790/product/` | 실제 1024×600 제품 화면 |
| `http://127.0.0.1:8790/` | 기존 지도 변환·GPS 연결 개발자 도구 |
| `http://127.0.0.1:8790/video/` | 촬영용 자동 DEMO 화면 |

기존 디자인과 개발자 도구는 유지했다. 제품 화면 오른쪽 위의 고정 `DEMO` 칸은 환경 계기로 바뀌었다.
재생 데이터나 샘플 지도가 실제로 사용될 때만 지도 이름 옆에 작은 `DEMO` 태그가 표시된다.

`/video/`는 영상 재현을 위한 합성 이동·장면 자동 전환 화면이므로 사용자 확인을 생략할 수 있다. 실제
사용자 계약은 `/product/`이며, 물 POI 후보는 음성 확인 전 목적지로 저장하지 않는다.

## 구현 기능

- STM32 `115200 8N1` JSONL 텔레메트리, CRC-16/CCITT-FALSE 검증
- 직렬 단선 후 2초 간격 자동 재연결 `[출처: gps_service.py]`
- Air530 fix·마지막 좌표·경과 시간·위성 수·정확도 표시
- SHT40 온도·습도, BMP390 기압·추세, ZE07-CO ppm·예열·경보 표시
- DS3231 `0x68` UTC를 표시하되 OSF 또는 날짜·시간 검증 실패 시 `rtc.valid=false`로 fail-closed 처리
- BMP390 `0x77` 우선·`0x76` 차순 탐색, `pressure_valid`와 10분 이상 표본의 `press_trend` 분리 표시
- 센서 입력이 3초 넘게 멈추면 live 상태 해제 `[출처: gps_service.py]`
- 보행로 노드가 아니라 **선분**까지의 트레일 이탈 거리 계산
- 일출·일몰·시민박명 완전 오프라인 계산
- 베이스캠프 경로 거리 + 보행 속도 + 안전 여유로 귀환 권고 시각 계산
- 목적지·베이스캠프·체크포인트 저장 API
- STM32 `PA0` 전원, `PA1` 체크포인트, `PA4` 음성 버튼 edge를 좌표 없이 검증·전달
- 전원 버튼 2초 길게 누름 뒤 로컬 정상 종료 ACK와 STM32 `PC9` Jetson 전원 gate 제어
- CO 경보 시 브라우저 보조음. 1차 물리 경보는 STM32 단독 출력

## 실행

JetPack 5.1.x 환경에서:

```bash
cd OGTECH-llm/MAP
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python app.py --gps-mode stm32 --gps-port /dev/ttyACM0 --gps-baud 115200
```

하드웨어 없이 NMEA 경로만 확인할 때:

```bash
python app.py --gps-mode replay
```

replay는 실제 센서가 아니므로 제품 화면에 `DEMO`가 유지된다.

STM32 포트가 아직 없거나 케이블이 분리된 상태에서도 `jetson/start-map.sh`는 서버를 저하 상태로 기동한다.
제품 화면은 GPS·센서를 회색 대기로 표시하고 위치를 추정하지 않으며, `GpsService`가 2초마다 같은 포트에
재연결을 시도한다. 포트가 나타나면 서버를 다시 시작하지 않아도 텔레메트리 수신을 재개한다. 이는 센서
정상 판정이 아니라 단선 상태를 명시적으로 보이는 복구 경로다.

전체 배선, STM32 빌드, Jetson 복사 파일, systemd와 키오스크 설정은
[STM32_JETSON_SETUP.md](STM32_JETSON_SETUP.md)에 있다.

## API

| 메서드·경로 | 내용 |
|---|---|
| `GET /api/device` | 화면용 통합 센서·항법 상태 |
| `GET /api/device/events` | 통합 상태 SSE |
| `GET /api/gps` | 원시 GNSS·센서 수신 상태 |
| `GET /api/buttons` | 마지막 STM32 물리 버튼 edge와 카운트(좌표 없음) |
| `GET /api/buttons/events` | 새 물리 버튼 edge만 내보내는 SSE(좌표 없음) |
| `GET /api/map` | 현재 지도 렌더링 표본 |
| `POST /api/route` | 명시 좌표 간 지도 엔진 경로 계산 |
| `GET /api/waypoints` | 저장 지점 조회 |
| `POST /api/waypoints` | `save_current`, `set`, `select`, `remove` |
| `GET /api/voice` | 음성 MAP 제어 상태와 허용 action |
| `GET /api/voice/events` | 음성 명령·화면 상태 SSE |
| `POST /api/voice/commands` | 숫자 필드 없는 열거형 MAP action 실행 |
| `POST /api/power/shutdown-ack` | 보류 중인 STM32 전원 종료 요청에만 `POWER OFF ACK`를 큐잉 |
| `POST /api/power/shutdown-cancel` | ACK 뒤 systemd 종료 요청이 실패한 transaction에만 `POWER OFF CANCEL`을 큐잉 |

Co-LLM은 저장된 지점의 이름/ID에 대응하는 열거형 action만 호출할 수 있다. 좌표·거리·방위·경로·귀환
시각을 LLM이 쓰는 API는 제공하지 않는다. 허용 action에는 `clear_destination`가 포함된다.
`repeat_response`는 MAP action이 아니라 Co-LLM repeat store v2가 `scenario`·`map_action`·`map_status`·`source_id` provenance로 검수 고정 문장을 재구성해 재생하는 별도 동작이다. `speech` 원문은 저장하지 않는다.

## 물리 버튼·전원 gate 계약

- 버튼은 active-low, 40 ms debounce이며 `PA0=power`, `PA1=checkpoint`, `PA4=voice`다. 서버는
  `power/checkpoint/voice`와 `pressed/released/held_ms`만 수용하고 좌표는 절대 전달하지 않는다.
- `PA0`을 2초 이상 누른 뒤 놓으면 STM32가 `shutdown_requested`를 내보낸다. Jetson의
  `smartaid-power-manager`는 CRC로 검증된 pending을 확인하고 `/api/power/shutdown-ack`로 ACK를 먼저
  보낸 뒤 `systemctl poweroff --no-block`을 요청한다. STM32는 ACK 뒤 `PC9` gate 차단을 **90초 후**로
  예약한다. systemd 요청이 실패하면 서비스가 즉시 `POWER OFF CANCEL`을 보내 예약을 취소한다.
  ACK가 없으면 **120초 후** pending을 취소하고 gate를 유지한다.
- gate가 꺼진 상태에서 전원 버튼을 놓으면 STM32가 `PC9`을 다시 켠다. 이 절차는 전원 차단 사실이나
  정상 종료 성공을 화면에서 추정·확정하지 않는다. 모든 실제 버튼·gate 검증은 `[미검증]`이다.

## 지도 입력

- `.graphml`: WGS84 보행 그래프 권장
- `.osm`, `.xml`: 검증용 OSM XML 부분 변환
- 업로드 상한 64 MB `[추정: 검증 앱 메모리 상한]`
- 런타임 지도·저장 지점은 `runtime/`에 두고 Git에서 제외

건국대 샘플 지도와 NMEA는 공개 데모 데이터다. 실제 GPS 트랙은 커밋하지 않는다.

## 테스트

```bash
python -B -m unittest discover -s tests -v
```

현재 결과는 `76/76` 통과 `[실측: 2026-08-19]`이다. 테스트는 지도 회귀, NMEA/STM32 fix 호환, 텔레메트리 CRC 손상
거부, stale 센서, 선분 이탈 거리, 저장 지점·귀환 시각, 서울 일출몰과 극지 예외, 음성 action·부팅
진단·제품 화면, DS3231 UTC·stale·OSF 경계, BMP390 확인 상태, 물리 버튼·전원 ACK, 3분 전 위치 역추적을 포함한다. 경로 cache는 `test_crossing_route_cache_is_rejected_until_progress_disambiguates_it`,
`test_overlapping_route_cache_uses_late_progress_to_disambiguate`,
`test_route_cache_includes_exact_eight_meter_boundary`, `test_route_cache_recomputes_above_eight_meter_boundary`로
자기교차/겹침 진행량 disambiguation, 정확히 8 m 포함, 8 m 초과 재경로를 검증하며 zero-length polyline 경계도
검증한다. 브라우저 증거는
[`test-results/product_ui_1024x600.json`](test-results/product_ui_1024x600.json)이다.
