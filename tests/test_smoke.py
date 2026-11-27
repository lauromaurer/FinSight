def test_core_module_imports_as_part_of_the_finsight_package():
    from finsight import finsight_core

    assert finsight_core.APP_NAME == "FinSight"
