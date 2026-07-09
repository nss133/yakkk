import docx
from docx_split import docx_to_text, split_docx


def _make_docx(tmp_path, paras):
    d = docx.Document()
    for p in paras:
        d.add_paragraph(p)
    fp = tmp_path / "draft.docx"
    d.save(fp)
    return str(fp)


def test_docx_to_text_joins_paragraphs(tmp_path):
    fp = _make_docx(tmp_path, ["제1조 (목적)", "이 약관은 …을 정합니다."])
    t = docx_to_text(fp)
    assert "제1조" in t and "목적" in t


def test_split_docx_yields_clauses(tmp_path):
    fp = _make_docx(tmp_path, ["제1조 (목적) 이 약관은 목적을 정합니다.",
                               "제2조 (용어의 정의) 이 약관에서 쓰는 용어는 다음과 같습니다."])
    out = {no: ti for no, ti, _ in split_docx(fp) if no}
    assert out.get("제1조") == "목적"
    assert out.get("제2조") == "용어의 정의"
