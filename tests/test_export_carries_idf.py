import export_dist


def test_copy_list_includes_idf_tables():
    # export_dist가 두 테이블을 반입 대상에 포함하는지(소스에 명시)
    import inspect
    src = inspect.getsource(export_dist.main)
    assert "ngram_idf" in src and "simindex_meta" in src


def test_copy_list_includes_std_reg_map():
    import inspect
    src = inspect.getsource(export_dist.main)
    assert "std_reg_map" in src


def test_update_all_has_bridge_step_after_simindex():
    import inspect
    import update_all
    src = inspect.getsource(update_all.main)
    assert "build_std_reg_map.py" in src
    # 유사인덱스(4b) 이후에 와야 함 — db_similar가 ngram_idf 필요
    assert src.index("build_simindex.py") < src.index("build_std_reg_map.py")
