import search_app


def test_page_has_reset_button():
    assert 'href="/"' in search_app.PAGE
    assert "초기화" in search_app.PAGE
