# SafeAid Kit LLM

SafeAid Kit의 제한형 온디바이스 LLM 하네스·평가·측정·지도 검증 자산을 관리하는 저장소입니다.

## 구현 상태

현재 저장소는 오지 생존 도메인 전환 중입니다. P0 하네스·평가 구현 상태는 [조직 PLAN](https://github.com/SmartAid-Kit/.github/blob/main/PLAN.md)과 저장소 이슈를 기준으로 확인합니다.

## 범위

- 시나리오 분류, 질의 대상 추출, 카드 문장 다듬기
- JSON Schema 제약과 코드 검증
- 실패·지연 시 재시도 없는 고정 카드 폴백
- 오프라인 지도 변환·경로 계산 검증 앱: [`MAP/`](MAP/README.md)

LLM은 경로·방위·거리·진단·처치·식용 판정을 생성하지 않습니다.

## 문서 경계

- `docs2/`: 현재 도메인의 공개 조사·계산 근거
- `docs/`: 이전 도메인 아카이브이며 현재 설계 근거가 아님
- `MAP/`: OSM 파생 샘플과 DEMO 좌표만 사용하는 지도 검증 앱

실제 GPS 트랙과 내부 검토 자료는 커밋하지 않습니다. MAP 샘플 지도 출처는 [`MAP/sample_data/ATTRIBUTION.md`](MAP/sample_data/ATTRIBUTION.md)를 따릅니다.

## 검증

```bash
cd MAP
python -B -m unittest discover -s tests -v
```

의존성이 준비되지 않아 실행하지 못한 테스트는 통과로 간주하지 않습니다.
