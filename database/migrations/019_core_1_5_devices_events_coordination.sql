-- FLOPPI Core 1.5 proposal. New migration 019; prepared only, not applied. Staging migration 018 is distinct and is left unchanged.
create table if not exists public.client_devices (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users(id) on delete cascade,
    node_id text not null unique,
    device_name text not null check (length(device_name) between 1 and 80),
    platform text not null check (platform in ('web','windows','macos','linux','android','ios')),
    client_version text not null,
    capabilities jsonb not null default '[]'::jsonb check (jsonb_typeof(capabilities) = 'array'),
    status text not null default 'offline' check (status in ('online','offline','revoked')),
    resource_metrics jsonb not null default '{}'::jsonb check (jsonb_typeof(resource_metrics) = 'object'),
    last_seen timestamptz,
    last_connected_at timestamptz,
    last_heartbeat_at timestamptz,
    connection_instance_id text,
    connection_lease_expires_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists client_devices_owner_created_idx on public.client_devices(owner_id, created_at desc);
create index if not exists client_devices_online_idx on public.client_devices(last_seen desc) where status = 'online' and revoked_at is null;
alter table public.client_devices enable row level security;
revoke all on public.client_devices from public, anon, authenticated;
grant select, insert, update on public.client_devices to service_role;

alter table public.backtest_runs add column if not exists assigned_device_id uuid references public.client_devices(id) on delete set null;
alter table public.backtest_runs drop constraint if exists backtest_runs_status_check;
alter table public.backtest_runs add constraint backtest_runs_status_check
    check (status in ('pending', 'running', 'completed', 'failed', 'cancelled', 'paused'));
create index if not exists backtest_runs_assigned_pending_idx on public.backtest_runs(assigned_device_id, priority desc, created_at) where status = 'pending';

create or replace function public.revoke_client_device(p_device_id uuid, p_user_id uuid)
returns setof public.client_devices language plpgsql security invoker
set search_path = public, pg_temp as $$
declare revoked_device public.client_devices;
begin
    update public.client_devices d set status='revoked', revoked_at=now(), updated_at=now()
      where d.id=p_device_id and d.owner_id=p_user_id and d.revoked_at is null
      returning d.* into revoked_device;
    if not found then return; end if;
    update public.backtest_runs r set assigned_device_id=null
      where r.assigned_device_id=p_device_id and r.user_id=p_user_id
        and r.status in ('pending','paused') and r.lease_token is null;
    update public.client_devices set connection_instance_id=null, connection_lease_expires_at=null
      where id=p_device_id;
    return next revoked_device;
end; $$;
revoke all on function public.revoke_client_device(uuid,uuid) from public, anon, authenticated;
grant execute on function public.revoke_client_device(uuid,uuid) to service_role;

create or replace function public.acquire_client_device_connection(p_device_id uuid, p_user_id uuid, p_instance_id text)
returns setof public.client_devices language plpgsql security invoker set search_path=public,pg_temp as $$
begin
    return query update public.client_devices d set status='online', last_connected_at=now(),
      updated_at=now(), connection_instance_id=p_instance_id,
      connection_lease_expires_at=now()+interval '90 seconds'
    where d.id=p_device_id and d.owner_id=p_user_id and d.revoked_at is null
      and (d.connection_lease_expires_at is null or d.connection_lease_expires_at<=now()
        or d.connection_instance_id=p_instance_id)
    returning d.*;
end; $$;
create or replace function public.heartbeat_client_device(
    p_device_id uuid, p_user_id uuid, p_instance_id text, p_resource_metrics jsonb
)
returns setof public.client_devices language plpgsql security invoker set search_path=public,pg_temp as $$
begin
    return query update public.client_devices d set status='online', resource_metrics=p_resource_metrics,
      last_seen=now(), last_heartbeat_at=now(), updated_at=now(),
      connection_lease_expires_at=now()+interval '90 seconds'
    where d.id=p_device_id and d.owner_id=p_user_id and d.revoked_at is null
      and d.connection_instance_id=p_instance_id and d.connection_lease_expires_at>now()
    returning d.*;
end; $$;
create or replace function public.release_client_device_connection(p_device_id uuid, p_user_id uuid, p_instance_id text)
returns void language plpgsql security invoker set search_path=public,pg_temp as $$
begin
    update public.client_devices d set status='offline', updated_at=now(),
      connection_instance_id=null, connection_lease_expires_at=null
    where d.id=p_device_id and d.owner_id=p_user_id and d.connection_instance_id=p_instance_id;
end; $$;
revoke all on function public.acquire_client_device_connection(uuid,uuid,text) from public,anon,authenticated;
revoke all on function public.heartbeat_client_device(uuid,uuid,text,jsonb) from public,anon,authenticated;
revoke all on function public.release_client_device_connection(uuid,uuid,text) from public,anon,authenticated;
grant execute on function public.acquire_client_device_connection(uuid,uuid,text) to service_role;
grant execute on function public.heartbeat_client_device(uuid,uuid,text,jsonb) to service_role;
grant execute on function public.release_client_device_connection(uuid,uuid,text) to service_role;

create or replace function public.claim_backtest_run(p_node_id text)
returns setof public.backtest_runs
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    claimed public.backtest_runs;
    selected_node text;
begin
    update public.backtest_runs
    set status = 'failed',
        error_message = coalesce(last_error, 'Worker lease expired after maximum attempts.'),
        completed_at = now(),
        node_id = null,
        lease_token = null,
        lease_expires_at = null
    where status = 'running'
      and lease_expires_at is not null
      and lease_expires_at <= now()
      and attempt_count >= max_attempts;

    select node.node_id
    into selected_node
    from public.node_status as node
    cross join lateral (
        select
            case
                when jsonb_typeof(node.resource_metrics -> 'cpu_percent') = 'number'
                 and (node.resource_metrics ->> 'cpu_percent') ~ '^[0-9]+([.][0-9]+)?$'
                    then (node.resource_metrics ->> 'cpu_percent')::numeric
                else null
            end as cpu_percent,
            case
                when jsonb_typeof(node.resource_metrics -> 'memory_percent') = 'number'
                 and (node.resource_metrics ->> 'memory_percent') ~ '^[0-9]+([.][0-9]+)?$'
                    then (node.resource_metrics ->> 'memory_percent')::numeric
                else null
            end as memory_percent
    ) as resources
    left join lateral (
        select avg(extract(epoch from (recent.completed_at - recent.started_at)) * 1000) as average_ms
        from (
            select run.started_at, run.completed_at
            from public.backtest_runs as run
            where run.node_id = node.node_id
              and run.status = 'completed'
              and run.started_at is not null
              and run.completed_at > run.started_at
            order by run.completed_at desc
            limit 20
        ) as recent
    ) as latency on true
    where node.status in ('online', 'idle')
      and node.last_seen >= now() - interval '90 seconds'
      and node.metrics_collected_at >= now() - interval '90 seconds'
      and node.metrics_collected_at <= now() + interval '30 seconds'
      and resources.cpu_percent between 0 and 100
      and resources.memory_percent between 0 and 100
      and node.active_job_id is null
      and not exists (
          select 1
          from public.backtest_runs as active
          where active.node_id = node.node_id
            and active.status = 'running'
            and active.lease_expires_at > now()
      )
    order by
        (resources.cpu_percent is null or resources.memory_percent is null),
        coalesce(resources.cpu_percent, 0) + coalesce(resources.memory_percent, 0)
            + coalesce(latency.average_ms / 1000, 0),
        latency.average_ms nulls last,
        node.last_seen desc,
        node.node_id
    for update of node skip locked
    limit 1;

    if selected_node is null or selected_node <> p_node_id then
        return;
    end if;

    with candidate as (
        select id
        from public.backtest_runs
        where assigned_device_id is null and ((
            status = 'pending'
            and (retry_after is null or retry_after <= now())
        ) or (
            status = 'running'
            and lease_expires_at is not null
            and lease_expires_at <= now()
            and attempt_count < max_attempts
        ))
        order by priority desc, created_at, id
        for update skip locked
        limit 1
    )
    update public.backtest_runs as run
    set status = 'running',
        node_id = p_node_id,
        started_at = now(),
        claimed_at = now(),
        lease_expires_at = now() + interval '5 minutes',
        lease_token = gen_random_uuid(),
        attempt_count = run.attempt_count + 1,
        retry_after = null,
        last_error = null
    from candidate
    where run.id = candidate.id
    returning run.* into claimed;

    if not found then
        return;
    end if;

    update public.node_status
    set status = 'busy',
        active_job_id = claimed.id::text
    where node_id = p_node_id;

    return next claimed;
end;
$$;

revoke all on function public.claim_backtest_run(text)
    from public, anon, authenticated;
grant execute on function public.claim_backtest_run(text)
    to service_role;

create or replace function public.assign_pending_backtest_run(p_run_id uuid, p_user_id uuid, p_device_id uuid)
returns setof public.backtest_runs language plpgsql security invoker set search_path = public, pg_temp as $$
begin
    if not exists (select 1 from public.client_devices d where d.id=p_device_id and d.owner_id=p_user_id
      and d.revoked_at is null and d.status='online' and d.last_seen >= now()-interval '90 seconds') then return; end if;
    return query update public.backtest_runs r set assigned_device_id=p_device_id
      where r.id=p_run_id and r.user_id=p_user_id and r.status='pending' and r.lease_token is null returning r.*;
end; $$;
create or replace function public.pause_pending_backtest_run(p_run_id uuid, p_user_id uuid)
returns setof public.backtest_runs language plpgsql security invoker set search_path = public, pg_temp as $$
begin
    return query update public.backtest_runs r set status='paused'
      where r.id=p_run_id and r.user_id=p_user_id and r.status='pending' and r.lease_token is null returning r.*;
end; $$;
create or replace function public.resume_paused_backtest_run(p_run_id uuid, p_user_id uuid)
returns setof public.backtest_runs language plpgsql security invoker set search_path = public, pg_temp as $$
begin
    return query update public.backtest_runs r set status='pending'
      where r.id=p_run_id and r.user_id=p_user_id and r.status='paused' and r.lease_token is null returning r.*;
end; $$;
create or replace function public.cancel_pending_backtest_run(p_run_id uuid, p_user_id uuid)
returns setof public.backtest_runs language plpgsql security invoker set search_path = public, pg_temp as $$
begin
    return query update public.backtest_runs r set status='cancelled', completed_at=now()
      where r.id=p_run_id and r.user_id=p_user_id and r.status='pending' and r.lease_token is null returning r.*;
end; $$;
create or replace function public.claim_assigned_backtest_run(p_run_id uuid, p_user_id uuid, p_device_id uuid)
returns setof public.backtest_runs language plpgsql security invoker set search_path = public, pg_temp as $$
declare claimed public.backtest_runs;
begin
    perform 1 from public.client_devices d where d.id=p_device_id and d.owner_id=p_user_id
      and d.revoked_at is null and d.status='online' and d.last_seen >= now()-interval '90 seconds'
      for update;
    if not found then return; end if;
    if exists (select 1 from public.backtest_runs active join public.client_devices dev on dev.node_id=active.node_id
      where dev.id=p_device_id and active.status='running' and active.lease_expires_at > now()) then return; end if;
    update public.backtest_runs r set status='running', node_id=d.node_id, started_at=now(), claimed_at=now(),
      lease_expires_at=now()+interval '5 minutes', lease_token=gen_random_uuid(), attempt_count=r.attempt_count+1,
      retry_after=null, last_error=null
    from public.client_devices d where r.id=p_run_id and r.user_id=p_user_id and r.assigned_device_id=p_device_id
      and r.status='pending' and r.attempt_count < r.max_attempts
      and (r.retry_after is null or r.retry_after<=now())
      and d.id=p_device_id and d.owner_id=p_user_id and d.revoked_at is null returning r.* into claimed;
    if found then return next claimed; end if;
end; $$;
revoke all on function public.assign_pending_backtest_run(uuid,uuid,uuid) from public, anon, authenticated;
revoke all on function public.cancel_pending_backtest_run(uuid,uuid) from public, anon, authenticated;
revoke all on function public.pause_pending_backtest_run(uuid,uuid) from public, anon, authenticated;
revoke all on function public.resume_paused_backtest_run(uuid,uuid) from public, anon, authenticated;
revoke all on function public.claim_assigned_backtest_run(uuid,uuid,uuid) from public, anon, authenticated;
grant execute on function public.assign_pending_backtest_run(uuid,uuid,uuid) to service_role;
grant execute on function public.cancel_pending_backtest_run(uuid,uuid) to service_role;
grant execute on function public.pause_pending_backtest_run(uuid,uuid) to service_role;
grant execute on function public.resume_paused_backtest_run(uuid,uuid) to service_role;
grant execute on function public.claim_assigned_backtest_run(uuid,uuid,uuid) to service_role;


-- Migration 019 adds a durable, user-scoped notification outbox. Realtime Broadcast
-- remains the low-latency transport; clients reconcile missed events through REST.
create table if not exists public.client_events (
    event_id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users(id) on delete cascade,
    event_type text not null check (length(event_type) between 1 and 96),
    payload jsonb not null default '{}'::jsonb check (jsonb_typeof(payload) = 'object'),
    created_at timestamptz not null default now(),
    published_at timestamptz,
    publish_attempts integer not null default 0 check (publish_attempts >= 0)
);
create index if not exists client_events_owner_created_idx
    on public.client_events(owner_id, created_at desc, event_id);
create index if not exists client_events_pending_idx
    on public.client_events(created_at, event_id) where published_at is null;
alter table public.client_events enable row level security;
revoke all on public.client_events from public, anon, authenticated;
grant select, insert, update, delete on public.client_events to service_role;

-- Idempotent compatibility for a staging DB where an earlier draft partially ran.
alter table public.client_devices add column if not exists last_connected_at timestamptz;
alter table public.client_devices add column if not exists last_heartbeat_at timestamptz;
alter table public.client_devices add column if not exists connection_instance_id text;
alter table public.client_devices add column if not exists connection_lease_expires_at timestamptz;

-- Rollback guidance: stop Core 1.5 event consumers first, then drop client_events,
-- remove assigned_device_id and client_devices only if no run references the table.
create or replace function public.prune_client_events(p_retention_days integer)
returns bigint language plpgsql security invoker set search_path = public, pg_temp as $$
declare removed_count bigint;
begin
    if p_retention_days < 1 or p_retention_days > 3650 then
        raise exception 'Retention must be between 1 and 3650 days.';
    end if;
    delete from public.client_events
    where created_at < now() - make_interval(days => p_retention_days);
    get diagnostics removed_count = row_count;
    return removed_count;
end; $$;
revoke all on function public.prune_client_events(integer) from public, anon, authenticated;
grant execute on function public.prune_client_events(integer) to service_role;

-- Reuse the existing recovery policy and release assignments whose device is no
-- longer recently online, so the existing global worker or a later manual claim
-- can make progress after lease expiry.
create or replace function public.recover_expired_backtest_runs(p_limit integer default 100)
returns setof public.backtest_runs language plpgsql security invoker
set search_path = public, pg_temp as $$
begin
    if p_limit < 1 or p_limit > 500 then
        raise exception 'Recovery limit must be between 1 and 500.';
    end if;
    return query
    with expired as (
        select run.id from public.backtest_runs run
        where run.status='running' and run.lease_expires_at is not null and run.lease_expires_at <= now()
        order by run.lease_expires_at, run.id for update skip locked limit p_limit
    )
    update public.backtest_runs run set
        status=case when run.attempt_count < run.max_attempts then 'pending' else 'failed' end,
        last_error=coalesce(run.last_error, 'Worker lease expired before the task completed.'),
        error_message=case when run.attempt_count < run.max_attempts then null
            else coalesce(run.last_error, 'Worker lease expired after maximum attempts.') end,
        last_failed_at=now(),
        retry_after=case when run.attempt_count < run.max_attempts then now() + make_interval(
            secs => least(300, 5 * power(2, greatest(0, run.attempt_count - 1))::integer)) else null end,
        completed_at=case when run.attempt_count < run.max_attempts then null else now() end,
        node_id=null, lease_token=null, lease_expires_at=null,
        assigned_device_id=case when run.assigned_device_id is not null and not exists (
            select 1 from public.client_devices d where d.id=run.assigned_device_id
              and d.owner_id=run.user_id and d.revoked_at is null and d.status='online'
              and d.last_seen >= now()-interval '90 seconds'
        ) then null else run.assigned_device_id end
    from expired where run.id=expired.id returning run.*;
end; $$;
revoke all on function public.recover_expired_backtest_runs(integer) from public, anon, authenticated;
grant execute on function public.recover_expired_backtest_runs(integer) to service_role;

create or replace function public.expire_stale_client_devices(p_stale_seconds integer default 90)
returns bigint language plpgsql security invoker set search_path=public,pg_temp as $$
declare changed_count bigint;
begin
    if p_stale_seconds < 30 or p_stale_seconds > 300 then
        raise exception 'Stale device timeout must be between 30 and 300 seconds.';
    end if;
    update public.client_devices d set status='offline', updated_at=now(),
      connection_instance_id=null, connection_lease_expires_at=null
    where d.status='online' and d.revoked_at is null and (
      (d.connection_lease_expires_at is not null and d.connection_lease_expires_at<=now())
      or (d.connection_lease_expires_at is null and
        (d.last_seen is null or d.last_seen < now()-make_interval(secs=>p_stale_seconds)))
    );
    get diagnostics changed_count = row_count;
    return changed_count;
end; $$;
revoke all on function public.expire_stale_client_devices(integer) from public,anon,authenticated;
grant execute on function public.expire_stale_client_devices(integer) to service_role;
