# WORK 04-Y — Galaxy options dashboard refinement

## 변경 사항

- 표시 언어를 한국어 중심으로 정리하고 금융 용어를 통일했습니다: 콜, 풋, 거래량, 미결제약정(OI), 행사가, 만기, 관측률.
- HTML에 `lang="ko"`, `translate="no"`, 번역 비활성 메타 태그를 지정했습니다. WORK 04-X 원본에 보고된 비정상 한국어 문구는 없었습니다. 당시 원문이 영어 중심이고 문서 언어도 `en`이어서 브라우저 자동 번역이 원인일 가능성은 있지만, Galaxy 번역 동작을 직접 확인하지 못해 원인 확정은 아닙니다.
- 옵션 체인을 데스크톱 `콜 | 행사가 | 풋` 구조로 묶었습니다. 모바일 기본 표는 거래량·OI·행사가만 보여 주고, 행을 눌렀을 때 선택한 개별 계약의 Bid/Ask 상세를 펼칩니다.
- Bid/Ask는 소수점 두 자리로 표시합니다. 실제 원본에 존재하는 필드만 사용하며 IV 열은 추가하지 않았습니다.
- 실행 ID, 수집시각, 거래일, 원본 SHA-256을 접을 수 있는 스냅샷 상세에 보존했습니다.
- 기존 차트, 만기별 계산, 합계, 결측 처리, PROVISIONAL 상태와 데이터 제한 문구는 유지했습니다.

## 검증

보존된 WORK 04-R 원본 SHA-256은 `85f6660ac4a07da061f7d2eb50080dcb40ed6203618710feb017edc55ef3d5ce`로 일치했습니다. 2,188개 계약·24개 만기·444개 행사가와 기존 Volume/OI 합계의 회귀 검증도 통과했습니다.

오프라인 단위 테스트는 21/21 통과했고, 생성 HTML의 인라인 JavaScript 구문 검사도 통과했습니다. 브라우저 실렌더링과 Galaxy 기기 재검증은 완료하지 못했습니다. 로컬 루프백 페이지는 클라우드 브라우저에서 `net::ERR_CONNECTION_REFUSED`였고, 네이티브 Chromium 자동입력은 X11 접근성 공급자 부재 오류로 진행할 수 없었습니다. 따라서 `DEVICE_PENDING`입니다.

## 데이터 제한

- `PROVISIONAL`
- `EOD_UNVERIFIED`
- `MISSINGNESS_CAUSE_UNKNOWN`
- `FULL_VOLUME_COMPLETENESS_UNVERIFIED`
- 현재 주가 기준선, IV, GEX, 매수·매도 흐름은 만들거나 표시하지 않습니다.

## 오프라인 대시보드 재생성

WORK 04-X에 기록된 `options_collector.nvda_dashboard` 인자를 사용해 보존된 WORK 04-R contracts CSV, WORK 04-T summary/volume/OI CSV, manifest, raw JSON, batch summary를 입력하고 새 출력 디렉터리를 지정합니다. 집계/수집 코드는 변경하지 않았습니다.
