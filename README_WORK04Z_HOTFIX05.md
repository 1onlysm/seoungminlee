# NAVI OPTIONS LAB — WORK 04-Z HOTFIX 05

## 기준과 범위

- 원격 기준 브랜치: `work04z-hotfix04-galaxy-ui-final-polish`
- 기준 전체 SHA: `bc60c2078b1d4b536efb9c94feacf67482ac67d1`
- 대상 브랜치: `work04z-hotfix05-data-binding-integrity`
- 원본: WORK 04-R NVDA 오프라인 snapshot, 해시 `85f6660ac4a07da061f7d2eb50080dcb40ed6203618710feb017edc55ef3d5ce`
- 작업 범위: 행사가 라벨 정밀도, stale tooltip 제거, tooltip 범위/행사가별 만기 수 표시

## 확인된 $158 불일치 원인

보존 원본과 `contracts.csv`를 다시 계산했습니다. 화면의 두 값 묶음은 같은 행사가의 다른 집계 결과가 아니었습니다.

| 스크린샷 값 | 원본 위치 | 관측값 (콜 거래량 / 풋 거래량 / 콜 OI / 풋 OI) | 실제 만기 수 |
|---|---|---:|---:|
| 선택 카드가 `$158`로 표시 | `2026-11-18`, 실제 행사가 `$157.50` | 11,767 / 10,824 / 1,074 / 5,337 | 1 |
| 툴팁의 `$158` | 전체 원본의 실제 `$158.00`, `2026-12-18` | 815 / 755 / 1,392 / 6,755 | 1 |

코드에서 확인한 문제는 세 가지입니다.

1. 일반 숫자 formatter가 행사가에도 소수점 0자리 규칙을 사용해 `$157.50`과 `$158.00`을 모두 `$158`로 표시했습니다.
2. tooltip DOM은 SVG 바깥에 있고 재렌더 전에 숨기지 않아 만기 변경 후 이전 범위 tooltip이 남을 수 있었습니다. 스크린샷 tooltip 값은 전체 데이터의 `$158.00` 원본 값과 일치하므로 stale tooltip 가설을 강하게 뒷받침합니다. 실제 Galaxy 조작 순서는 브라우저에서 재현하지 못했으므로 화면 사건의 발생 경로 자체는 미검증입니다.
3. 전체 만기 차트의 행마다 대상 만기 수 24를 그대로 넣어 “포함 만기 수”처럼 표시했습니다. 실제 `$158.00` 행사가 데이터는 2026-12-18 한 만기에만 있습니다.

## 최소 수정

- 행사가 전용 formatter를 추가해 실제 소수 행사가를 최대 2자리까지 구분합니다. 관측값, 집계값, 결측 처리에는 손대지 않았습니다.
- Volume/OI 차트를 다시 그리기 전 양쪽 tooltip을 숨겨 이전 만기·범위 정보가 남지 않게 했습니다.
- tooltip에 집계 범위와 해당 실제 행사가가 관측된 만기 수를 표시합니다. 전체 만기 대상 수와 그 행사가가 실제 나타난 만기 수를 분리했습니다.
- 전체 범위 요약 bin tooltip은 “요약 구간” 및 구간 내 실제 행사가 수를 표시합니다.

## 데이터 및 coverage 감사

- 원본 JSON: 2,212 rows (`totalRecord=2,212`), 옵션 계약 CSV: 2,188 rows
- 고유 행사가 444개, 만기 24개
- `2026-11-18`: 계약 행 90개, 실제 행사가 90개
- Call Volume 85/90, Put Volume 73/90, Call OI 85/90, Put OI 73/90. 네 필드는 원본 필드별로 독립 계산했고 동일한 수치는 원본에서 각각 재현됐습니다.
- 집계 합계: Call Volume 297,644; Put Volume 232,846; Call OI 171,626; Put OI 143,622
- 결측은 관측값으로 세지 않았고 숫자 0과 구분했습니다.
- 전체 원본 SHA-256은 기대값과 일치합니다. 원본은 수정하지 않았습니다.

세부 수치와 lineage는 `audit_reports/work04z_hotfix05_data_binding_audit.json`에 기록합니다.

## 검증

- 기준 테스트: 41/41 통과
- 수정 후 테스트: 43/43 통과 (`python -m unittest discover -s tests -v`)
- Python 문법 검사: 통과
- 생성 HTML inline JavaScript `node --check`: 통과
- HTML 및 데이터 검증 산출: 통과
- 실제 브라우저 렌더링: 미검증
- Galaxy 실기기: `DEVICE_PENDING`

실제 Galaxy 검증은 `audit_reports/work04z_hotfix05_galaxy_checklist.md`의 순서를 사용합니다. HTML은 수정 코드에서 보존된 실제 snapshot으로 재생성했습니다.

## 안전

- Nasdaq/Tiingo/기타 시장 API 요청: 0
- GitHub Actions 실행: 0
- `main` 변경: 0
- 신규 제공자: 0
- APK 변경/빌드: 0
- 원본 snapshot 변경: 0

## 판정

`DATA_BINDING_INTEGRITY_READY_DEVICE_PENDING`

코드·원본 재계산 및 오프라인 회귀는 통과했습니다. 사용자 Galaxy에서의 최종 상호작용 검증은 남아 있습니다.
