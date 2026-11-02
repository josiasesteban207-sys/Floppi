from pathlib import Path

import pytest

from tools import verify_worker_expiry_migration


def test_scratch_migration_runner_requires_explicit_authorization(monkeypatch, capsys):
    monkeypatch.setattr(
        verify_worker_expiry_migration,
        "verify_migration_on_scratch",
        lambda *_args: pytest.fail("Migration must not run without explicit authorization."),
    )

    with pytest.raises(SystemExit) as error:
        verify_worker_expiry_migration.main(
            ["--backup", "backups/staging/test.dump"]
        )

    assert error.value.code == 2
    assert "--authorize-scratch-migration-017" in capsys.readouterr().err


def test_migration_runner_uses_only_the_offline_scratch_image_and_no_network():
    source = Path(verify_worker_expiry_migration.__file__).read_text(encoding="utf-8")

    assert '"--network"' in source
    assert '"none"' in source
    assert '"--tmpfs"' in source
    assert "PortBindings" in source
    assert "SCRATCH_NAME_PATTERN" in source
    assert "floppi-worker-expiry-scratch-" in source


@pytest.mark.parametrize(
    ("table_exists", "apply_baseline"),
    [("t", False), ("f", True)],
)
def test_baseline_migration_only_runs_when_restored_backup_lacks_table(
    monkeypatch, table_exists, apply_baseline
):
    applied = []
    monkeypatch.setattr(
        verify_worker_expiry_migration,
        "_scratch_psql",
        lambda *_args: table_exists,
    )
    monkeypatch.setattr(
        verify_worker_expiry_migration,
        "_apply_migration_file",
        lambda _container, migration: applied.append(migration),
    )

    verify_worker_expiry_migration._ensure_baseline_schema("scratch-container")

    assert applied == (
        [verify_worker_expiry_migration.MIGRATION_BASELINE] if apply_baseline else []
    )


def test_scratch_psql_passes_sql_as_subprocess_input_bytes(monkeypatch):
    observed = {}

    def fake_run_docker(arguments, **kwargs):
        observed["arguments"] = arguments
        observed.update(kwargs)
        return "ok"

    monkeypatch.setattr(verify_worker_expiry_migration, "_run_docker", fake_run_docker)

    result = verify_worker_expiry_migration._scratch_psql("scratch-container", "SELECT 1;")

    assert result == "ok"
    assert observed["input_data"] == b"SELECT 1;"
    assert "stdin" not in observed
