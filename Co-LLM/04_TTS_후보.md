# 04. TTS 후보 3안

`AGENTS.md` 미결 항목 #2(**한국어 TTS 엔진 확정, 기한 W1**)를 닫기 위한 실험입니다.
여기서 나온 숫자로 `AGENTS.md`를 고칩니다.

## 이 프로젝트에서 TTS가 만족해야 하는 조건

화면이 기본 OFF이므로 **음성이 1차 출력**입니다. 그래서 판정 기준이 일반 TTS와 다릅니다.

1. **첫 소리까지의 지연** — 전체 합성 시간이 아닙니다. 경로 A는 문장 단위 스트리밍이므로
   첫 문장만 빨리 나오면 됩니다
2. **메모리 0.5~1.5 GB** — `AGENTS.md` TTS 온디맨드 예산. LLM 상주 1.4 GB와 겹치면 안 됩니다
3. **완전 오프라인** — 실행 시 네트워크를 건드리면 탈락입니다 (안전 계약 9)
4. **바람·빗소리 속에서 알아들리는가** — 자연스러움보다 **명료도**가 우선입니다.
   이건 스펙이 아니라 실제로 들어 봐야 압니다

| | 1안 espeak-ng | 2안 Piper | 3안 MeloTTS-KR |
|---|---|---|---|
| 역할 | **기준선·폴백** | **균형** | **자연스러움** |
| 방식 | 포먼트 합성 | VITS(ONNX) | VITS + 형태소 분석 |
| 모델 크기 | ~수 MB | ~63 MB [추정] | ~수백 MB [추정] |
| 첫 소리 [추정] | ~0.05 s | ~0.2 s | ~1 s |
| 메모리 [추정] | 무시 가능 | ~0.2 GB | ~1.0~1.5 GB |
| 음질 | 로봇 소리 | 양호 | **가장 자연스러움** |
| 한국어 지원 | 공식 | **비공식 커뮤니티 모델** | **공식** |
| 실행 | CLI | CLI | Python 인프로세스 |
| 언로드 | 자동 | 자동 | 명시적 `del`+`gc` |
| aarch64 리스크 | 없음 | 낮음 | **중간** (mecab-ko 빌드) |

---

## 1안 — espeak-ng (기준선이자 최종 폴백)

**음질 때문에 넣은 게 아닙니다.** 두 가지 역할이 있습니다.

- **지연 하한선**: 합성 시간이 거의 0이므로, espeak로 측정한 총 지연이 곧
  "STT + 재생 + 오버헤드"입니다. 다른 TTS를 넣었을 때 늘어난 만큼이 그 TTS의 비용입니다
- **최종 폴백**: 다른 엔진이 죽어도 이건 삽니다. 안전 계약 2번(생명 관련 응답은 반드시 나가야 함)의
  마지막 방어선입니다

```bash
sudo apt install -y espeak-ng
espeak-ng --voices | grep -i ko
espeak-ng -v ko -s 150 -w /tmp/t.wav --stdin <<'EOF'
해가 지기까지 40분 남았습니다. 지금 돌아서세요.
EOF
aplay -D plughw:CARD=Device_1,DEV=0 /tmp/t.wav
```

`config.py`:

```python
TTS_ENGINE = "espeak"
ESPEAK_VOICE = "ko"
ESPEAK_SPEED = 150      # 130~170. 야외에서는 느린 편이 알아듣기 쉽습니다
```

**속도를 꼭 조정해 보세요.** 기본 175는 한국어에서 빠릅니다. 130~150이 명료합니다 [추정].

---

## 2안 — Piper + 한국어 ONNX 모델 (균형)

단일 ONNX 파일 + 단일 바이너리라 배포가 가장 깔끔하고, `--output-raw`로
**문장 단위 스트리밍 재생**이 쉽습니다. 경로 A 설계와 잘 맞습니다.

### 먼저 알아야 할 리스크

**Piper 공식 음성 목록에 한국어가 없습니다** [출처: rhasspy/piper `VOICES.md`, 한국어 지원 요청 이슈 #680].
쓰려면 커뮤니티 모델을 가져와야 합니다.

- 후보: Hugging Face `neurlang/piper-onnx-kss-korean` [출처]
- 학습 데이터는 **KSS(Korean Single Speaker Speech)**로 보입니다. **라이선스를 반드시 확인하세요.**
  KSS 계열은 비상업 조건(CC BY-NC-SA)이 붙는 경우가 있습니다 [미검증].
  우리 저장소는 공개 GitHub이고 대회 제출물이므로, **라이선스 확인 전에는 모델 파일을 커밋하지 마세요.**
- 품질은 공식 음성과 다를 수 있습니다 [미검증]. 반드시 직접 들어 보고 판정합니다

### 설치

```bash
source ~/safeaid_ai/venv/bin/activate
pip install piper-tts

mkdir -p ~/safeaid_ai/tts/piper && cd ~/safeaid_ai/tts/piper
# 네트워크가 되는 머신에서 받아 Jetson으로 복사해도 됩니다
# ko.onnx 와 ko.onnx.json 두 파일이 한 쌍입니다
```

동작 확인:

```bash
echo "해가 지기까지 40분 남았습니다." | \
  piper --model ~/safeaid_ai/tts/piper/ko.onnx --output_file /tmp/piper.wav
aplay -D plughw:CARD=Device_1,DEV=0 /tmp/piper.wav
```

`--output_file` 옵션명이 버전에 따라 `--output-file`로 바뀝니다.
`voice_loop.py`는 둘 다 시도하므로 신경 쓰지 않아도 됩니다.

### 교체

```python
TTS_ENGINE = "piper"
PIPER_MODEL = "~/safeaid_ai/tts/piper/ko.onnx"
```

---

## 3안 — MeloTTS-Korean (자연스러움)

MyShell의 MeloTTS는 **한국어를 공식 지원**하고 MIT 라이선스입니다. 세 후보 중 가장 자연스럽습니다.
대신 설치가 가장 까다롭습니다.

### 설치 — 순서를 지키세요

```bash
source ~/safeaid_ai/venv/bin/activate
cd ~/safeaid_ai/tts
git clone https://github.com/myshell-ai/MeloTTS.git
cd MeloTTS
pip install -e .
python -m unidic download
```

한국어 g2p에 형태소 분석기가 필요합니다.

```bash
pip install python-mecab-ko g2pkk
```

> **알려진 충돌**: `mecab-python3`와 `python-mecab-ko`를 같이 설치하면
> `AttributeError`가 납니다 ([myshell-ai/MeloTTS#121](https://github.com/myshell-ai/MeloTTS/issues/121)) [출처].
> 이미 깔려 있으면 `pip uninstall mecab-python3` 후 `python-mecab-ko`를 다시 설치하세요.
> aarch64에서 mecab 빌드가 실패하면 `sudo apt install -y libmecab-dev mecab` 후 재시도합니다.

동작 확인:

```python
from melo.api import TTS
m = TTS(language="KR", device="cpu")     # 되면 "cuda:0"으로 재시도
spk = m.hps.data.spk2id
m.tts_to_file("해가 지기까지 40분 남았습니다.", spk["KR"], "/tmp/melo.wav", speed=1.0)
```

### 교체

```python
TTS_ENGINE = "melotts"
MELO_DEVICE = "cpu"      # "cuda:0" 로 바꿔 비교해 보세요
MELO_SPEED = 1.0
```

### 알려진 함정

- **첫 호출이 매우 느립니다** (모델 + BERT + 사전 로드). 반드시 **웜 런**으로 측정하세요.
- 메모리가 1.5 GB 예산 상단입니다. `MemAvailable`이 1 GB 아래로 내려가면
  LLM 상주와 공존할 수 없습니다. 그 경우 2안으로 내려갑니다.
- 첫 실행 시 사전·모델을 내려받습니다. **오프라인 최종 데모 전에 캐시를 미리 채워 두세요.**

---

## Kokoro-82M에 대해 — 확인이 필요합니다

`AGENTS.md` 미결 항목 #2는 후보로 `MeloTTS-Korean / Kokoro-82M / espeak-ng`를 적어 두었습니다.
그런데 **Kokoro-82M v1.0의 공식 `lang_code` 목록에 한국어가 있는지 확인되지 않았습니다** [미검증].
2차 출처마다 설명이 엇갈립니다.

먼저 이 한 줄로 확인하세요.

```bash
python -c "from kokoro import KPipeline; KPipeline(lang_code='k')" 2>&1 | tail -5
```

- 한국어 코드가 없다면 → **후보에서 빼고** `AGENTS.md` 미결 항목 #2를 고칩니다.
  그 자리에 Piper(한국어 커뮤니티 모델)를 넣습니다
- 있다면 → 4번째 후보로 같은 방식으로 측정합니다

이 문서가 Piper를 2안으로 올린 이유가 이것입니다. **한국어가 확실한 후보를 3개 확보해야 합니다.**

---

## 판정 순서

```
1. espeak-ng 로 배관을 뚫고 지연 하한선을 잡는다      <- 여기부터
2. Piper 로 바꿔서 "지연이 얼마나 늘었나 / 알아들을 만한가"를 본다
3. 시간이 남으면 MeloTTS 로 바꿔서 "메모리를 감당할 수 있나"를 본다
4. 셋 다 들어 보고 -- 스펙이 아니라 귀로 -- 고른다
```

명료도 평가는 조용한 방에서 하지 마세요. **스피커를 배낭에 넣고 1 m 떨어져서**,
가능하면 선풍기를 틀고 들어 보세요. 실제 사용 조건입니다.

## 기록할 것

[`05_테스트_기록표.md`](05_테스트_기록표.md)의 TTS 표를 채웁니다.
지연 숫자와 함께 **"알아들었는가"를 5점으로** 꼭 적으세요. 이 항목이 최종 결정을 좌우합니다.
