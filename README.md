# yakgwan-db — 생보사 약관 DB 구축 (파일럿)

내부 약관검토 활용 목적의 생명보험사 공시 약관 수집·DB화 프로젝트.
장기 목표: 폐쇄망 반입 → 상품기초서류 검토 지원.

## 파일럿 범위 (2026-07-07 확정)

- **판매중 상품 × 종신/질병/암 × 미래에셋생명(L34)·한화(L01)·삼성(L03)·교보(L05)**
- 협회 분류상 "건강"은 질병보험(0003)+암보험(0004)으로 매핑

## 아키텍처: 2계층 수집

| 계층 | 소스 | 역할 | 도구 |
|---|---|---|---|
| 카탈로그 | 생보협회 비교공시(pub.insure.or.kr) | 회사×상품 마스터 목록+메타 | `src/catalog_fetch.py` (stdlib, 월 1회 저빈도) |
| 원문 | 각 보험사 상품공시실 | 약관·사업방법서·요약서 PDF | `src/collect_<insurer>.py` (Playwright) |

약관 PDF는 협회에 없음(상품명 링크 = 각 사 공시실 랜딩). 협회는 카탈로그 전용.

## 컴플라이언스 원칙

1. pub.insure.or.kr robots.txt는 일반 봇 전체 차단 → **카탈로그 수집은 월 1회, 요청 10회 미만, 2초 간격**으로 최소화. 대량·반복 크롤링 금지.
2. 각 보험사 공시실 자료는 보험업감독규정상 공시의무 자료. 수집은 **내부 검토 목적 한정**, 재배포 금지.
3. 요청 간 sleep(1.2~2초) 유지. 새벽 등 저부하 시간대 권장.
4. 수집 이력(fetched_at, snapshot_file, source_url)을 DB에 남겨 추적 가능성 확보.

## DB (db/terms.db, SQLite)

- `insurers`: 회사코드(L34 등)·공시실 URL
- `products`: 협회 카탈로그 (prod_cd PK, 상품명·상품군·판매일자·요약서 fileNo·스냅샷 경로)
- `documents`: PDF 실물 (doc_type=TERMS/METHODS/SUMMARY, version_label=판매기간, sha256 dedup)
- 스키마: `src/schema.sql`

## 사용법

```bash
# 정기 갱신(월 1회 권장) — 전 단계 자동 실행(카탈로그→수집→추출→매칭→반입DB→커버리지)
.venv/bin/python src/update_all.py
.venv/bin/python src/update_all.py --skip-collect   # 수집 제외

# 개별 단계
python3 src/catalog_fetch.py                        # ① 협회 카탈로그 → products
.venv/bin/python src/gen_search_keys.py             # ② 검색키 JSON 재생성
.venv/bin/python src/collect_mirae.py --categories 전체 --targets-json catalog/targets_L34_pilot.json
.venv/bin/python src/collect_hanwha.py              # (삼성·교보 동일; --raw-keys로 보완 수집)
.venv/bin/python src/extract_index.py               # ④ PDF→조항 청크(증분)
.venv/bin/python src/build_simindex.py               # ④b 문자 n-gram IDF 적재(유사비교용)
.venv/bin/python src/build_matches.py               # ⑤ 카탈로그↔문서 매핑(product_doc_map)
.venv/bin/python src/enrich_sections.py             # ⑤b 섹션 태깅(주계약/특약)+상품군 라벨
.venv/bin/python src/export_dist.py [--current-only] # ⑥ 반입용 DB
.venv/bin/python src/coverage_report.py             # ⑦ 커버리지 검증
.venv/bin/python src/ingest_standards.py             # ⑧ 표준약관 3종 적재(준수성 심사용, doc_type=STANDARD)
.venv/bin/python src/ingest_regulations.py           # ⑨ 감독규정·법령 4종 적재(매핑 참고용, doc_type=REG)

# 폐쇄망 검색 UI (반입물 = terms_dist*.db + search_app.py + simmatch.py + diff_render.py 네 파일, python3 stdlib만 필요)
# 필터: 회사·상품군(협회 분류)·주계약/특약·상품명 포함어 / 검색범위: 본문+제목 vs 제목(조문명)만
# 유사비교: 조문 열람 화면의 "닮은 타사 조문", /similar_text(붙여넣기), /review(docx 일괄 심사)
# 표준약관 대응 조문은 인라인 diff로 표시(초안에만 있는 문구=초록, 표준약관에만 있는 문구=빨간 취소선; 1위 펼침·저유사도는 미리보기 폴백)
# 유사조문 결과에 표준약관 대응 조문(생보·질병상해·실손5세대) + 관련 감독규정·법령
# (보험업감독규정·보험업법 등)을 표준약관 → 감독규정·법령 → 타사 유사조문 순으로 표시.
# 감독규정·법령 섹션은 순수 유사도(char n-gram+BM25) 매핑으로, 표면 어휘가 겹치는
# 주제(해약환급금·특별계정 등)는 정확도가 높으나 코퍼스 공백·랭킹 미스로 안 맞는
# 주제도 있음(품질 실측: .superpowers/sdd/reg-mapping-eval.md, 6주제 중 2/6 성공)
# — 참고용으로만 활용, 주제사전 보강은 후속 과제.
python3 src/search_app.py --db db/terms_dist_current.db --port 8765
```

## 사이트 구조 메모 (2026-07-07 조사)

### 협회 (pub.insure.or.kr)
- 보장성 목록: `POST /compareDis/prodCompare/assurance/listNew.do`
  (pageIndex, pageUnit, search_prodGroup, search_memberCd 복수)
- 상품군코드: 종신 024400010001 / 정기 0002 / 질병 0003 / 암 0004 / CI 0005 / 상해 0006 / 어린이 0007 / 치아 0009 / 간병치매 0010 / 기타 0011
- 회사코드(2026-07-07 협회 페이지 재검증 — 초기 추정 매핑에 오류 있었음): 한화 L01, ABL L02, 삼성 L03, 흥국 L04, 교보 L05, iM L31, KDB L33, 미래에셋 L34, DB L71, 동양 L74, 메트라이프 L72, KB라이프 L61, 신한 L11, 처브 L77, 하나 L63, BNP카디프 L78, 푸본현대 L17, 라이나 L51, AIA L52, IBK연금 L41, NH농협 L42, 교보라이프플래닛 L43
- 행 파싱 앵커: `class="js_spRspan_<prodCd>_2"` (회사명 셀) → 상품명 a[target=_blank] → fn_fileDown(fileNo)=협회 호스팅 상품요약서
- 페이지는 서버렌더링. 저축성 `/compareDis/prodCompare/saving/list.do`, 변액 `/compareDis/variableInsrn/...`

### 미래에셋생명 (life.miraeasset.com)
- 공시실: `/micro/disclosure/product/PC-HO-080301-000000.do` (판매중지: PC-HO-081600)
- WAF 봇차단 스크립트 존재 → curl 불가, 실브라우저(Playwright) 필요
- 데이터: `COMEXCEL.fn_getWorkDvsnDataPaging()` AJAX → 다운로드 앵커에 data-fpath/data-fileNm
- 다운로드: `POST /micro/cmmnFileDown.do` (pathType=gongci_u1, fileName, orgFileName, filePath=/uploadwas/life/<fpath>)
- 판매중 탭 첫 로드 전체 267행(전 분류). 판매기간 종료 행도 일부 포함 → version_label로 추적

### 한화생명 (www.hanwhalife.com) — collect_hanwha.py
- 판매중 목록: `DF_GDDN000_P10000.do?MENU_ID1=DF_GDGL000&MENU_ID2=DF_GDGL000_P10000` (⚠️ P20000은 판매중지 탭)
- 검색: `#schText` + "검색하기" → 결과 상품 링크 `a.ck-search2`(클릭 시 페이지 이동 없이 갱신)
- 판매기간별 그리드 `#LIST_GRID3` → `button.ck-fileDownload[data-file*='약관']` → expect_download
- data-file 속성은 파일경로 아님 → 판매기간 기반 파일명 생성. 목록 진입 타임아웃 산발 → 3회 재시도

### 교보생명 (www.kyobo.com) — collect_kyobo.py
- 전체상품조회: `/dgt/web/product-official/all-product/search`, `#input-01`+`#searchBtn`
- 행 '확인' 버튼 → 모달 `#pop-period-down`(기간별 다운로드), 닫기=`button.btn-pop-close`
  (⚠️ '닫기' 텍스트 매칭 금지 — '안내문 닫기' 토글이 먼저 걸림)
- 모달 컬럼: 판매기간|상품요약서|약관|사업방법서 — ⚠️ td 인덱스 대신 `a[href*='약관']`로 타깃(요약서 오수집 방지)
- 인접 판매기간이 동일 파일(sha 동일)인 경우 많음 → UNIQUE(sha256) dedup이 흡수

### 삼성생명 (www.samsunglife.com) — collect_samsung.py
- 판매상품 목록(SPA/Vue): `PDO-PRPRI010110M` — 전체 이력 6,500행+ 포함
- 검색: `#keywordSearch` + Enter만(검색버튼 클릭 금지 — 오버레이 차단·리셋). SPA 하이드레이션 전 Enter 무시됨 → 매칭 확인+재시도 필수
- 약관 = 표 7번째 컬럼 링크 → 팝업 문서뷰어(XView.do)가 Range 스트리밍 → 64KB 청크만 잡힘
  → %PDF 응답 URL 확보 후 전체 재요청 + `%%EOF` 검증
- 검색 API는 암호화 페이로드(g/b 파라미터) → 직접 호출 불가, UI 자동화만 가능

## 참고: 선행 프로젝트 yakk

`~/Library/Mobile Documents/com~apple~CloudDocs/cursor/yakk`
- 6개사 Playwright 시나리오(삼성/교보/한화/신한/동양/흥국) — 2026-04 기준, 현행화 필요
- PDF→조항 인덱스(`peer_index`), 조항분할(`clause_split`), 비교 엑셀 생성기 → Phase 4에서 재활용

## 로드맵

- [x] Phase 1: 협회 카탈로그 (144건 적재, 2026-07-07)
- [x] Phase 2a: 미래에셋 수집기 e2e 검증 (약관 3건)
- [x] Phase 2b: 미래에셋 파일럿 범위 전량 수집 (2026-07-07, 약관 27건/26상품/375MB — 과거판 포함)
  - 협회 24건 ↔ 사이트 상품명 가족단위 매칭 → `catalog/targets_L34_pilot.json`
  - 주의: 사이트 분류(종신/정기 13종, 건강/암 2종)가 협회 분류와 불일치, 간편고지 분류는 서버가 0건 반환
    → '전체' 조회 + 상품명 타깃 필터 방식이 정답 (`--categories 전체 --targets-json ...`)
  - selectList는 callGubun='first'로 호출해야 함(아니면 전체 조회 시 alert 가드로 중단)
- [x] Phase 2c: 삼성·한화·교보 수집기 (2026-07-07 완료)
  - 최종 커버리지(협회 카탈로그 144건 대비): **141건(98%)** — 미래에셋 24/24, 삼성 35/35, 교보 47/48, 한화 35/37
  - 문서 692건 / 7.3GB (판매기간별 과거판 포함, sha256 dedup)
  - 미커버 3건(사이트 미노출·수동 확인 필요): 한화 H간병보험[간편/일반](2026-05-04 출시인데 공시실 검색 미노출),
    교보암보험[D2408](다이렉트 채널 명칭 차이 의심 — 간편암보험[D2408]은 수집됨)
  - 검색 요령: 협회 카탈로그 키 실패 시 `--raw-keys`로 공백제거·축약·exact 변형 재시도
    (삼성은 exact 명칭 "The(더)Dream"이 통한 사례). coverage_report의 '검색키 미수집'은
    dest.exists 스킵 때문에 과소표시 — 가족 커버리지가 실지표
- [x] Phase 4: PDF 텍스트화·조항 인덱싱 (2026-07-07 완료)
  - `extract_index.py`: 692문서 → 조항 청크 640,930개(실패 0). 제N조 인라인 헤더+별표 분할, 전량 청크 보존(원문 복원 가능)
  - `export_dist.py`: 반입용 SQLite 2종 — 전체판 `terms_dist.db` 1.56GB / **현행판 `terms_dist_current.db` 290MB(zip 72MB)**
  - FTS5 전문검색 검증 완료(예: '대장점막내암' → 조문 단위 히트). 30자 미만 청크(목차 라인)는 FTS 제외
  - 용량 실측: PDF→원문텍스트 약 7:1, FTS 인덱스 +30%. (23~36:1은 zlib 압축 텍스트 기준 — 반입 추정 시 혼동 주의)
- [x] Phase 3: `build_matches.py` → `product_doc_map` (2026-07-07) — 카탈로그 141/144 연결, 문서 620/692 연결(미연결 72건=비파일럿 인접상품·과거명칭). N:M 매핑(협회=유형 단위, 사이트=통합약관 단위)
- [x] Phase 5: `update_all.py` 월 주기 갱신 오케스트레이터 — 전 단계 멱등·증분, logs/에 단계별 로그
- [x] Phase 6(부분): `search_app.py` 폐쇄망 검색 UI — stdlib 단일 파일(FTS 검색·조문 열람·문서 목록), 반입물 = DB+이 파일 2개
- [x] 10개사 확장 완료 (2026-07-08) — **커버리지 295/317 (93%)**, 문서 1,209건/9.9GB, 조항 청크 1,022,060개
  - 회사별: 미래에셋 100%·삼성 100%·KB 100%·교보 98%·한화 95%·동양 93%·신한 92%·NH 88%·메트 81%·흥국 79%
  - 반입 DB: 전체판 terms_dist.db 2.2GB / 현행판 terms_dist_current.db 426MB (205문서·16.5만 조항)
  - 신규 수집기 6종 다운로드 방식: 신한=bizxpress 경로 GET, NH=/pdfViewer.nhl 직접 GET(popupPdfViewer 파싱),
    KB=/api/archive/archives/download/product-terms/{seqno}/{boxno} 직링크, 메트=fnum=03 직링크(title=상품명),
    동양=pbano.myangel.co.kr(www는 404)+기간 td4/5, 흥국=자동완성 병합(빈검색+키앞4자 probe)
  - 검색 UI v2(사용자 피드백 반영): 회사·상품군·주계약/특약·상품명 필터 + 제목(조문명)만 검색.
    enrich_sections.py가 '제1조 재시작' 경계로 섹션 태깅(clauses.section_no/is_rider/section_title)
  - 잔여 미커버 22건: 흥국 6(자동완성 미노출)·메트 5(달러종신 등 별도 공시 추정)·NH 3·신한 3·동양 2·한화 2(H간병)·교보 1(D2408) — 수동 확인 대상
- [완료된 확장 이력 — 착수 기록]
  - [x] 카탈로그 10개사 재수집(317상품) — ⚠️ 초기 회사코드 매핑 오류 발견·정정함(신한 L11, KB L61, 메트 L72, 동양 L74, NH L42; 위 회사코드 표가 검증본)
  - [x] 검색키 9개사 생성(gen_search_keys.py)
  - [x] 메트라이프 수집기 완성·e2e 검증(collect_metlife.py — fnum=03=약관 651앵커, title=상품명, 직링크 request.get)
  - [ ] 재개 TODO: ①메트라이프 전량 실행 ②KB 수집기(productList.do, 테이블 구분|상품명|판매기간|…|약관, 검색 input[placeholder*='검색어'])
    ③신한(yakk 방식: #meta05·#btnSearch·#GoodsList>tr, 버튼 _3=약관 data-ws-id/data-url→bizxpress GET — 셀렉터 생존 확인)
    ④동양(pbano.myangel.co.kr/paging/WE_AC_WEPAAP020100L — www 아닌 pbano, #productSearchLbl+Enter, 행 링크 0요약서/1방법서/2약관)
    ⑤흥국(#searchText+doSearch 자동완성 ajax→hidden 설정→#productVoTr, td2=약관, nppfs-loading-modal 제거 필요)
    ⑥NH(HOON0004M00.nhl, #proName+'검 색', 행 '확인'→goAnonm→기간별 모달 — 모달 구조 미확인)
    ⑦수집 후: extract_index → build_matches → export_dist(2종) → coverage_report → update_all.py에 6개사 편입
- [ ] 잔여: 미커버 3건 수동 확인(한화 H간병×2 — 공시실 검색 미노출 확인됨 / 교보암보험[D2408] — 전체상품조회 46행에 부재 확인, 다이렉트 채널 공시 추정), 폐쇄망 반입 승인 절차, 확대 시 22개사 수집기 추가
