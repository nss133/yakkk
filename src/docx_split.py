#!/usr/bin/env python3
"""초안 docx → 조문 청크. python-docx로 문단 추출 후 clause_split 재사용."""
from clause_split import split_clauses


def docx_to_text(path) -> str:
    """path: 파일 경로(str/Path) 또는 파일류 객체(BytesIO 등) 모두 허용."""
    import docx
    d = docx.Document(path)
    return "\n".join(p.text for p in d.paragraphs)


def split_docx(path):
    return split_clauses(docx_to_text(path))
