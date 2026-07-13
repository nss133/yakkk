# 차이 하이라이트(diff) — 초안 vs 표준약관 설계

> 작성: 2026-07-13 · 상태: 설계 승인(대화) · 스펙 리뷰 대기
> 대상: 유사조문 결과의 표준약관 섹션. VISION.md 개선 우선순위 ②.

## 1. 문제

준수성 심사의 핵심은 "표준약관엔 있는데 초안에 빠진/추가된 문구"의 식별인데,
현재 표준약관 대응 조문은 본문 앞 120자 미리보기만 표시됨. 심사자가 두 조문을
각각 열어 눈대조해야 하며, 이것이 대량 약관검토의 병목. 엔진(매칭)은 이미 있으므로
렌더링 계층만 추가하면 "자동 1차 심사 리포트"가 됨.

## 2. 확정된 요구사항 (사용자 결정)

- **대상**: 표준약관(STANDARD) 섹션만. 감독규정·타사 섹션 무변경(후속 확장 여지).
- **레이아웃**: 인라인 통합 diff — 한 본문 안에 표준약관에만 있는 문구=빨간 취소선(`<del>`),
  초안에만 있는 문구=초록 배경(`<ins>`). 기준 방향은 초안(draft).
- **표시 시점**: 1위 매치는 `<details open>`으로 즉시 펼침, 2·3위는 `<details>` 접기.
  JS 없이 순수 HTML.
- **적용 화면**: `_similar_blocks` 공유 지점 1곳 수정으로 `/similar`(조문 열람)·
  `/similar_text`(붙여넣기)·`/review`(docx 일괄심사) 모두 자동 적용.

## 3. 설계

### 3.1 새 모듈 `src/diff_render.py` (순수 함수, stdlib만)

- `diff_html(draft: str, std: str) -> str`
  - 토큰화: `re.split(r'(\s+)', text)`로 공백 토큰 보존 분할.
    비교 시퀀스는 공백 정규화한 어절 목록(어절 단위 diff — 한국어 약관에서
    "30일→3영업일" 같은 교체가 어절로 깔끔히 잡힘. 문자 단위는 산탄 노이즈로 기각).
  - `difflib.SequenceMatcher(None, std_words, draft_words, autojunk=False)` opcode 순회:
    `equal`=그대로, `insert`(초안에만)=`<ins>`, `delete`(표준약관에만)=`<del>`,
    `replace`=`<del>`+`<ins>` 연속.
  - 출력 시 원문 공백 복원(초안 쪽은 초안의 공백, 삭제분은 단일 공백 연결).
  - XSS: 기존 `_highlight`와 동일 원칙 — 어절을 `html.escape` 후 태그로 wrap.
- `diff_stats(draft: str, std: str) -> dict`
  - `{"equal_ratio": float, "n_ins": int, "n_del": int}` — `<summary>` 헤더의
    "일치 87% · 초안 추가 3곳 · 표준약관 누락 2곳" 요약용. opcode를 1회만 계산해
    diff_html과 공유 가능하도록 내부 공통 함수로 구성(`_diff_ops`).

### 3.2 `search_app.py` 통합

- `_similar_blocks`에서 표준약관 섹션만 전용 렌더러 `render_standard_diff(rows, query_text)`로 분기.
  감독규정·타사 섹션은 기존 `render_similar` 유지.
- 각 매치를 `<details>`로 렌더: `<summary>`에 기존 메타(유사도%·상품/문서 링크·조문명 링크)
  + diff_stats 요약. 1위만 `open` 속성.
- **저유사도 가드**: 매치 유사도 < 0.25 → diff 대신 기존 120자 미리보기 +
  "유사도가 낮아 차이 표시 생략(대응 조문이 아닐 수 있음)" 안내. 노이즈 diff가
  '이만큼 다르다'는 오판을 유도하는 것 방지. 임계값은 상수 `DIFF_MIN_SCORE`.
- **길이 가드**: 두 본문 중 한쪽이 `MAX_DIFF_CHARS`(20,000자) 초과 시 diff 생략·미리보기 폴백
  (별표 등 초장문에서 SequenceMatcher 지연·화면 폭주 방지).
- CSS 추가: `ins{background:#d7f5d7;text-decoration:none} del{background:#fdd;color:#933}`
  + details/summary 여백 소량.
- 반입물: 기존 2파일(DB+search_app.py) → **3파일(+diff_render.py)**.
  테스트 용이성을 위해 단일파일 인라인 대신 별도 모듈. README 반입물 목록 갱신.

### 3.3 데이터 흐름 (변경 없음 확인)

`db_similar` 결과 rows에 `text` 전문이 이미 포함 → DB 스키마·simmatch 엔진·수집 파이프라인
전부 무변경. 렌더링 계층 순수 추가.

## 4. 검증

- **단위 테스트** `tests/test_diff_render.py` (TDD, bare import — conftest가 src 경로 추가):
  - 어절 교체("30일"→"3영업일")·삽입·삭제 각각 ins/del 태그 정확성
  - 공백·개행 보존 재조립(원문 복원성)
  - XSS: `<script>` 포함 입력이 escape되어 출력
  - 동일 텍스트 → 태그 없음·equal_ratio 1.0 / 완전 상이 텍스트 → stats 값 검증
  - 빈 문자열·초장문 폴백
- **통합**: `_similar_blocks` 출력에 details 3개(1위만 open)·저유사도 시 생략 문구 —
  소형 픽스처 DB로 스모크. 기존 3섹션 구조 무회귀(기존 테스트 green).
- 브라우저 스모크: /similar_text에 표준약관 변형 문구 붙여넣기 → diff 육안 확인.

## 5. 리스크

- 문장 재배열이 큰 조문은 diff가 대체로 빨강/초록 — 저유사도 가드 + stats 요약(일치%)으로
  "diff를 신뢰할 수준인지"를 심사자가 즉시 판단 가능하게 함.
- 어절 단위라 조사만 바뀐 경우("을"→"를") 어절 전체가 교체로 표시 — 수용(과잉 정밀보다 가독).
  필요 시 후속: replace 쌍에만 문자 단위 2차 diff.
- `<details>` 미지원 구형 브라우저 — 폐쇄망 PC 표준 브라우저(Edge/Chrome) 기준 문제없음.

## 6. 후속 (범위 외)

- 타사 조문 diff 확장 / replace 어절쌍 문자 단위 2차 diff
- 표준약관 브릿지(VISION ①)와 결합: 초안→표준약관 diff + 해당 표준약관의 감독규정 근거 병기
