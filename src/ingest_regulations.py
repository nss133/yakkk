#!/usr/bin/env python3
"""감독규정·법령 평문 → DB 적재(doc_type=REG). ingest_standards 로직 재사용.

사용법: .venv/bin/python src/ingest_regulations.py
"""
import pathlib

from common import ROOT
from ingest_standards import ingest
from standards_prep import load_manifest, to_plaintext
from common import open_db

MANIFEST = ROOT / "catalog" / "regulations.json"


def main():
    conn = open_db()
    for e in load_manifest(str(MANIFEST)):
        txt = to_plaintext(e)
        n = ingest(conn, e, txt)
        print(f"  [{e['key']}] {e['name']} ({e['version_label']}) — 조문 {n}개 적재")
    total = conn.execute("SELECT COUNT(*) FROM documents WHERE doc_type='REG'").fetchone()[0]
    print(f"완료: REG 문서 {total}건")
    conn.close()


if __name__ == "__main__":
    main()
