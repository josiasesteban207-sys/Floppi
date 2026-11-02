begin;

update public.worker_credentials
set active = false,
    revoked_at = coalesce(revoked_at, now()),
    expires_at = now()
where expires_at is null;
alter table public.worker_credentials
    alter column expires_at set not null;

commit;
