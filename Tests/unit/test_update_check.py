from scripts.check_update import check_update, current_version


def test_current_version_nonempty():
    assert current_version()


def test_check_update_local_only():
    report = check_update(None)
    assert report["local_version"]
    assert report["update_available"] is False
    assert report["action"] == "report_only"
