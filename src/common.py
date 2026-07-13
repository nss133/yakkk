"""수집기 공통 유틸: DB 적재·파일 저장·검색키 로드."""
import datetime
import hashlib
import json
import pathlib
import re
import sqlite3
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "terms.db"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

FTS_MIN_CHARS = 30
FTS_DDL = ("CREATE VIRTUAL TABLE clauses_fts USING fts5("
           "text, title, content='clauses', content_rowid='clause_id')")


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", s).strip("_")[:120]


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.executescript((ROOT / "src" / "schema.sql").read_text())
    cols = [r[1] for r in conn.execute("PRAGMA table_info(documents)")]
    if "src_category" not in cols:
        conn.execute("ALTER TABLE documents ADD COLUMN src_category TEXT")
    return conn


def load_search_keys(tag: str):
    """catalog/searchkeys_<tag>.json → [{'search_key':…, 'members':[{prod_cd,prod_nm,grp}…]}…]"""
    return json.loads((ROOT / "catalog" / f"searchkeys_{tag}.json").read_text())


def save_document(conn, member_cd: str, prod_nm_raw: str, doc_type: str, version_label: str,
                  source_url: str, blob: bytes, dest: pathlib.Path, src_category: str = "") -> bool:
    """PDF 검증 후 저장+documents 적재. 성공 시 True."""
    if not blob or not blob.startswith(b"%PDF") or len(blob) < 1000:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        """INSERT OR IGNORE INTO documents(member_cd, prod_nm_raw, doc_type, version_label,
               source_url, file_path, sha256, file_size, fetched_at, src_category)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (member_cd, prod_nm_raw, doc_type, version_label, source_url,
         str(dest.relative_to(ROOT)), hashlib.sha256(blob).hexdigest(), len(blob), now, src_category),
    )
    conn.commit()
    return True
