-- FLOPPI 0.8.0: worker runtime telemetry and explicit busy state.
-- Apply after migrations 001-004. No credentials or user secrets are stored here.
alter table public.node_status
    add column if not exists worker_version text not null default '0.7.0',
    add column if not exists python_version text not null default 'unknown',
    add column if not exists platform text not null default 'unknown',
    add column if not exists processor text not null default 'unknown',
    add column if not exists cpu_count integer not null default 1 check (cpu_count between 1 and 1024),
    add column if not exists active_job_id text;

alter table public.node_status drop constraint if exists node_status_status_check;
alter table public.node_status add constraint node_status_status_check
    check (status in ('online', 'idle', 'busy', 'offline'));

create index if not exists node_status_last_seen_idx
    on public.node_status (last_seen desc);

-- node_status remains server-managed. Do not add anon/authenticated policies.
