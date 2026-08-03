# SafeAid 오프라인 지도 변환 검증기

팀의 GraphML 경로 데이터를 Jetson에서 읽고, 지도 엔진이 계산한 현재 위치·목적지·경로를 화면과 `DEVICE_STATE`로 확인하는 로컬 전용 웹앱이다. 인터넷, CDN, 외부 폰트, 프런트엔드 프레임워크를 사용하지 않는다.

> 지도와 경로를 LLM이 계산하지 않는다. 지도 엔진 코드가 계산한 작은 `DEVICE_STATE`만 LLM의 읽기 전용 입력 후보로 보여 준다. LLM의 경로·방위·거리 생성은 허용하지 않는다.

## 지원 입력

- `.graphml`: OSMnx 등으로 미리 만든 WGS84 보행 그래프. 권장 경로다.
- `.osm`, `.xml`: 원본 OSM XML을 읽는 검증용 부분 변환기다. `path`, `footway`, `track`, `steps` 등 주요 보행 way만 다루며 PBF는 지원하지 않는다.
- 업로드 상한은 64MB `[추정: 검증 앱 메모리 상한]`이다.

앱은 입력을 검증한 뒤 `runtime/active_map.json`으로 정규화한다. 원본 업로드와 런타임 산출물은 `runtime/`에만 저장되며 Git에서 제외된다.

```mermaid
flowchart LR
  A["GraphML 또는 OSM XML"] --> B["좌표·CRS·길이·연결망 검증"]
  B --> C["런타임 지도 JSON"]
  C --> D["지도 엔진 A* 계산"]
  D --> E["현재 위치·목적지·경로 표시"]
  D --> F["작은 DEVICE_STATE 읽기 전용 출력"]
```

## 실행

Jetson Xavier NX의 JetPack 5.1.x 기본 Python 3.8을 기준으로 NetworkX 3.1을 고정했다 `[출처: requirements.txt]`.

```bash
cd smartaid-llm/MAP
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Chromium에서 `http://127.0.0.1:8790/`을 연다 `[출처: app.py 기본값]`.

Windows 개발 PC에서는 활성화 명령만 다음처럼 바꾼다.

```powershell
cd smartaid-llm\MAP
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

## 화면 사용법

1. 시작하면 건국대학교 샘플 GraphML이 자동 변환되고 고정 데모 현재 위치와 목적지가 표시된다.
2. `오프라인 지도 넣기`에서 새 GraphML 또는 OSM XML을 선택하면 검증·변환·화면 갱신이 연속으로 실행된다.
3. `현재 위치 지정` 또는 `목적지 지정`을 누르고 지도 안을 터치한다. 두 지점이 있으면 경로를 자동 계산한다.
4. 오른쪽 `LLM READ-ONLY INPUT`에서 지도 전체가 아닌 제한된 `gps`·`route` 상태만 확인한다.

모든 수동 좌표와 샘플 좌표는 실제 Air530 측정이 아니므로 화면의 `DEMO` 표시는 숨기지 않는다. 생산 연동에서는 STM32/Air530이 보낸 fix·정확도·위성 수·좌표 경과 시간을 `/api/route` 입력에 전달해야 한다.

지도 화면에는 `© OpenStreetMap contributors` 귀속을 항상 표시한다. 샘플 데이터의 생성 범위와 라이선스는 `sample_data/ATTRIBUTION.md`를 따른다.

## 검증 규칙

- 좌표는 WGS84(EPSG:4326)만 허용한다.
- 모든 엣지는 0보다 큰 유한 `length`가 있어야 한다.
- 현재 위치나 목적지가 보행망에서 250m보다 멀면 `[추정: 검증용 기본 스냅 상한]` 경로를 만들지 않는다.
- 끊긴 보행망이 여러 개면 경고하고, 서로 다른 연결망 사이의 경로를 만들지 않는다.
- OSMnx의 WKT `LINESTRING`을 보존해 곡선 도로를 직선 노드 연결로 단순화하지 않는다.
- 지도 렌더링은 도로 12,000개까지만 표시한다 `[추정: Chromium 검증 화면 상한]`. 경로 계산 그래프는 줄이지 않는다.
- 대형 지도는 앞부분 도로만 자르지 않고 지도 전체를 격자로 나눠 공간 균등 표본을 표시한다.

## 대형 GraphML 확인

광진구 보행 그래프 `gwangjin_walk.graphml` 25.96MB는 노드 51,756개와 방향 엣지 122,126개를 포함한다 `[실측]`. 개발 PC에서 현재 앱의 전체 업로드는 13.11초, 저장 후 재시작은 3.10초에 완료됐다 `[실측]`. Jetson 처리 시간은 실제 장치에서 별도로 측정해야 한다 `[미검증]`.

업로드 중에는 지도 위에 현재 단계를 크게 표시한다. 별도 터미널에서는 다음 API로 상태를 확인할 수 있다.

```bash
curl -s http://127.0.0.1:8790/api/import-status
curl -s http://127.0.0.1:8790/api/map | python3 -c 'import json,sys; m=json.load(sys.stdin); print(m["source_name"], m["statistics"])'
```

광진구 파일이 활성화됐다면 `source_name`은 `gwangjin_walk.graphml`, 노드와 엣지는 각각 51,756개와 122,126개로 나온다 `[실측]`. 계속 933개와 2,668개가 나오면 이전 앱 프로세스가 실행 중이거나 업로드가 실패한 상태다.

## 테스트

```bash
python -B -m unittest discover -s tests -v
```

회귀 테스트 7개는 고정 데모 경로 913.08m·26개 노드와 대형 지도 공간 표본을 확인한다 `[실측]`. 이 값은 실제 사용자 이동 기록이 아니라 팀원이 넣은 공개 캠퍼스 좌표 쌍이다.

## 범위

이 폴더는 변환 파이프라인 검증용이다. 최종 제품의 지도 타일 서빙과 항법 API는 `smartaid-backend`, 7인치 키오스크 지도 UI는 `smartaid-frontend`로 옮겨야 한다. PMTiles/MBTiles 배경 지도, Air530 UART/NMEA, STM32 NAV1, 체크포인트 DB는 아직 연결하지 않았다.
