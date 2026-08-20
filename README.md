# OGTECH-llm — 온디바이스 음성 파이프라인과 평가 하네스

**SafeAid Kit** (2026 임베디드 소프트웨어 경진대회 자유공모 / 팀 OGTECH) 의 LLM 저장소입니다.
[조직 개요](https://github.com/2026-ESW-OGTECH) · [다른 저장소 안내](https://github.com/2026-ESW-OGTECH/.github)

---

## 이 저장소가 하는 일 한 줄

**인터넷 없이, 말로 물으면 말로 답한다. 그리고 위험한 질문에는 모델이 대답하지 못하게 막는다.**

LLM은 판단 주체가 아니라 **정해진 계약 안에서 텍스트만 다루는 부품**입니다.
역할은 세 가지뿐이고, 경로·방위·거리는 **출력 스키마에 숫자 필드 자체가 없어** 환각할 자리가 없습니다.

| # | 작업 | 출력 한도 |
|---|---|---|
| 1 | 시나리오 분류 | 14개 라벨 중 **1개** (JSON 생성 안 함) |
| 2 | 질의 대상 추출 | `target` × `ask` — 값이 아니라 "무엇을 묻는지"만 |
| 3 | 카드 맞춤 문장 | 2~4줄, 약 96 토큰 |

## 구성

```text
Co-LLM/                        ★ 실행 파이프라인과 검증 (이 저장소의 본체)
├─ scripts/
│  ├─ product_voice.py         제품 음성 경로 진입점
│  ├─ physical_voice.py        물리 버튼 → 음성 질의
│  ├─ pipeline_gate.py         키워드 게이트 (모델 도달 전 차단)
│  ├─ tts_pipeline.py          문장 단위 스트리밍 TTS
│  ├─ product_assistant.py     카드 선택과 문장 조립
│  ├─ device_monitor.py        장치 상태 감시
│  ├─ safeaid_core.py          시나리오 · 고정 카드 정의
│  └─ engines.py · voice_loop.py · stt_prompt.txt
├─ config/
│  ├─ survival_cards.json      검수된 고정 카드
│  ├─ keyword_rules.yaml       키워드 게이트 규칙
│  └─ fixed_audio.json         사전 합성 음성
├─ eval/                       14 라벨 분류 · refuse 누출 평가, 하드웨어 인수 러너
├─ tests/                      단위 테스트 55개
├─ assets/audio/               검수된 고정 안내 음성 (사전 합성 wav)
└─ jetson/                     systemd 유닛과 오디오 환경 설정

docs2/                         조사·계산 근거 문서 ★ 현재 도메인 정본
config/ · harness/ · runner/ · results/   하네스 자리
```

## 확정된 실행 구성

**작업 크기에 따라 최적 실행 타깃이 다릅니다.** 74M 파라미터(whisper base)에서는 커널 실행
오버헤드가 연산량을 압도해 CPU가 유리하고, 1.5B(Qwen2.5)에서는 GPU가 유리합니다.

```text
STT  → CPU      whisper.cpp
LLM  → GPU      llama.cpp, Qwen2.5 1.5B Q4_K_M
TTS  → CPU
```

메모리 대역폭은 공유하므로 **셋을 동시에 올리지 않고 순차 실행**합니다.
LLM만 상주시키고 STT·TTS는 온디맨드 로드/언로드합니다.

### STT 측정 — `-ac 450`이 지연의 대부분을 설명합니다

whisper는 입력이 5초든 30초든 인코더를 30초 멜 윈도로 돌립니다. 5초 클립에서 25초는 순수 패딩 연산입니다.

| 구성 | 지연 |
|---|---:|
| small, `-t 6`, `-ac` 없음 | 13,744 ms `[실측]` |
| base, `-t 6`, `-ac` 없음 | 7,720 ms `[실측]` |
| **base, `-t 6`, `-ac 450`** | **1,494 ms** `[실측]` |
| base, `-t 6`, `-ac 450`, beam 5 | 1,779 ms `[실측]` |

- **`-ng`는 필수입니다.** 빼면 Xavier 통합 메모리에서 91 MiB cudaMalloc에 실패해 SIGSEGV로 죽습니다 `[실측]`.
- **beam search 기각** — 지연 +33%에 출력이 한 글자도 바뀌지 않았습니다 `[실측]`.
- **판정은 중앙값이 아니라 최댓값**으로 봅니다. 데모 조건이 연속 20회라 한 번의 이상치가 곧 실패입니다.
  실제로 중앙값 1위 구성의 최댓값이 12.6초였습니다 `[실측]`.

### 생성 설정

`temperature = 0`. 취향이 아니라 재현성 문제입니다 — 리허설 20회 연속 동일 출력을 보장해야 합니다.
구조화 출력은 JSON Schema 제약(llama.cpp GBNF)으로 강제하며, 문법 실패가 구조적으로 0이므로
**재시도 단계를 두지 않습니다.**

## 지연 병목은 모델이 아니라 프롬프트 길이입니다

Xavier 실측 prefill이 413 tok/s입니다. **3,300 토큰짜리 프롬프트는 prefill만 8초입니다.**
그래서 프롬프트를 불변 → 준가변 → 가변 순으로 조립해 KV 캐시를 살리고,
장치 상태(`DEVICE_STATE`)에 **60 토큰 상한**을 겁니다.

```text
[SYSTEM + 출력 규칙]   ← 완전 고정, KV 캐시에 남음
[SURVIVAL_CARD]        ← 선택된 카드 1장, 세션 내 준고정
[DEVICE_STATE]         ← 요청마다 변함. 60 tok 상한
[USER]                 ← 마지막
```

## 지도 엔진은 이 저장소에 없습니다

경로·방위·거리를 계산하는 지도 엔진의 정본은
**[OGTECH-frontend/MAP](https://github.com/2026-ESW-OGTECH/OGTECH-frontend/tree/main/MAP)** 하나뿐입니다.
이 저장소에는 사본을 두지 않습니다. 같은 모듈이 두 곳에 있으면 어느 쪽이 정본인지 알 수 없고,
한쪽만 고쳤을 때 조용히 갈라지기 때문입니다.

`Co-LLM/eval/run_video_scenario.py`는 지도 엔진과 음성 경로를 함께 도는 통합 검증 하네스라
두 저장소가 모두 필요합니다. 같은 상위 폴더에 나란히 clone하면 자동으로 찾고,
다른 곳에 있으면 `SAFEAID_MAP_ROOT`로 지정합니다.

```bash
git clone https://github.com/2026-ESW-OGTECH/OGTECH-llm.git
git clone https://github.com/2026-ESW-OGTECH/OGTECH-frontend.git

# 경로가 다르면
SAFEAID_MAP_ROOT=/path/to/OGTECH-frontend/MAP python Co-LLM/eval/run_video_scenario.py
```

## 검증

```bash
cd Co-LLM && python -B -m unittest discover -s tests
```

| 대상 | 결과 |
|---|---|
| `Co-LLM/tests/` | 55 tests, OK `[실측: 2026-08-20]` |

지도 엔진 테스트(80건)는 [OGTECH-frontend](https://github.com/2026-ESW-OGTECH/OGTECH-frontend)에서 돕니다.
의존성이 준비되지 않아 실행하지 못한 테스트는 통과로 간주하지 않습니다.

## 안전 경계

- **생명 관련 질문은 모델에 도달하지 않습니다.** `lost / daylight / warmth / sleep_safety / injury / refuse`는
  키워드 게이트가 잡아 검수된 고정 카드로 직행합니다.
- **모호하면 키워드가 결정하지 않습니다.** 두 라벨이 동시에 잡히면 LLM 분류로 강등하되,
  `refuse` 키워드가 있으면 다른 매칭을 무시하고 무조건 `refuse`입니다.
- LLM은 경로·방위·거리·진단·처치·**야생 동식물 식용 판정**을 생성하지 않습니다.
- 실제 GPS 트랙과 내부 검토 자료는 커밋하지 않습니다.

## 문서

`docs2/`가 현재 오지 생존 도메인의 정본입니다. 조사 근거, 전력 예산, 부품 선정(BOM),
하네스 재설계, 첨부 기능 명세가 들어 있습니다.
