# WORK 04-AE — NVDA OHLCV source authentication

**최종 판정: `NVDA_OHLCV_UPSTREAM_SOURCE_UNVERIFIED`.** 기존 Library 실행 번들의 실제 바이트와 내장 90행 해시는 재검증했고, 2026-04-21~2026-08-27 구간은 Nasdaq/NYSE 거래일 달력 기준 90개 세션과 일치합니다. 다만 원본 응답과 실행 시 선택된 공급자 기록이 없어 해당 90행을 Yahoo 또는 다른 공급자 응답에 확정 연결할 수 없습니다. 가격 조정 계약 및 OPTIONS LAB 재사용 권한도 확인되지 않아 데이터는 가져오지 않았고 HV를 계산·표시하지 않았습니다.

## 기준 및 브랜치

- 저장소: `1onlysm/seoungminlee`
- SOURCE: `work04ad-nvda-ohlcv-evidence-recovery`
- 실행 시 원격 HEAD: `cf20a20cc3c062065b4bf2f6ae2c15396d7d5e26` (기준 부모 `31cebeafe15901430958d5c0c9e70598b4a0b734`)
- TARGET: `work04ae-nvda-hv-source-authentication`, 위 HEAD에서 생성
- 실제 데이터 수집 및 새 공급자 연결: 없음

## 소스 추적 결과

정확한 후보 `NVDA_NAVI-BOOT-NVDA-20260829T074538284767Z_execution_bundle.json`을 다시 받아 검증했습니다. 번들 SHA-256은 `11afaf56361858216019ac95027262e858a7d13a006b7489b2ed159ea7d9c96e`, `execution_bundle.producer_attendance[5].output.raw_ohlcv_90d`의 정규 직렬화 SHA-256은 `735c5e5dbb42b9697930373b5436c53bbfa2db143d8f59aaa6e4f853fc836f65`입니다.

실행 번들의 TECH producer는 `source: OHLCV`와 `LIVE_RUN`을 기록하고 `canonical market adapter tech_producer`에 데이터가 입력되었다고 설명합니다. 같은 실행의 NVDA discovered-ledger는 출처를 Yahoo Finance chart endpoint라고 기록합니다. 이와 연결된 시장 어댑터 코드는 Yahoo chart 경로를 기본 소스로, Naver Finance를 fallback으로 둡니다. 그러나 TECH의 선택 공급자·응답 URL·요청 파라미터·HTTP 결과는 payload에 남지 않았고 원본 제공자 응답 바이트도 없습니다. 따라서 같은 실행의 Yahoo 흔적은 강한 정황이지만 90행의 정확한 원천을 증명하지 않습니다. Library에서 확보한 의존 코드 바이트 해시도 번들에 선언된 의존성 해시와 일치하지 않아 실행 당시 정확한 코드 바이트까지 증명하지 못했습니다.

## 데이터·권리 게이트

- 후보: NVDA 라벨 90행, 2026-04-21~2026-08-27, 날짜/OHLCV 필드. 구조 검사는 90/90 통과했습니다.
- 달력: 해당 범위에서 Nasdaq/NYSE 공식 일정상 빠진 세 평일은 휴장일입니다. 나머지 90 세션은 빠짐없이 존재합니다.
- 조정 기준: `RAW_OHLC_ONLY`는 원시/분할조정/배당조정 여부를 정의하지 않습니다. 분할·배당 보정 기준, 통화 및 원본 응답 부재로 미확정입니다.
- 공급자 이용 권한 및 별도 프로젝트 데이터의 OPTIONS LAB 재사용 권한: 확인 불가. 공개 저장소로 원시 값을 복제하지 않았습니다.
- 결과: `PROVENANCE_PARTIAL`, `REUSE_RIGHTS_UNVERIFIED`; production HV import gate 실패.

Yahoo의 공개 이용약관은 서면 허가 없는 콘텐츠 복제·배포를 제한합니다. 이는 후보가 Yahoo에서 왔다는 증명도, 해당 사용자 계정의 별도 권한 판단도 아닙니다. 보고서는 이를 권리 확인이 필요하다는 근거로만 기록합니다.

## HV 및 대시보드

HV10/HV20/HV30/HV60은 모두 **계산하지 않았습니다**. WORK 04-AB의 계약(정확히 N개 종가 로그수익률, ddof=1, `sqrt(252) × 100`)은 그대로 두었습니다. 계산 가능한 90개 종가가 있다고 해도 인증·재사용·가격 조정 게이트 실패 때문에 production 값으로 쓸 수 없습니다. 기존 IV, IV Rank, IV Percentile, IV Skew 차단도 유지됩니다.

기존 옵션 스냅샷은 재검증한 SHA-256 `85f6660ac4a07da061f7d2eb50080dcb40ed6203618710feb017edc55ef3d5ce`로 불변이며 계약 2,188, 행사가 444, 만기 24, Call/Put 거래량 1,457,430/953,110, Call/Put OI 9,839,124/8,636,754가 유지됩니다. 기존 대시보드를 온라인 요청 없이 다시 생성했으며 HV 숫자는 포함되지 않았습니다.

## 검증 및 다음 조치

- 기준 테스트: `python -m unittest discover -s tests -v` — 112 통과, 0 실패
- Python compileall: 통과
- 기존 대시보드 생성: 오프라인 성공
- 생성 HTML JavaScript 구문 검사: 통과
- 실제 브라우저: 환경 제약으로 확인 불가; Galaxy: 사용자 확인 대기
- 다음 조치: 원본 응답/선택 공급자 로그와 조정 계약, 그리고 OPTIONS LAB에서 해당 데이터를 사용할 수 있다는 제공자 권한 근거를 데이터 보유자가 제공해야 합니다. 새 요청·수집은 별도 승인 전까지 하지 않습니다.

상세 JSON은 `audit_reports/work04ae_source_trace.json`, `audit_reports/work04ae_ohlcv_quality.json`, `audit_reports/work04ae_calendar_audit.json`, `audit_reports/work04ae_hv_verification.json`, `audit_reports/work04ae_data_integrity.json`, `audit_reports/work04ae_source_manifest.json`, `audit_reports/work04ae_test_report.json`에 기록했습니다.

### 안전 확인

- LIVE market-data requests: 0
- GitHub Actions runs: 0
- Main modifications: 0
- New provider integrations: 0
- APK modifications: 0
- Original Nasdaq options snapshot changes: 0
