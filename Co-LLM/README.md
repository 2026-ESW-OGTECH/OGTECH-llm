# Co-LLM — 마이크 → LLM → 스피커 배관 테스트

목적은 하나입니다. **"말을 걸면 소리로 답이 온다"가 Xavier NX에서 실제로 되는지**를
가장 적은 단계로 확인하고, 각 단계가 몇 초 걸리는지 숫자로 남깁니다.

이 폴더는 **벤치 테스트용**입니다. 제품 응답 경로(경로 A/B, 고정 카드, 키워드 게이트)가 아닙니다.
제품 경로는 `smartaid-backend`가 담당합니다. 여기서 확인하는 것은 **오디오 배관과 지연 예산**뿐입니다.

---

## 부품 확인 결과 — I2S가 아니라 USB입니다

| 역할 | 구매한 부품 | 인터페이스 | 근거 |
|---|---|---|---|
| 마이크 | **Adafruit 3367** Mini USB Microphone | **USB 오디오** (드라이버 불필요) | [출처] 디바이스마트 상품번호 15835432 / adafruit.com/product/3367 |
| 스피커 | **Adafruit 3369** Mini External USB Stereo Speaker | **USB 오디오** 2×2 W | [출처] 디바이스마트 상품번호 15547280 / adafruit.com/product/3369 |

둘 다 USB Audio Class 장치라서 **디바이스 트리 오버레이도, I2S 배선도 필요 없습니다.**
꽂으면 ALSA 카드로 바로 잡힙니다. 지금 하려는 테스트에는 이게 최선입니다 — 배관을 뚫는 데
반나절짜리 device tree 작업이 끼어들지 않습니다.

> 다만 이건 최종 부품이 **아닙니다.** `AGENTS.md` 고정 하드웨어 표는 INMP441(I2S) + MAX98357A(I2S)입니다.
> IP67 외함에 USB 커넥터 2개를 관통시키는 건 방수 부담이고, USB 오디오는 항상 5 V 버스를 물고 있습니다.
> **소프트웨어 파이프라인을 USB로 먼저 확정하고, I2S 전환은 ALSA 장치 이름만 바꾸는 작업으로 남깁니다.**
> 자세한 판단은 [`01_하드웨어_확인.md`](01_하드웨어_확인.md).

---

## 가장 간단하게 확인하는 방법 — 3단 사다리

한 번에 다 하려다 어디서 막혔는지 모르게 되는 게 이 테스트의 유일한 실패 모드입니다.
**아래 순서를 건너뛰지 마세요.** 각 단이 통과해야 다음 단으로 갑니다.

```
0단  루프백      : 녹음 -> 재생.  LLM/STT/TTS 아무것도 없이 소리만 왕복    (5분)
1단  배관        : 마이크 -> STT -> [고정 문장] -> TTS -> 스피커           (30분)
                   LLM을 건너뜁니다. 경로 B 예산(<= 2.0s)이 여기서 나옵니다
2단  전체        : 마이크 -> STT -> llama-server -> TTS -> 스피커          (30분)
                   경로 A 예산(<= 3.5s)이 여기서 나옵니다
```

0단에서 소리가 안 나면 STT·TTS·LLM은 손대지 마세요. 100% 오디오 장치 문제입니다.

### 0단 — 지금 당장 (5분)

Jetson에 마이크·스피커를 꽂고:

```bash
bash scripts/00_check_audio.sh
```

장치 이름이 출력되고, 5초 녹음 후 그 소리가 스피커로 되돌아 나오면 0단 통과입니다.

---

## 추천 엔진 — 각각 3안, 교체는 한 줄

| 순위 | STT | TTS |
|---|---|---|
| **1안 (먼저)** | `whisper.cpp` + `ggml-small` (CUDA) | `espeak-ng` (ko) |
| **2안** | `sherpa-onnx` 한국어 zipformer (streaming, int8) | `piper` + 한국어 ONNX |
| **3안** | `faster-whisper` small int8_float16 (CUDA) | `MeloTTS-Korean` |

1안은 **품질이 아니라 "확실히 설치된다"** 기준으로 골랐습니다. 배관부터 뚫고,
숫자를 본 다음 2안·3안으로 갈아탑니다. 갈아타는 방법은 [`config.py`](config.py) 두 줄입니다.

```python
STT_ENGINE = "whisper_cpp"   # whisper_cpp | sherpa_onnx | faster_whisper
TTS_ENGINE = "espeak"        # espeak | piper | melotts
```

선정 근거·설치법·각 안의 리스크는 [`03_STT_후보.md`](03_STT_후보.md)와 [`04_TTS_후보.md`](04_TTS_후보.md)에 있습니다.

---

## 문서 순서

| 파일 | 언제 봅니까 |
|---|---|
| [`01_하드웨어_확인.md`](01_하드웨어_확인.md) | 부품을 꽂기 전. 전원·장치 이름·I2S 전환 판단 |
| [`02_설치_A_to_Z.md`](02_설치_A_to_Z.md) | **본문.** 0단부터 2단까지 전 과정 |
| [`03_STT_후보.md`](03_STT_후보.md) | STT를 바꿀 때 |
| [`04_TTS_후보.md`](04_TTS_후보.md) | TTS를 바꿀 때 |
| [`05_테스트_기록표.md`](05_테스트_기록표.md) | 테스트 후. **이 양식을 채워서 알려 주세요** |

## 파일

```
Co-LLM/
├── config.py                  <- 엔진 교체는 여기 한 곳 (voice_loop.py 전용)
└── scripts/                   <- 이 폴더만 옮겨도 00~03 은 동작합니다
    ├── 00_check_audio.sh      루프백 (마이크+스피커 동시 필요)
    ├── 01_record.sh           녹음 전용   — 마이크만
    ├── 03_echo.sh             STT -> TTS  — 오디오 장치 불필요
    ├── 02_play.sh             재생 전용   — 스피커만
    ├── engines.py             STT/TTS 어댑터
    ├── voice_loop.py          전체 파이프라인 + 지연 측정 (config.py 필요)
    └── test_rec/              산출물 (자동 생성, .gitignore 됨)
```

USB 포트가 부족하면 `01 -> 03 -> 02` 순으로 나눠서 돌립니다.
`03_echo.sh`는 오디오 장치를 아예 건드리지 않아서 아무것도 안 꽂은 상태로 실행됩니다.

---

## 안전 계약과의 관계

- 이 벤치의 LLM 프롬프트는 **제품 응답 경로가 아닙니다.** 실제 제품에서 생명 관련 라벨
  (`lost/daylight/warmth/sleep_safety/injury/refuse`)은 LLM을 거치지 않고 고정 카드로 갑니다.
- 그래도 벤치 프롬프트에 **방위·거리·좌표를 말하지 말 것**을 넣어 두었습니다. 습관이 남으면 곤란합니다.
- `temperature = 0` 고정입니다.
- **STT와 TTS를 동시에 메모리에 올리지 않습니다.** `voice_loop.py`가 단계마다 로드/언로드하고
  `MemAvailable`을 같이 찍습니다.
- 녹음된 음성 wav와 측정 CSV는 `scripts/test_rec/`에 남습니다.
  `.gitignore`로 막아 두었습니다 — 커밋되지 않습니다.
