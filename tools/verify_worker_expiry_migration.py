#!/usr/bin/env python3
"""Verify migration 017 only in a disposable, offline PostgreSQL scratch container."""
from __future__ import annotations

import argparse
import json
import re
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import BinaryIO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.staging_environment import (
    SERVICE,
    _run_compose,
    check_database,
    load_and_validate_config,
    validate_backup_path,
    verify_backup,
)

MIGRATION_BASELINE = ROOT / "database" / "migrations" / "004_worker_credentials.sql"
MIGRATION_UNDER_TEST = ROOT / "database" / "migrations" / "017_worker_credential_expiry.sql"
SCRATCH_IMAGE = (
    "postgres:16-alpine@sha256:"
    "0cefaabd882e42bcb2a2f3dc56d3ce4770560ba62fd7f197f1a2e008fd5731ab"
)
SCRATCH_NAME_PATTERN = re.compile(r"^floppi-worker-expiry-scratch-[0-9a-f]{16}$")


def _run_docker(
    arguments: list[str],
    *,
    stdin: BinaryIO | None = None,
    input_data: bytes | None = None,
    timeout: int = 300,
) -> str:
    if stdin is not None and input_data is not None:
        raise ValueError("Provide either an input stream or input bytes, not both.")
    input_options = {"stdin": stdin} if stdin is not None else {"input": input_data}
    text_mode = stdin is None and input_data is None
    try:
        result = subprocess.run(
            ["docker", *arguments],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=text_mode,
            check=False,
            timeout=timeout,
            **input_options,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("The isolated migration scratch operation did not complete.") from exc
    if result.returncode:
        raise RuntimeError("The isolated migration scratch operation failed; details are suppressed.")
    if isinstance(result.stdout, bytes):
        return result.stdout.decode("utf-8", errors="strict")
    return result.stdout


def _scratch_psql(
    container_name: str, sql: str, *, stdin: BinaryIO | None = None
) -> str:
    command = [
        "exec",
        "-i",
        container_name,
        "sh",
        "-c",
        'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -h 127.0.0.1 -X '
        '-v ON_ERROR_STOP=1 -A -t -F "|" -U "$POSTGRES_USER" '
        '-d "$POSTGRES_DB" -f -',
    ]
    if stdin is not None:
        return _run_docker(command, stdin=stdin)
    return _run_docker(command, input_data=sql.encode("utf-8"))


def _wait_for_scratch(container_name: str) -> None:
    for _ in range(60):
        try:
            _run_docker(
                [
                    "exec",
                    container_name,
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    "floppi_staging",
                    "-d",
                    "floppi_staging",
                ],
                timeout=10,
            )
        except RuntimeError:
            time.sleep(1)
        else:
            return
    raise RuntimeError("The isolated migration scratch database did not become ready.")


def _start_scratch(container_name: str, env_file: Path) -> None:
    _run_docker(
        [
            "run",
            "--detach",
            "--network",
            "none",
            "--name",
            container_name,
            "--tmpfs",
            "/var/lib/postgresql/data:rw,noexec,nosuid,size=256m",
            "--env-file",
            str(env_file),
            SCRATCH_IMAGE,
        ]
    )
    try:
        runtime = _run_docker(
            [
                "inspect",
                "--format",
                "{{.HostConfig.NetworkMode}}|{{json .HostConfig.PortBindings}}|"
                "{{json .HostConfig.Binds}}|{{json .HostConfig.Tmpfs}}",
                container_name,
            ]
        ).strip().split("|", 3)
        if (
            len(runtime) != 4
            or runtime[0] != "none"
            or json.loads(runtime[1]) not in ({}, None)
            or json.loads(runtime[2]) not in ([], None)
            or not json.loads(runtime[3])
        ):
            raise ValueError(
                "Scratch container is not isolated from networks, ports, or persistent mounts."
            )
        _wait_for_scratch(container_name)
    except (RuntimeError, ValueError, json.JSONDecodeError, KeyboardInterrupt):
        _run_docker(["rm", "--force", container_name])
        raise


def _restore_backup(container_name: str, backup_path: Path) -> None:
    with backup_path.open("rb") as backup:
        _run_docker(
            [
                "exec",
                "-i",
                container_name,
                "sh",
                "-c",
                'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_restore --exit-on-error '
                '--no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"',
            ],
            stdin=backup,
        )


def _create_supabase_roles(container_name: str) -> None:
    _scratch_psql(
        container_name,
        """
DO $roles$
BEGIN
    CREATE ROLE anon NOLOGIN;
    CREATE ROLE authenticated NOLOGIN;
    CREATE ROLE service_role NOLOGIN BYPASSRLS;
END
$roles$;
""",
    )


def _ensure_baseline_schema(container_name: str) -> None:
    output = _scratch_psql(
        container_name,
        "SELECT to_regclass('public.worker_credentials') IS NOT NULL;",
    ).strip()
    if output == "f":
        _apply_migration_file(container_name, MIGRATION_BASELINE)
    elif output != "t":
        raise ValueError("Scratch worker_credentials existence check returned an unexpected result.")


def _apply_migration_file(container_name: str, migration_path: Path) -> None:
    with migration_path.open("rb") as migration:
        _scratch_psql(container_name, "", stdin=migration)


def _seed_test_credentials(container_name: str, node_tag: str) -> None:
    token_hashes = [secrets.token_hex(32) for _ in range(4)]
    sql = f"""
INSERT INTO public.worker_credentials
    (node_id, token_hash, active, created_at, expires_at, revoked_at)
VALUES
    ('{node_tag}-active-legacy', '{token_hashes[0]}', true, now(), NULL, NULL),
    ('{node_tag}-inactive-legacy', '{token_hashes[1]}', false, now(), NULL, NULL),
    ('{node_tag}-revoked-legacy', '{token_hashes[2]}', false, now(), NULL, '2020-01-01T00:00:00Z'),
    ('{node_tag}-valid-active', '{token_hashes[3]}', true, now(), '2099-12-31T23:59:59Z', NULL);
"""
    _scratch_psql(container_name, sql)


def _assert_schema_before_migration(container_name: str) -> None:
    output = _scratch_psql(
        container_name,
        """
SELECT column_name || '|' || data_type || '|' || is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'worker_credentials'
ORDER BY ordinal_position;
SELECT column_name || '|' || COALESCE(column_default, '')
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'worker_credentials'
ORDER BY ordinal_position;
SELECT relrowsecurity::text || '|' || relforcerowsecurity::text
FROM pg_class WHERE oid = 'public.worker_credentials'::regclass;
SELECT indexname FROM pg_indexes
WHERE schemaname = 'public' AND tablename = 'worker_credentials'
ORDER BY indexname;
SELECT conname FROM pg_constraint
WHERE conrelid = 'public.worker_credentials'::regclass
ORDER BY conname;
SELECT count(*)::text FROM pg_trigger
WHERE tgrelid = 'public.worker_credentials'::regclass AND NOT tgisinternal;
SELECT grantee || '|' || privilege_type
FROM information_schema.role_table_grants
WHERE table_schema = 'public' AND table_name = 'worker_credentials'
ORDER BY grantee, privilege_type;
"""
    )
    lines = [line for line in output.splitlines() if line.strip()]
    column_specs = [line for line in lines if line.count("|") == 2]
    columns = {line.split("|")[0]: line for line in column_specs}
    expected_columns = {
        "id": "id|uuid|NO",
        "node_id": "node_id|text|NO",
        "token_hash": "token_hash|text|NO",
        "active": "active|boolean|NO",
        "created_at": "created_at|timestamp with time zone|NO",
        "expires_at": "expires_at|timestamp with time zone|YES",
        "last_used_at": "last_used_at|timestamp with time zone|YES",
        "revoked_at": "revoked_at|timestamp with time zone|YES",
    }
    if columns != expected_columns:
        raise ValueError("Scratch worker_credentials schema does not match the migration 004 baseline.")
    if not any(line == "true|false" for line in lines):
        raise ValueError("Scratch worker_credentials RLS does not match the migration 004 baseline.")
    if not {
        "worker_credentials_node_id_idx",
        "worker_credentials_active_idx",
        "worker_credentials_pkey",
        "worker_credentials_token_hash_key",
    }.issubset(lines):
        raise ValueError("Scratch worker_credentials indexes do not match the migration 004 baseline.")
    if not {
        "worker_credentials_pkey",
        "worker_credentials_token_hash_key",
        "worker_credentials_node_id_check",
        "worker_credentials_revoked_inactive",
    }.issubset(lines):
        raise ValueError("Scratch worker_credentials constraints do not match the migration 004 baseline.")
    if not any(line == "0" for line in lines):
        raise ValueError("Unexpected user trigger exists on scratch worker_credentials.")
    if not {"service_role|SELECT", "service_role|UPDATE", "service_role|INSERT"}.issubset(lines):
        raise ValueError("Scratch worker_credentials grants do not match the migration 004 baseline.")
    if any(line.startswith(("anon|", "authenticated|", "PUBLIC|")) for line in lines):
        raise ValueError("Scratch worker_credentials grants expose access to client roles.")


def _read_affected_counts(container_name: str) -> tuple[int, int]:
    output = _scratch_psql(
        container_name,
        "SELECT count(*)::text || '|' || "
        "count(*) FILTER (WHERE expires_at IS NULL)::text || '|' || "
        "count(*) FILTER (WHERE expires_at IS NULL AND active)::text "
        "FROM public.worker_credentials;",
    ).strip()
    parts = output.split("|")
    if len(parts) != 3:
        raise ValueError("Scratch migration preflight returned an unexpected count.")
    return int(parts[1]), int(parts[2])


def _snapshot_pre_migration_state(container_name: str) -> None:
    _scratch_psql(
        container_name,
        """
CREATE TABLE public._migration017_preexisting_null_expiry AS
SELECT id, active, revoked_at
FROM public.worker_credentials
WHERE expires_at IS NULL;
CREATE TABLE public._migration017_preexisting_valid_expiry AS
SELECT id, active, expires_at, revoked_at
FROM public.worker_credentials
WHERE expires_at IS NOT NULL;
""",
    )


def _assert_migration_results(
    container_name: str, node_tag: str, rejected_token_hash: str
) -> None:
    sql = f"""
DO $assertions$
DECLARE
    null_expiries bigint;
    active_legacy bigint;
    revoked_legacy bigint;
    active_valid bigint;
    preserved_revocation timestamptz;
    expiry_nullable text;
    preexisting_null_invalid bigint;
    preexisting_valid_changed bigint;
BEGIN
    SELECT count(*) INTO null_expiries
    FROM public.worker_credentials WHERE expires_at IS NULL;
    SELECT count(*) INTO active_legacy
    FROM public.worker_credentials
    WHERE node_id = '{node_tag}-active-legacy'
      AND active = false AND revoked_at IS NOT NULL AND expires_at IS NOT NULL;
    SELECT count(*) INTO revoked_legacy
    FROM public.worker_credentials
    WHERE node_id = '{node_tag}-inactive-legacy'
      AND active = false AND revoked_at IS NOT NULL AND expires_at IS NOT NULL;
    SELECT revoked_at INTO preserved_revocation
    FROM public.worker_credentials WHERE node_id = '{node_tag}-revoked-legacy';
    SELECT count(*) INTO active_valid
    FROM public.worker_credentials
    WHERE node_id = '{node_tag}-valid-active'
      AND active = true AND revoked_at IS NULL
      AND expires_at = '2099-12-31T23:59:59Z'::timestamptz;
    SELECT is_nullable INTO expiry_nullable
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'worker_credentials'
      AND column_name = 'expires_at';
    SELECT count(*) INTO preexisting_null_invalid
    FROM public._migration017_preexisting_null_expiry s
    LEFT JOIN public.worker_credentials w ON w.id = s.id
    WHERE w.id IS NULL OR w.active OR w.revoked_at IS NULL OR w.expires_at IS NULL
       OR (s.revoked_at IS NOT NULL AND w.revoked_at <> s.revoked_at)
       OR (s.revoked_at IS NULL AND w.revoked_at <> w.expires_at);
    SELECT count(*) INTO preexisting_valid_changed
    FROM public._migration017_preexisting_valid_expiry s
    LEFT JOIN public.worker_credentials w ON w.id = s.id
    WHERE w.id IS NULL OR w.active IS DISTINCT FROM s.active
       OR w.expires_at IS DISTINCT FROM s.expires_at
       OR w.revoked_at IS DISTINCT FROM s.revoked_at;

    IF null_expiries <> 0 OR active_legacy <> 1 OR revoked_legacy <> 1
       OR preserved_revocation <> '2020-01-01T00:00:00Z'::timestamptz
       OR active_valid <> 1 OR expiry_nullable <> 'NO'
       OR preexisting_null_invalid <> 0 OR preexisting_valid_changed <> 0 THEN
        RAISE EXCEPTION 'Migration 017 scratch assertions failed.';
    END IF;

    BEGIN
        INSERT INTO public.worker_credentials
            (node_id, token_hash, active, expires_at)
        VALUES ('{node_tag}-null-rejected', '{rejected_token_hash}', true, NULL);
        RAISE EXCEPTION 'NOT NULL constraint accepted a null expiry.';
    EXCEPTION WHEN not_null_violation THEN
        NULL;
    END;
END
$assertions$;
DROP TABLE public._migration017_preexisting_null_expiry;
DROP TABLE public._migration017_preexisting_valid_expiry;
"""
    _scratch_psql(container_name, sql)


def _staging_fingerprint() -> str:
    config = load_and_validate_config()
    check_database(config)
    exists = _run_compose(
        [
            "exec",
            "-T",
            SERVICE,
            "sh",
            "-c",
            'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -h 127.0.0.1 -X -A -t '
            '-U "$POSTGRES_USER" -d "$POSTGRES_DB" '
            '-c "SELECT to_regclass(\'public.worker_credentials\') IS NOT NULL;"',
        ]
    ).stdout.strip()
    if exists == "f":
        return "absent"
    if exists != "t":
        raise ValueError("Staging schema check returned an unexpected result.")
    result = _run_compose(
        [
            "exec",
            "-T",
            SERVICE,
            "sh",
            "-c",
            'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -h 127.0.0.1 -X -A -t '
            '-U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "'
            "SELECT count(*)::text || '|' || "
            "md5(COALESCE((SELECT string_agg(id::text || '|' || node_id || '|' "
            "|| token_hash || '|' || active::text || '|' || created_at::text || '|' "
            "|| COALESCE(expires_at::text, 'NULL') || '|' "
            "|| COALESCE(last_used_at::text, 'NULL') || '|' "
            "|| COALESCE(revoked_at::text, 'NULL'), E'\\\\n' ORDER BY id) "
            "FROM public.worker_credentials), ''));\"",
        ]
    )
    return result.stdout.strip()


def verify_migration_on_scratch(backup_path: Path) -> tuple[int, int]:
    if not backup_path.is_absolute():
        backup_path = ROOT / backup_path
    backup_path = validate_backup_path(backup_path)
    config = load_and_validate_config()
    check_database(config)
    verify_backup(config, backup_path)
    staging_before = _staging_fingerprint()

    container_name = f"floppi-worker-expiry-scratch-{secrets.token_hex(8)}"
    node_tag = f"migration017-{secrets.token_hex(6)}"
    created = False
    try:
        with tempfile.TemporaryDirectory(prefix="floppi-migration-017-") as temp_dir:
            env_file = Path(temp_dir) / "scratch.env"
            scratch_password = secrets.token_urlsafe(48)
            env_file.write_text(
                "\n".join(
                    (
                        "POSTGRES_DB=floppi_staging",
                        "POSTGRES_USER=floppi_staging",
                        f"POSTGRES_PASSWORD={scratch_password}",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            _start_scratch(container_name, env_file)
            created = True
            _restore_backup(container_name, backup_path)

            _create_supabase_roles(container_name)
            _ensure_baseline_schema(container_name)
            _assert_schema_before_migration(container_name)
            _snapshot_pre_migration_state(container_name)

            existing_null_count, existing_active_null_count = _read_affected_counts(container_name)
            _seed_test_credentials(container_name, node_tag)
            rejected_token_hash = secrets.token_hex(32)
            null_count, active_null_count = _read_affected_counts(container_name)
            if null_count != existing_null_count + 3 or active_null_count != existing_active_null_count + 1:
                raise ValueError("Scratch legacy credential fixture did not produce expected preflight counts.")

            _apply_migration_file(container_name, MIGRATION_UNDER_TEST)
            _assert_migration_results(container_name, node_tag, rejected_token_hash)
            return existing_null_count, existing_active_null_count
    finally:
        if created:
            if not SCRATCH_NAME_PATTERN.fullmatch(container_name):
                raise ValueError("Refusing to remove a container outside the scratch naming guard.")
            existing = _run_docker(
                ["ps", "--all", "--quiet", "--filter", f"name=^{container_name}$"]
            ).strip()
            if existing:
                _run_docker(["rm", "--force", container_name])
        if _staging_fingerprint() != staging_before:
            raise RuntimeError(
                "Staging database changed during scratch verification; manual review is required."
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument(
        "--authorize-scratch-migration-017",
        action="store_true",
        help="Explicitly authorize migration 017 only in a disposable offline scratch container.",
    )
    args = parser.parse_args(argv)
    if not args.authorize_scratch_migration_017:
        parser.error(
            "Migration execution is disabled without --authorize-scratch-migration-017; "
            "only a separate disposable scratch container is permitted."
        )
    try:
        affected, active_affected = verify_migration_on_scratch(args.backup)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(
        "PASS: migration 017 verified only in an offline disposable scratch container; "
        f"preflight null-expiry rows={affected}, active rows among them={active_affected}. "
        "Original staging and production were not migrated."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
