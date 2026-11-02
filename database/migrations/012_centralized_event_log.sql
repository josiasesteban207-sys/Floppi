-- FLOPPI 1.1.6: centralized, correlated, server-managed operational events.
-- Apply after migration 011 using a Supabase admin connection.
-- Event bodies, credentials, request headers and query strings are not stored.

create table if not exists public.system_events (
    event_id uuid primary key default gen_random_uuid(),
    occurred_at timestamptz not null default now(),
    level text not null
        check (level in ('INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    component text not null
        check (length(component) between 1 and 64),
    code text not null
        check (length(code) between 1 and 96),
    message text not null
        check (length(message) between 1 and 500),
    request_id uuid,
    task_id uuid,
    metadata jsonb not null default '{}'::jsonb
        check (jsonb_typeof(metadata) = 'object')
);

create index if not exists system_events_occurred_at_idx
    on public.system_events (occurred_at desc, event_id);

create index if not exists system_events_component_level_time_idx
    on public.system_events (component, level, occurred_at desc);

create index if not exists system_events_request_id_idx
    on public.system_events (request_id)
    where request_id is not null;

create index if not exists system_events_task_id_idx
    on public.system_events (task_id)
    where task_id is not null;

alter table public.system_events enable row level security;
revoke all on table public.system_events from public, anon, authenticated;
grant select, insert on table public.system_events to service_role;

create or replace function public.prune_system_events(p_retention_days integer)
returns bigint
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    removed_count bigint;
begin
    if p_retention_days < 1 or p_retention_days > 3650 then
        raise exception 'Retention must be between 1 and 3650 days.';
    end if;

    delete from public.system_events
    where occurred_at < now() - make_interval(days => p_retention_days);
    get diagnostics removed_count = row_count;
    return removed_count;
end;
$$;

revoke all on function public.prune_system_events(integer)
    from public, anon, authenticated;
grant execute on function public.prune_system_events(integer)
    to service_role;
