from config.paths import bundle_root, is_frozen, project_root


def test_project_root_points_at_repo():
    root = project_root()
    assert (root / "app.py").exists() or (root / "main.py").exists()
    assert (root / "config").exists()


def test_bundle_root_matches_project_when_not_frozen():
    assert is_frozen() is False
    assert bundle_root() == project_root()
