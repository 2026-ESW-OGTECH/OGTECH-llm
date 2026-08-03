# config

동결된 LLM 역할 3개에 맞춰 **새로 작성해야 한다.** 아직 비어 있다.

1. 시나리오 분류 → **14개 라벨 중 하나.** 출력 라벨 1개.
2. 질의 대상 추출 → `target` × `ask`. **값이 아니라 "무엇을 묻는지"만.**
3. 카드 맞춤 문장 → 2~4줄, 약 96토큰.

허용 `scenario_id`:

```
lost, route, daylight, weather, shelter, warmth, water, food,
sleep_safety, injury, wildlife, gear, refuse, unknown
```

## 만들 파일

| 파일 | 내용 |
|---|---|
| `system_prompt_ko.txt` | 완전 고정. KV 캐시 대상 |
| `schema_classify.json` | enum 14개 |
| `schema_extract.json` | `target` × `ask` |
| `schema_polish.json` | `lines[2..4]`, 각 40자 이내 |
| `keyword_rules.yaml` | 1차 분류 + **refuse 게이트** |
| `llama_server.args` | `-fa`, cache q8_0, `--cache-reuse 256`, `--mlock`, `-b 512 -ub 512` |

## 절대 규칙

- **좌표·방위·거리 숫자 필드를 스키마에 넣지 않는다.** 자리가 없으면 환각도 없다.
- `confidence` 필드는 넣지 않는다. 안전 판단에 쓰지 않을 값을 생성하는 것은 지연 낭비다.
- `refuse`는 모델이 아니라 **키워드 게이트가 먼저** 잡는다. "먹/식용/버섯"은 모델에 도달하기 전에 차단한다.
- 경로 B(`lost`/`daylight`/`warmth`/`sleep_safety`/`injury`/`refuse`)는 LLM을 거치지 않는다.
- `temperature = 0` 고정.

`legacy/Gemma 4 E2B/config/`의 구 스키마는 벡터 RAG 전제라 참고만 하고 복사하지 않는다.
구 의료 도메인 라벨 9개(`bleeding` 등)와 SMS 필드 추출은 폐기되었다. 근거는 `docs2/03`, `docs2/05`.
