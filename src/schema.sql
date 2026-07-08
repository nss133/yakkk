-- 약관 DB 파일럿 스키마
-- 계층 1: 협회 비교공시 카탈로그(products) / 계층 2: 각 사 공시실 원문(documents)

CREATE TABLE IF NOT EXISTS insurers (
    member_cd   TEXT PRIMARY KEY,   -- 협회 회사코드 (L34 등)
    name        TEXT NOT NULL,
    disclosure_url TEXT             -- 각 사 상품공시실 진입 URL
);

CREATE TABLE IF NOT EXISTS products (
    prod_cd     TEXT PRIMARY KEY,   -- 협회 상품코드 (js_spRspan에서 추출)
    member_cd   TEXT NOT NULL REFERENCES insurers(member_cd),
    prod_nm     TEXT NOT NULL,
    prod_group_cd TEXT NOT NULL,    -- 024400010001 등
    prod_group_nm TEXT NOT NULL,    -- 종신보험/질병보험/암보험
    ext_url     TEXT,               -- 협회→각사 공시실 링크(랜딩)
    sale_start  TEXT,               -- 판매일자(협회 표기)
    summary_file_no TEXT,           -- 협회 호스팅 상품요약서 fileNo
    sale_status TEXT DEFAULT '판매중',
    fetched_at  TEXT NOT NULL,      -- 카탈로그 수집 시각
    snapshot_file TEXT              -- 원본 HTML 스냅샷 경로
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    member_cd   TEXT NOT NULL REFERENCES insurers(member_cd),
    prod_cd     TEXT REFERENCES products(prod_cd),  -- 매칭 실패 시 NULL 허용(수동 매핑)
    prod_nm_raw TEXT,               -- 각 사 공시실에 표기된 상품명(협회 표기와 다를 수 있음)
    doc_type    TEXT NOT NULL,      -- TERMS(약관)/METHODS(사업방법서)/SUMMARY(상품요약서)
    version_label TEXT,             -- 판매기간·개정일자 등 각 사 표기
    source_url  TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    file_size   INTEGER,
    fetched_at  TEXT NOT NULL,
    UNIQUE(sha256, member_cd)       -- 동일 파일 중복 적재 방지
);

CREATE INDEX IF NOT EXISTS idx_products_member ON products(member_cd);
CREATE INDEX IF NOT EXISTS idx_documents_prod ON documents(prod_cd);
