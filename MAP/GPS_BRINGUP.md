# Air530 도착 당일 GNSS 연동 절차

## 결론

별도 네이티브 앱을 새로 만들지 않는다. 이 검증 앱은 Jetson 안의 Python 서비스와 Chromium 키오스크가 `127.0.0.1`로만 통신하는 오프라인 로컬 앱이다. 인터넷 웹사이트가 아니며 네트워크 단절 상태에서도 지도 변환, GNSS 수신, 위치 표시와 경로 계산이 동작한다.

입력은 세 단계가 같은 화면과 API를 사용한다.

```text
도착 전   air530_replay.nmea -> gps_service.py -> 지도 화면
초기 점검 Air530 -> 3.3 V USB-UART -> /dev/ttyUSB0 -> gps_service.py
최종 구조 Air530 -> STM32 UART1 -> STM32 GET_FIX -> /dev/ttyACM0 -> gps_service.py
```

## 0. 하드웨어 도착 전 확인

```bash
cd smartaid-llm/MAP
. .venv/bin/activate
python app.py --gps-mode replay
```

Chromium에서 `http://127.0.0.1:8790/`을 연다. GNSS가 `DEMO FIX`, 위성 수가 `SAT 10`, 정확도가 `HDOP 0.8 · ±—`로 시작하면 정상이다 `[출처: sample_data/air530_replay.nmea]`. 재생 마지막 no-fix 문장에서는 확정 좌표를 새로 만들지 않고 마지막 좌표와 경과 시간을 남긴다.

터미널에서도 확인할 수 있다.

```bash
curl -s http://127.0.0.1:8790/api/gps | python3 -m json.tool
```

## 1. Air530 직접 연결 — 모듈 자체 점검

이 단계는 STM32 펌웨어와 분리해 안테나, UART와 NMEA 수신부터 확인하기 위한 임시 경로다.

1. Air530과 USB-UART의 `GND`를 공통으로 연결한다.
2. Air530 `TX`를 USB-UART `RX`에 연결한다.
3. 로직 전압은 3.3 V를 사용한다. 현재 하드웨어 문서도 Air530 UART를 3.3 V로 고정하며 5 V 로직을 금지한다 `[출처: smartaid-embedded/stm32_smart_tray_controller/README.md]`.
4. u.FL 외장 안테나를 연결하고 하늘이 트인 실외에서 시험한다.

Jetson에서 포트를 확인한다.

```bash
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```

권한이 없으면 사용자를 `dialout` 그룹에 추가한 뒤 로그아웃·로그인한다.

```bash
sudo usermod -aG dialout "$USER"
```

현재 앱의 Air530 직결 기본 baud는 9600이다 `[미검증]`. 수신되지 않으면 모듈 데이터시트나 실제 출력 설정을 확인해 화면의 baud를 바꾼다.

```bash
python app.py --gps-mode air530 --gps-port /dev/ttyUSB0 --gps-baud 9600
```

또는 앱의 `GPS 연결 → Air530 직결`에서 포트와 baud를 고른다. NMEA 체크섬이 맞고 GGA/RMC가 fix를 보고해야 현재 위치가 녹색으로 바뀐다. GGA의 HDOP만으로 `±m` 정확도를 만들어 내지 않으므로 직결 모드에서 `±—`가 표시될 수 있으며 이는 정상이다.

## 2. STM32 최종 연결

최종 배선은 Air530을 STM32 `UART1`, Jetson 명령 채널을 STM32 `UART3`에 둔다 `[출처: smartaid-embedded/stm32_smart_tray_controller/README.md]`. Jetson-STM32 명령 채널은 115200 baud와 한 줄 JSON 계약을 사용한다 `[출처: 같은 문서]`.

앱은 약 1초마다 `[출처: gps_service.py]` 다음 명령을 보낸다.

```text
GET_FIX\n
```

fix 응답:

```json
{"ok":true,"event":"fix","lat":37.12345,"lon":128.54321,"acc_m":6.2,"sats":11,"age_s":2}
```

no-fix 응답:

```json
{"ok":true,"event":"fix","fix":false,"last_age_s":840}
```

실행 예시는 다음과 같다.

```bash
python app.py --gps-mode stm32 --gps-port /dev/ttyACM0 --gps-baud 115200
```

`acc_m`이 없으면 앱은 정확도를 모름으로 표시한다. no-fix에서는 새 위치를 추측하지 않고 프로세스가 이미 받은 마지막 확정 좌표와 STM32가 보고한 `last_age_s`만 표시한다.

## 3. 현장 합격 기준

- 네트워크 케이블과 Wi-Fi를 끈 상태에서 앱이 시작된다.
- 실물 fix에서 현재 위치가 녹색이고 `SAT`, `AGE`, 보고된 경우에만 `±m`가 함께 보인다.
- 안테나를 분리하거나 실내로 이동해 no-fix를 만들면 현재 위치가 회색 `마지막`으로 바뀌며 좌표를 이동 추정하지 않는다.
- USB 직렬 케이블을 뽑으면 입력 오류 또는 연결 끊김이 적색/회색으로 드러난다.
- 목적지를 누르면 지도 엔진이 경로를 계산하고 LLM 입력에는 계산 결과만 들어간다.
- NMEA 재생 모드에서는 `DEMO`가 항상 보이며 실물 센서 fix로 오인되지 않는다.

## 현재 남은 하드웨어 의존 작업

`smartaid-embedded/stm32_smart_tray_controller/README.md`에는 `GET_FIX` 계약이 정의돼 있지만, 현재 `stm32_smart_tray_controller.ino`는 삭제된 서보·수납 구조의 레거시 구현이다 `[실측: 2026-08-03 저장소 점검]`. 따라서 앱의 STM32 모드는 준비됐지만 최종 실물 연동 전에 STM32 펌웨어가 Air530 NMEA 파싱과 위 JSON 응답을 실제로 구현해야 한다.
