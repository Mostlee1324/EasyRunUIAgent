"""配置：解析路径、数据目录迁移。"""

from __future__ import annotations

from pathlib import Path

from easyrun.config import Settings, migrate_legacy_paths


def test_resolved_paths_default_to_data_dir(tmp_path):
    s = Settings(data_dir=tmp_path / "data")
    assert s.resolved_database_url == f"sqlite+aiosqlite:///{tmp_path / 'data' / 'easyrun.db'}"
    assert s.resolved_artifact_dir == tmp_path / "data" / "artifacts"


def test_explicit_config_wins(tmp_path):
    s = Settings(
        data_dir=tmp_path / "data",
        database_url="postgresql+asyncpg://u:p@h/db",
        artifact_dir=tmp_path / "custom-artifacts",
    )
    assert s.resolved_database_url == "postgresql+asyncpg://u:p@h/db"
    assert s.resolved_artifact_dir == tmp_path / "custom-artifacts"


def test_migrate_legacy_paths(monkeypatch, tmp_path):
    import easyrun.config as config

    monkeypatch.setattr(config, "ROOT_DIR", tmp_path)
    (tmp_path / "easyrun.db").write_text("sqlite-legacy")
    legacy_artifacts = tmp_path / "artifacts"
    legacy_artifacts.mkdir()
    (legacy_artifacts / "x.png").write_bytes(b"png")

    s = Settings(data_dir=tmp_path / "data")
    migrate_legacy_paths(s)

    assert (tmp_path / "data" / "easyrun.db").read_text() == "sqlite-legacy"
    assert (tmp_path / "data" / "artifacts" / "x.png").exists()
    assert not (tmp_path / "easyrun.db").exists()
    assert not legacy_artifacts.exists()

    # 幂等：再次执行不报错、不覆盖
    migrate_legacy_paths(s)


def test_migrate_skipped_when_explicit_config(monkeypatch, tmp_path):
    import easyrun.config as config

    monkeypatch.setattr(config, "ROOT_DIR", tmp_path)
    (tmp_path / "easyrun.db").write_text("legacy")
    s = Settings(data_dir=tmp_path / "data", database_url="postgresql+asyncpg://u:p@h/db")
    migrate_legacy_paths(s)
    assert (tmp_path / "easyrun.db").exists()  # 显式配置时不动旧文件


def test_allure_bin_resolution(tmp_path, monkeypatch):
    import easyrun.config as config

    monkeypatch.setattr(config, "ROOT_DIR", tmp_path)
    s = Settings(data_dir=tmp_path / "data")
    assert s.resolve_allure_bin() is None  # 无 PATH、无 tools 时不报错

    explicit = tmp_path / "my-allure"
    explicit.write_text("x")
    s2 = Settings(data_dir=tmp_path / "data", allure_bin=str(explicit))
    assert s2.resolve_allure_bin() == str(explicit)
