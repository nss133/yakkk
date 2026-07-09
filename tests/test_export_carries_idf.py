import export_dist


def test_copy_list_includes_idf_tables():
    # export_dist가 두 테이블을 반입 대상에 포함하는지(소스에 명시)
    import inspect
    src = inspect.getsource(export_dist.main)
    assert "ngram_idf" in src and "simindex_meta" in src
