"""_parse_multipart 회귀 테스트: 바이너리 파일의 실제 끝 바이트(\\r/\\n)가
구분자 제거 과정에서 잘리지 않는지 검증. (data-integrity bug fix)
"""
from search_app import _parse_multipart


class H:
    """self.headers 스탠드인 — .get(key, default) 만 지원하면 됨."""
    def __init__(self, ctype):
        self._c = ctype

    def get(self, k, default=""):
        return self._c if k == "Content-Type" else default


def _build_body(boundary: str, field_content: bytes) -> bytes:
    b = boundary.encode()
    return (
        b"--" + b + b"\r\n"
        b'Content-Disposition: form-data; name="f"; filename="x.docx"\r\n'
        b"Content-Type: application/octet-stream\r\n"
        b"\r\n"
        + field_content + b"\r\n"
        b"--" + b + b"--\r\n"
    )


def test_binary_trailing_0a_byte_not_truncated():
    """파일의 실제 마지막 바이트가 0x0a(\\n)인 경우, 그 바이트가
    구분자용 \\r\\n 제거 로직에 의해 함께 잘려나가면 안 됨(구 rstrip 버그)."""
    boundary = "----WebKitFormBoundaryABC123"
    # 내부에 \r\n 을 포함하고(내부 개행으로 분할되지 않음을 증명),
    # 실제 파일 콘텐츠의 마지막 바이트가 0x0a 로 끝나는 바이너리(ZIP류) 시뮬레이션.
    content = b"PK\x03\x04\r\nSOMEDATA\x00\x0a"
    body = _build_body(boundary, content)
    headers = H(f"multipart/form-data; boundary={boundary}")

    fields = _parse_multipart(headers, body)

    assert fields["f"] == content, (
        f"trailing byte truncated: expected {content!r}, got {fields.get('f')!r}"
    )


def test_quoted_boundary_parses_correctly():
    """RFC 2046: boundary 값이 따옴표로 감싸질 수 있음(Content-Type: ...; boundary=\"----X\")."""
    boundary = "----X"
    content = b"hello world"
    body = _build_body(boundary, content)
    headers = H(f'multipart/form-data; boundary="{boundary}"')

    fields = _parse_multipart(headers, body)

    assert fields["f"] == content


def test_no_boundary_returns_empty_dict():
    headers = H("multipart/form-data")
    assert _parse_multipart(headers, b"anything") == {}
