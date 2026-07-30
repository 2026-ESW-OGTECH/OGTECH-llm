# 1단계 준비: Jetson Xavier NX 초기화와 프로젝트용 초기 세팅

목표: Jetson Xavier NX를 우리 프로젝트의 엣지 추론 장치로 쓰기 위해 **기존 의존성 꼬임을 제거하고, JetPack/CUDA/TensorRT/LLM 런타임을 깨끗한 기준선으로 맞춘다.**

이 문서는 “홈 디렉터리만 정리”가 아니라 **OS/JetPack 재플래시로 사실상 초기화한 뒤 다시 세팅하는 방법**을 기준으로 한다.

## 0. 결론

우리 프로젝트용 장비라면 그냥 밀고 새로 시작하는 편이 낫다.

- 이유: Jetson은 JetPack, CUDA, cuDNN, TensorRT, Python 패키지 버전이 서로 엮여 있어서 예전 설치 흔적이 남으면 원인 추적이 오래 걸린다.
- 기준: Xavier NX는 **JetPack 5.1.x 계열**을 사용한다.
- 2026-07-07 기준 NVIDIA JetPack Archive에는 **JetPack 5.1.6 / L4T 35.6.4**가 Xavier NX series를 지원하는 최신 5.x 계열로 올라와 있다.
- JetPack 6.x/7.x는 Orin/Thor 계열 중심이므로 Xavier NX에 억지로 올리지 않는다.

예상 시간:

| 작업                      | 예상 시간    |
| ------------------------- | ------------ |
| 백업                      | 10~30분      |
| SD 카드 재플래시          | 20~40분      |
| SDK Manager 플래시        | 40분~2시간   |
| 첫 부팅/업데이트/SSH      | 30분~1시간   |
| 개발 도구/LLM 런타임 세팅 | 1~2시간      |
| 모델 다운로드             | 10분~몇 시간 |

문제 없이 가면 2~4시간, USB/복구모드/스토리지 문제가 있으면 반나절까지 잡는다.

## 0.1. 2026-07-08 진행 메모

현재 Jetson Xavier NX는 microSD 재플래시 후 첫 부팅과 기본 세팅을 통과했고, Jetson 안의 프로젝트 기준 폴더는 `~/projects/aidkit`으로 맞췄다.

진행된 작업:

- JetPack 5.1.x 계열 SD 이미지 플래시와 첫 부팅 완료
- 초기 OEM 설정 실패 후 microSD 재플래시로 정상 부팅 확인
- 기본 업데이트와 개발 도구 설치 진행
- SSH/VS Code Remote SSH 기준 경로를 `~/projects/aidkit`으로 정리
- `nvcc --version`, `nvpmodel`, `tegrastats` 계열 확인 진행
- `llama.cpp` 저장소를 `~/projects/llama.cpp`에 준비
- JetPack 기본 CMake 3.16.3이 낮아서 사용자 영역 CMake로 보완
- CMake가 `nvcc`를 못 찾는 문제는 `/usr/local/cuda/bin/nvcc`를 명시하는 방식으로 처리
- 퇴근 전 `cmake --build build --config Release -j 4` 실행 중

아직 완료로 보면 안 되는 것:

- `llama.cpp` CUDA 빌드 성공 여부
- 작은 GGUF 모델 다운로드와 첫 추론
- 추론 중 `tegrastats`로 GPU 사용률과 온도 확인

내일 시작 지점:

```bash
cd ~/projects/llama.cpp
./build/bin/llama-cli --help
./build/bin/llama-server --help
```

위 명령이 동작하면 빌드는 성공한 것이다. 실패했거나 빌드가 중간에 멈췄다면 마지막 에러를 확인하고, 우선 병렬도를 낮춰 다시 빌드한다.

```bash
cmake --build build --config Release -j 2
```

## 1. 버전 전제

| 항목       | 기준                                            | 비고                                       |
| ---------- | ----------------------------------------------- | ------------------------------------------ |
| JetPack    | **5.1.x 계열**                            | Xavier NX 지원 계열                        |
| 권장       | JetPack 5.1.6 또는 NVIDIA가 안내하는 최신 5.1.x | 설치 전 JetPack Archive 확인               |
| L4T        | 35.x                                            | JetPack 5.x 대응                           |
| OS         | Ubuntu 20.04                                    | JetPack 5.x 기본                           |
| Python     | 3.8                                             | JetPack 5.x 기본                           |
| CUDA       | JetPack 동봉 CUDA 11.x                          | 5.1.4/5.1.5/5.1.6 계열은 CUDA 11.4.19 기준 |
| TensorRT   | JetPack 동봉 TensorRT 8.x                       | 비전/추론 가속용                           |
| LLM 런타임 | `llama.cpp` 우선                              | Jetson에서 가장 단순하고 제어하기 쉬움     |

중요한 점은 버전을 외워서 쓰는 것이 아니라 **JetPack, L4T, CUDA, TensorRT, PyTorch/ONNX/TensorRT 패키지를 같은 세대에 맞추는 것**이다.

설치 후 실제 버전은 반드시 `~/projects/aidkit/results/versions.md` 또는 프로젝트의 결과 기록 파일에 남긴다.

## 2. 초기화 전에 백업할 것

Jetson을 재플래시하면 저장장치 내용이 지워진다고 생각한다. 최소한 아래는 따로 빼 둔다.

```bash
mkdir -p ~/backup_before_flash
cp -a ~/projects ~/backup_before_flash/ 2>/dev/null || true
cp -a ~/models ~/backup_before_flash/ 2>/dev/null || true
cp -a ~/.ssh ~/backup_before_flash/ssh 2>/dev/null || true
cp -a ~/.gitconfig ~/backup_before_flash/gitconfig 2>/dev/null || true
cp -a ~/.bashrc ~/backup_before_flash/bashrc 2>/dev/null || true
```

백업 대상:

- 프로젝트 코드
- 직접 받은 GGUF 모델 파일
- 실험 로그와 결과
- `~/.ssh`
- `.env`, API key, 토큰 파일
- Wi-Fi/고정 IP 정보
- 이전에 성공했던 설치 명령 기록

주의:

- API key, 토큰, `.env`는 Git에 올리지 않는다.
- 모델 파일은 크므로 외장 SSD나 PC로 따로 옮기는 편이 낫다.
- 의존성이 꼬였다고 느껴서 초기화하는 것이므로 `site-packages`, `node_modules`, `build` 폴더는 굳이 백업하지 않는다.

## 3. 내 보드가 어떤 초기화 방식인지 확인

Xavier NX는 구성에 따라 초기화 방식이 다르다.

| 구성                                   | 추천 초기화 방식                      |
| -------------------------------------- | ------------------------------------- |
| Xavier NX Developer Kit + microSD 부팅 | SD 카드 이미지 재플래시               |
| eMMC 모듈                              | SDK Manager로 플래시                  |
| NVMe SSD 부팅                          | SDK Manager 또는 SD 부팅 후 NVMe 구성 |
| JetPack 4.x에서 5.x로 처음 넘어감      | QSPI 업데이트 필요 가능성 높음        |

가장 흔한 함정은 **QSPI 업데이트**다. NVIDIA 문서에는 Xavier NX Developer Kit이 JetPack 5.x를 이전에 실행한 적이 없다면 JetPack 5.x SD 카드 이미지를 쓰기 전에 QSPI 업데이트가 필요할 수 있다고 안내되어 있다.

판단이 애매하면 SDK Manager 방식이 더 확실하다.

## 4. 방법 A: microSD 카드 재플래시

Developer Kit에서 microSD로 부팅하는 경우 가장 단순한 방식이다.

준비물:

- 64GB 이상 microSD, 가능하면 128GB 이상
- balenaEtcher 또는 Raspberry Pi Imager
- 안정적인 전원 어댑터
- 모니터/키보드 또는 초기 SSH 접속 방법

절차:

1. PC에서 NVIDIA JetPack Archive에 들어간다.
2. Xavier NX Developer Kit용 JetPack 5.1.x SD 카드 이미지를 받는다.
3. JetPack 5.1.6은 SD 이미지를 직접 새로 제공하지 않고, JetPack 5.1.5/Jetson Linux 35.6.2 SD 이미지에서 APT 업그레이드로 5.1.6에 올리는 흐름일 수 있다. NVIDIA 안내를 우선한다.
4. balenaEtcher로 microSD에 이미지를 굽는다.
5. Jetson 전원을 끄고 기존 microSD를 제거한다.
6. 새로 구운 microSD를 꽂고 부팅한다.
7. 첫 부팅 마법사에서 사용자, 비밀번호, 언어, 네트워크를 설정한다.

QSPI 주의:

- 예전에 JetPack 4.x만 쓰던 보드라면 JetPack 5.x SD 이미지가 바로 부팅되지 않을 수 있다.
- 이 경우 NVIDIA의 Xavier NX QSPI 업데이트 절차를 먼저 수행한다.
- QSPI 업데이트가 부담스러우면 방법 B의 SDK Manager 플래시를 쓴다.

## 5. 방법 B: SDK Manager로 재플래시

eMMC 모듈, NVMe 구성, QSPI까지 확실히 맞추고 싶을 때 권장한다.

준비물:

- Ubuntu 18.04 또는 20.04가 설치된 x86 호스트 PC
- NVIDIA SDK Manager
- Jetson과 호스트 PC를 연결할 USB 케이블
- 안정적인 전원
- HDMI/키보드 또는 네트워크 접속 수단

절차:

1. 호스트 PC에 NVIDIA SDK Manager를 설치한다.
2. Jetson 전원을 끈다.
3. 보드 매뉴얼에 따라 Force Recovery Mode로 진입한다.
4. Jetson을 USB로 호스트 PC에 연결한다.
5. 호스트 PC에서 장치가 보이는지 확인한다.

```bash
lsusb
```

6. SDK Manager를 실행한다.
7. Target Hardware에서 Jetson Xavier NX를 선택한다.
8. JetPack 5.1.x 계열을 선택한다.
9. 처음 세팅이면 OS + Jetson SDK Components 전체 설치를 선택한다.
10. 플래시가 끝나면 Jetson을 재부팅하고 첫 부팅 마법사를 진행한다.

SDK Manager 방식의 장점:

- QSPI/부트로더까지 맞추기 쉽다.
- eMMC/NVMe 구성이 편하다.
- CUDA/cuDNN/TensorRT 구성 누락 가능성이 낮다.

단점:

- Ubuntu 호스트 PC가 필요하다.
- USB 연결/복구모드 인식에서 시간이 걸릴 수 있다.

## 6. 첫 부팅 직후 체크

Jetson에서 아래를 확인한다.

```bash
cat /etc/nv_tegra_release
dpkg-query --show nvidia-jetpack
uname -a
python3 --version
/usr/local/cuda/bin/nvcc --version
```

기록 파일을 만든다.

```bash
mkdir -p ~/projects/aidkit/results
{
  date
  echo
  cat /etc/nv_tegra_release
  echo
  dpkg-query --show nvidia-jetpack
  echo
  uname -a
  echo
  python3 --version
  echo
  /usr/local/cuda/bin/nvcc --version
} | tee ~/projects/aidkit/results/versions.md
```

## 7. 첫 업데이트

재플래시 직후 한 번은 업데이트한다.

```bash
sudo apt update
sudo apt upgrade -y
sudo reboot
```

주의:

- 프로젝트가 안정화된 뒤에는 무작정 `apt upgrade`를 자주 하지 않는다.
- JetPack/CUDA/TensorRT는 보드 전체 런타임 기준선이므로 실험 중간에 바뀌면 결과 비교가 어려워진다.
- 큰 업데이트 전에는 SD 카드 이미지 또는 SSD 스냅샷을 백업한다.

## 8. 기본 개발 도구 설치

재부팅 후 기본 도구를 설치한다.

```bash
sudo apt update
sudo apt install -y \
  git curl wget ca-certificates \
  build-essential cmake ninja-build pkg-config \
  python3-pip python3-venv python3-dev \
  ffmpeg v4l-utils \
  htop tmux nano
```

Jetson 상태 모니터링 도구를 설치한다.

```bash
sudo -H pip3 install -U jetson-stats
sudo reboot
```

재부팅 후:

```bash
jtop
```

`jtop`이 안 되면 최소한 `tegrastats`를 쓴다.

```bash
sudo tegrastats
```

## 9. SSH와 원격 개발 세팅

Jetson에는 무거운 데스크톱 개발 도구를 최대한 깔지 않는다. 메인 PC에서 VS Code Remote SSH로 붙는 구성을 기본으로 한다.

Jetson에서:

```bash
sudo apt install -y openssh-server
sudo systemctl enable ssh
sudo systemctl start ssh
hostname -I
```

원하면 호스트명을 고정한다.

```bash
sudo hostnamectl set-hostname jetson-xavier-nx
sudo reboot
```

메인 PC에서:

```bash
ssh <jetson_user>@<jetson_ip>
```

VS Code에서는:

1. PC에 VS Code 설치
2. Remote - SSH 확장 설치
3. `ssh <jetson_user>@<jetson_ip>`로 접속
4. 프로젝트 폴더는 Jetson의 `~/projects/aidkit`을 연다

권장:

- Codex, Claude Desktop, 무거운 IDE는 PC에서 실행한다.
- Jetson은 추론 서버, 센서 연결, CUDA/TensorRT 실행 장치로 단순하게 유지한다.
- Jetson 안에 Codex/Claude CLI를 꼭 넣어야 할 이유가 생기기 전까지는 설치하지 않는다.

## 10. 전원 모드와 쿨링

Xavier NX는 전원 모드에 따라 추론 속도 차이가 크다.

```bash
sudo nvpmodel -q --verbose
```

목록을 보고 가장 높은 전력/성능 모드를 고른다. 모드 번호는 이미지와 보드 구성에 따라 다를 수 있으므로 문서의 숫자를 그대로 믿지 않는다.

예시:

```bash
sudo nvpmodel -m 0
sudo jetson_clocks
sudo nvpmodel -q
```

부하 중 확인:

```bash
sudo tegrastats
```

확인할 것:

- `GR3D_FREQ`가 올라가는지
- 온도가 과하게 올라가지 않는지
- 쓰로틀링이 보이지 않는지
- 전원 어댑터가 부족하지 않은지

쿨링 기준:

- 액티브 쿨링 팬은 필수다.
- 실제 데모 케이스에 넣은 상태로 온도를 본다.
- 쓰로틀링이 보이면 모델을 줄이기 전에 전원과 쿨링부터 확인한다.

## 11. 스왑 메모리

8GB Xavier NX에서는 모델 로딩 순간 OOM이 날 수 있다. 스왑은 안전망으로 둔다.

microSD만 쓰는 경우:

- 4GB 정도만 권장
- 스왑을 많이 쓰면 SD 수명과 속도에 불리하다

NVMe/SSD를 쓰는 경우:

- 8GB 스왑까지 고려 가능

4GB 스왑 예시:

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile swap swap defaults 0 0' | sudo tee -a /etc/fstab
free -h
```

스왑은 성능 해결책이 아니다. 추론 중 스왑을 계속 크게 쓰면 모델이 크거나 동시에 너무 많이 올린 것이다.

## 12. CUDA/TensorRT 동작 확인

```bash
/usr/local/cuda/bin/nvcc --version
dpkg -l | grep -E 'nvidia-jetpack|cuda|cudnn|nvinfer|tensorrt'
sudo tegrastats
```

확인 기준:

- `nvcc --version`이 JetPack 5.x에 맞는 CUDA 버전을 표시한다.
- `nvidia-jetpack` 패키지가 보인다.
- `nvinfer` 또는 TensorRT 관련 패키지가 보인다.
- `tegrastats`에 `GR3D_FREQ` 항목이 보인다.

Jetson은 일반 PC처럼 `nvidia-smi`가 기본 확인 도구가 아니다. `nvidia-smi`가 없다고 GPU가 없는 것이 아니다.

## 13. 프로젝트 폴더 기준선

Jetson 안의 작업 위치를 고정한다.

```bash
mkdir -p ~/projects/aidkit
mkdir -p ~/models/gguf
mkdir -p ~/runs/logs
cd ~/projects/aidkit
```

Python은 프로젝트별 `venv`로 분리한다.

```bash
cd ~/projects/aidkit
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
```

원칙:

- 시스템 Python에 직접 이것저것 깔지 않는다.
- `sudo pip install`을 남발하지 않는다.
- 프로젝트별로 `.venv`를 만든다.
- 설치 명령은 `setup_notes.md`나 README에 남긴다.

## 14. llama.cpp CUDA 빌드

처음 LLM 테스트는 `llama.cpp`로 간다. Ollama보다 수동 제어가 쉽고, Jetson에서 문제가 생겼을 때 원인 분리가 쉽다.

```bash
cd ~/projects
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j 4
```

빌드 확인:

```bash
./build/bin/llama-cli --help
./build/bin/llama-server --help
```

만약 빌드 중 메모리 부족이 나면:

```bash
cmake --build build --config Release -j 2
```

그래도 안 되면 스왑과 온도, 저장공간을 먼저 확인한다.

## 15. 작은 GGUF 모델로 첫 추론 테스트

처음부터 큰 모델을 올리지 않는다.

권장 시작점:

- 1B~3B급 instruct 모델
- Q4_K_M 또는 Q5_K_M GGUF
- 컨텍스트는 작게 시작

모델 위치:

```bash
mkdir -p ~/models/gguf
```

실행 예시:

```bash
cd ~/projects/llama.cpp
./build/bin/llama-cli \
  -m ~/models/gguf/model.gguf \
  -p "You are running on Jetson Xavier NX. Say hello in one sentence." \
  -n 64 \
  -ngl 20
```

서버 실행 예시:

```bash
cd ~/projects/llama.cpp
./build/bin/llama-server \
  -m ~/models/gguf/model.gguf \
  --host 0.0.0.0 \
  --port 8080 \
  -ngl 20
```

PC에서 확인:

```bash
curl http://<jetson_ip>:8080/health
```

모델이 너무 크면:

- `-ngl` 값을 낮춘다.
- 더 작은 모델로 바꾼다.
- Q4 계열 양자화 모델로 바꾼다.
- 동시에 실행 중인 프로세스를 줄인다.

## 16. Docker는 언제 쓸지

초기 검증은 native 빌드가 단순하다. 단, 프로젝트가 굳어지면 Docker로 고정하는 편이 좋다.

Docker를 쓰는 이유:

- 의존성 재현성이 좋아진다.
- 컨테이너만 지우면 앱 환경을 다시 만들 수 있다.
- Jetson OS/JetPack은 깨끗하게 유지할 수 있다.

JetPack에는 NVIDIA Container Runtime과 Docker 연동이 포함된다. 먼저 아래를 확인한다.

```bash
docker --version
dpkg -l | grep nvidia-container
```

Docker가 아직 익숙하지 않으면 이 순서로 간다.

1. JetPack/CUDA 정상 확인
2. native `llama.cpp` 빌드 성공
3. 작은 모델 추론 성공
4. 프로젝트 의존성 목록 확정
5. Dockerfile로 고정

## 17. 설치 후 절대 피할 것

- JetPack 6.x/7.x를 Xavier NX에 억지로 설치
- 시스템 Python에 `sudo pip install` 남발
- CUDA만 따로 최신으로 올리고 TensorRT/PyTorch는 그대로 두기
- 모델, 서버, 비전, STT를 한 번에 다 설치
- 추론 성능 보기 전에 전원 모드와 쿨링을 무시
- 성공한 상태의 버전 기록 없이 계속 업데이트

## 18. 인수 기준

초기화와 기본 세팅이 끝났다고 보는 기준:

- [X] JetPack 5.1.x / L4T 35.x 계열 설치
- [X] 첫 부팅과 네트워크 설정 완료
- [X] SSH 접속 가능
- [X] VS Code Remote SSH 접속 가능
- [X] `nvidia-jetpack` 패키지 확인
- [X] `nvcc --version` 확인
- [ ] TensorRT 관련 패키지 확인
- [X] `tegrastats`에서 `GR3D_FREQ` 확인
- [X] `nvpmodel` 최대 성능 모드 적용
- [X] `jetson_clocks` 적용
- [ ] 스왑 표시 확인
- [X] `jtop` 또는 `tegrastats`로 온도 확인
- [ ] `llama.cpp` CUDA 빌드 성공
- [ ] 작은 GGUF 모델 추론 성공
- [ ] 실제 버전을 `results/versions.md`에 기록

## 19. 참고 링크

- NVIDIA JetPack Archive: https://developer.nvidia.com/embedded/jetpack-archive
- NVIDIA JetPack 5.1.6: https://developer.nvidia.com/embedded/jetpack-sdk-516
- NVIDIA JetPack 5.1.4: https://developer.nvidia.com/embedded/jetpack-sdk-514
- llama.cpp build guide: https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md

통과하면 `02_공통_환경.md`로 넘어간다.
