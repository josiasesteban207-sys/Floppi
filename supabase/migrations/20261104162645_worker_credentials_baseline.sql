-- Partial staging bootstrap: worker credentials table supplied by the project owner.
create table if not exists public.worker_credentials (
    id uuid primary key default gen_random_uuid(),
    node_id text not null check (length(node_id) between 2 and 64),
    token_hash text not null unique check (token_hash ~ '^[0-9a-f]{64}$'),
    active boolean not null default true,
    created_at timestamptz not null default now(),
    expires_at timestamptz,
    last_used_at timestamptz,
    revoked_at timestamptz,
    constraint worker_credentials_revoked_inactive
        check (revoked_at is null or active = false)
);

create index if not exists worker_credentials_node_id_idx
    on public.worker_credentials (node_id);
create index if not exists worker_credentials_active_idx
    on public.worker_credentials (token_hash)
    where active = true;

alter table public.worker_credentials enable row level security;
revoke all on public.worker_credentials from public, anon, authenticated;
grant select, update, insert on public.worker_credentials to service_role;;
