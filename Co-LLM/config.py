# -*- coding: utf-8 -*-
"""Co-LLM 음성 배관 테스트 설정.

엔진을 바꾸는 곳은 이 파일 한 곳뿐입니다.
STT_ENGINE / TTS_ENGINE 두 줄만 고치고 scripts/voice_loop.py 를 다시 실행합니다.

경로에 ~ 를 써도 됩니다. 아래 _p() 가 펼쳐 줍니다.
"""

import os
from pathlib import Path


def _p(path_str):
    return str(Path(os.path.expanduser(path_str)))


# 출력물은 전부 scripts/test_rec/ 안에 남습니다.
# scripts 폴더만 젯슨으로 옮겨도 그 안에서 완결되도록 한 것입니다.
CO_LLM_DIR = Path(__file__).resolve().parent
RESULT_DIR = CO_LLM_DIR / "scripts" / "test_rec"
SAMPLE_DIR = RESULT_DIR


# =============================================================
# 1. 오디오 장치
#    scripts/00_check_audio.sh 가 찍어 준 이름을 그대로 넣습니다.
#    hw: 가 아니라 plughw: 를 씁니다 (리샘플링 자동).
#    카드 번호(hw:1,0)는 USB 꽂는 순서에 따라 바뀌므로 쓰지 않습니다.
# =============================================================
MIC_DEVICE = "plughw:CARD=Device,DEV=0"      # Adafruit 3367 Mini USB Microphone
SPK_DEVICE = "plughw:CARD=Device_1,DEV=0"    # Adafruit 3369 Mini USB Stereo Speaker

REC_SECONDS = 5          # 한 번에 녹음할 초. --seconds 로 덮어쓸 수 있습니다
REC_RATE = 16000         # STT 3안 모두 16 kHz 를 요구합니다. 바꾸지 마세요
REC_CHANNELS = 1


# =============================================================
# 2. 엔진 선택  <-- 테스트할 때 고치는 곳은 여기 두 줄입니다
# =============================================================
STT_ENGINE = "whisper_cpp"    # whisper_cpp | sherpa_onnx | faster_whisper
TTS_ENGINE = "espeak"         # espeak | piper | melotts


# =============================================================
# 3. STT 설정
# =============================================================

# --- 1안: whisper.cpp -----------------------------------------
# 구버전은 바이너리 이름이 whisper-cli 가 아니라 main 입니다.
WHISPER_CPP_BIN = _p("~/safeaid_ai/stt/whisper.cpp/build/bin/whisper-cli")
# small 이 아니라 base 입니다. 1,494 ms vs 3,468 ms `[실측]` 이고 경로 B 예산이
# 2.0초입니다. 모델 확정은 미결 #8 — 21문장 벤치가 닫습니다.
WHISPER_CPP_MODEL = _p("~/safeaid_ai/stt/whisper.cpp/models/ggml-base.bin")
WHISPER_CPP_THREADS = 6      # 4 -> 6 은 -9% `[실측]`. nproc 6 이 상한
WHISPER_CPP_LANG = "ko"

# AGENTS.md 5절에서 동결된 플래그입니다. 튜닝 손잡이가 아닙니다.
#   -ac 450  30초 멜 윈도 패딩이 지연의 81%. 16,933 -> 1,494 ms `[실측]`
#            300 으로 내리면 환각과 12.6초 폭주 `[실측]`
#   -bo 1 -bs 1  beam 은 +33% 지연에 출력 변화 0 `[실측]`
# -ng(GPU 미사용)는 설정이 아니라 고정이므로 engines.py 안에 박아 둡니다.
WHISPER_CPP_FLAGS = ["-ac", "450", "-bo", "1", "-bs", "1", "-nf"]

# 초기 프롬프트(컨텍스트 바이어싱)의 정본은 scripts/stt_prompt.txt 한 곳입니다.
# 셸 스크립트(03/06)와 이 파이썬 경로가 같은 파일을 읽으므로 사본이 갈라지지 않습니다.
# 환경변수 WHISPER_PROMPT 가 있으면 그쪽이 이깁니다(빈 문자열 = 프롬프트 끄기).
STT_PROMPT_FILE = Path(os.environ.get(
    "WHISPER_PROMPT_FILE", str(CO_LLM_DIR / "scripts" / "stt_prompt.txt")))
if not STT_PROMPT_FILE.is_absolute() and not STT_PROMPT_FILE.exists():
    STT_PROMPT_FILE = CO_LLM_DIR / "scripts" / STT_PROMPT_FILE.name


def _read_prompt(path):
    """'#' 주석과 빈 줄을 버리고 나머지 줄을 공백으로 이어 한 줄로 만듭니다."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""
    out = []
    for line in raw.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return " ".join(out)


_env_prompt = os.environ.get("WHISPER_PROMPT")
WHISPER_CPP_PROMPT = (
    _env_prompt if _env_prompt is not None else _read_prompt(STT_PROMPT_FILE)
)

# --- 2안: sherpa-onnx 한국어 zipformer (오프라인) ---------------
# 압축을 푼 뒤 실제 파일명을 확인해서 맞추세요. epoch/avg 숫자가 다를 수 있습니다.
SHERPA_DIR = _p("~/safeaid_ai/stt/sherpa-onnx-zipformer-korean-2024-06-24")
SHERPA_ENCODER = "encoder-epoch-99-avg-1.int8.onnx"
SHERPA_DECODER = "decoder-epoch-99-avg-1.onnx"
SHERPA_JOINER = "joiner-epoch-99-avg-1.int8.onnx"
SHERPA_TOKENS = "tokens.txt"
SHERPA_THREADS = 4

# --- 3안: faster-whisper ---------------------------------------
FW_MODEL = "small"       # tiny | base | small | medium
FW_DEVICE = "cuda"       # cuda 가 죽으면 cpu
FW_COMPUTE = "float16"   # cpu 일 때는 int8
FW_BEAM = 1              # 기본값 5 는 느립니다


# =============================================================
# 4. TTS 설정
# =============================================================

# --- 1안: espeak-ng --------------------------------------------
ESPEAK_BIN = "espeak-ng"
ESPEAK_VOICE = "ko"
ESPEAK_SPEED = 150       # 130~170. 야외에서는 느린 쪽이 알아듣기 쉽습니다

# --- 2안: piper ------------------------------------------------
PIPER_BIN = "piper"
PIPER_MODEL = _p("~/safeaid_ai/tts/piper/ko.onnx")

# --- 3안: MeloTTS-Korean ---------------------------------------
MELO_LANGUAGE = "KR"
MELO_DEVICE = "cpu"      # "cuda:0" 로 바꿔 비교해 보세요
MELO_SPEED = 1.0


# =============================================================
# 5. LLM (경로 A 에서만 사용)
#    llama-server 직결입니다. 제품의 backend(8765) 가 아닙니다.
# =============================================================
LLM_URL = "http://127.0.0.1:8080/v1/chat/completions"
LLM_MODEL = "qwen2.5-1.5b-instruct"
LLM_MAX_TOKENS = 96      # AGENTS.md 카드 다듬기 출력 한도
LLM_TEMPERATURE = 0.0    # 재현성. 취향이 아닙니다
LLM_TIMEOUT_S = 5.0

# 시연용 시스템 프롬프트입니다. 제품 응답 경로(검수된 고정 카드)가 아니라
# 경로 A 다듬기 대역이며, 안전 계약(방위/거리/좌표/진단/식용 금지)을 그대로 겁니다.
#
# "반드시 완결된 문장" 조항이 취향이 아닌 이유: 출력이 화면이 아니라 TTS 로 갑니다.
# 불릿·번호·괄호·기호는 espeak-ng 가 읽지 못하거나 기호 이름을 읽어 버립니다.
# 길이 제한도 같은 이유입니다 — 96 토큰이 AGENTS.md 4절의 카드 다듬기 한도입니다.
#
# 숫자를 금지어로 못 박은 것은 안전 계약 1번입니다. 방위·거리는 지도 엔진이
# 계산하고 LLM 은 읽어 주기만 합니다. 스키마에 자리가 없으면 환각도 없습니다.
LLM_SYSTEM = (
    "당신은 오지 생존 보조 장치의 음성 안내입니다. "
    "답변은 반드시 완결된 한국어 문장으로만 씁니다. "
    "단어 나열, 목록, 번호 매기기, 불릿, 표, 이모지, 괄호 설명을 쓰지 않습니다. "
    "2~4문장으로, 한 문장은 40자 이내로 짧게 말합니다. "
    "말하듯이 씁니다. 소리 내어 읽었을 때 어색한 표현은 쓰지 않습니다. "
    "방위, 거리, 좌표, 경로, 소요 시간은 절대 말하지 않습니다. "
    "진단, 약물, 야생 동식물의 식용 가능 여부는 답하지 않습니다. "
    "확실하지 않으면 모른다고 한 문장으로 말합니다."
)


# =============================================================
# 6. 경로 B 고정 문장
#    실제 제품에서는 검수된 고정 카드가 들어옵니다.
#    여기서는 TTS 지연만 재기 위한 대역입니다.
# =============================================================
PATH_B_SENTENCE = "해가 지기까지 40분 남았습니다. 지금 돌아서세요."


# =============================================================
# 7. 예산 (AGENTS.md)
# =============================================================
BUDGET_PATH_B_S = 2.0    # 경로 B: 키워드 게이트 -> 고정 카드 -> TTS
BUDGET_PATH_A_S = 3.5    # 경로 A: 분류 -> 카드 -> LLM -> 스트리밍 TTS
MEM_GATE_MB = 1024       # MemAvailable 게이트
