-- FLOPPI 1.2.0: persistent, deduplicated schedules for DEMO backtests.
-- Apply after migration 012 using a Supabase admin connection.

insert into public.strategies (
    id, user_id, name, description, version, parameters,
    indicators_required, entry_conditions, exit_conditions, risk_configuration
)
values
    (
        '30000000-0000-4000-8000-000000000001', null, 'SMA Cross',
        'Educational long-only experiment using SMA crossovers.', '1.0.0',
        '{"strategy_type":"sma_cross","fast_period":20,"slow_period":50}'::jsonb,
        '["sma"]'::jsonb, '{"rule":"fast SMA crosses above slow SMA"}'::jsonb,
        '{"rule":"fast SMA crosses below slow SMA"}'::jsonb,
        '{"position_fraction":1.0}'::jsonb
    ),
    (
        '30000000-0000-4000-8000-000000000002', null, 'RSI Range',
        'Educational long-only experiment using configurable RSI thresholds.', '1.0.0',
        '{"strategy_type":"rsi","period":14,"oversold":30,"overbought":70}'::jsonb,
        '["rsi"]'::jsonb, '{"rule":"RSI crosses into the oversold range"}'::jsonb,
        '{"rule":"RSI crosses into the overbought range"}'::jsonb,
        '{"position_fraction":1.0}'::jsonb
    ),
    (
        '30000000-0000-4000-8000-000000000003', null, 'MACD Cross',
        'Educational long-only experiment using MACD and signal-line crossovers.', '1.0.0',
        '{"strategy_type":"macd","fast_period":12,"slow_period":26,"signal_period":9}'::jsonb,
        '["macd"]'::jsonb, '{"rule":"MACD crosses above its signal line"}'::jsonb,
        '{"rule":"MACD crosses below its signal line"}'::jsonb,
        '{"position_fraction":1.0}'::jsonb
    )
on conflict (id) do nothing;

create table if not exists public.scheduled_tasks (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references auth.users(id) on delete cascade,
    name text not null check (length(name) between 2 and 100),
    strategy_id uuid not null references public.strategies(id) on delete restrict,
    asset_id uuid not null references public.assets(id) on delete restrict,
    timeframe text not null check (timeframe in ('1m', '5m', '15m', '1h', '4h', '1d', '1w')),
    start_date timestamptz not null,
    end_date timestamptz not null,
    initial_capital numeric(28, 12) not null check (initial_capital > 0),
    parameters jsonb not null default '{}'::jsonb check (jsonb_typeof(parameters) = 'object'),
    data_fingerprint text not null check (length(data_fingerprint) = 64),
    interval_seconds integer not null check (interval_seconds between 60 and 2592000),
    priority smallint not null default 5 check (priority between 1 and 10),
    max_concurrency smallint not null default 1 check (max_concurrency between 1 and 4),
    max_attempts smallint not null default 3 check (max_attempts between 1 and 10),
    enabled boolean not null default true,
    next_run_at timestamptz not null,
    last_run_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    cancelled_at timestamptz,
    check (end_date > start_date)
);

alter table public.scheduled_tasks enable row level security;
revoke all on table public.scheduled_tasks from public, anon, authenticated;
grant select, insert, update on table public.scheduled_tasks to service_role;

create index if not exists scheduled_tasks_due_idx
    on public.scheduled_tasks (next_run_at, id)
    where enabled;

create or replace function public.enforce_scheduled_task_limit()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    if new.enabled then
        perform pg_advisory_xact_lock(
            1128351536,
            hashtext(coalesce(new.user_id::text, 'demo'))
        );
        if (
            select count(*)
            from public.scheduled_tasks
            where user_id is not distinct from new.user_id
              and enabled
              and id <> new.id
        ) >= 10 then
            raise exception 'An account may have at most 10 active schedules.';
        end if;
    end if;
    return new;
end;
$$;
revoke all on function public.enforce_scheduled_task_limit()
    from public, anon, authenticated;

drop trigger if exists scheduled_tasks_enforce_limit on public.scheduled_tasks;
create trigger scheduled_tasks_enforce_limit
    before insert or update of enabled on public.scheduled_tasks
    for each row execute function public.enforce_scheduled_task_limit();

alter table public.backtest_runs
    add column if not exists priority smallint not null default 5
        check (priority between 1 and 10),
    add column if not exists scheduled_task_id uuid
        references public.scheduled_tasks(id) on delete set null,
    add column if not exists scheduled_for timestamptz;

alter table public.backtest_runs
    drop constraint if exists backtest_runs_status_check;
alter table public.backtest_runs
    add constraint backtest_runs_status_check
        check (status in ('pending', 'running', 'completed', 'failed', 'cancelled'));

create unique index if not exists backtest_runs_schedule_slot_idx
    on public.backtest_runs (scheduled_task_id, scheduled_for)
    where scheduled_task_id is not null and scheduled_for is not null;

create index if not exists backtest_runs_priority_queue_idx
    on public.backtest_runs (priority desc, created_at, id)
    where status in ('pending', 'running');

create or replace function public.dispatch_due_scheduled_tasks(p_limit integer default 20)
returns setof public.backtest_runs
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    scheduled public.scheduled_tasks;
    queued public.backtest_runs;
    due_slot timestamptz;
    next_slot timestamptz;
    has_capacity boolean;
    did_enqueue boolean;
    processed integer := 0;
begin
    if p_limit < 1 or p_limit > 100 then
        raise exception 'Dispatch limit must be between 1 and 100.';
    end if;

    for scheduled in
        select *
        from public.scheduled_tasks
        where enabled and next_run_at <= now()
        order by next_run_at, id
        for update skip locked
        limit p_limit
    loop
        processed := processed + 1;
        due_slot := scheduled.next_run_at;
        select count(*) < scheduled.max_concurrency
        into has_capacity
        from public.backtest_runs
        where scheduled_task_id = scheduled.id
          and status in ('pending', 'running');

        did_enqueue := false;
        if has_capacity then
            insert into public.backtest_runs (
                user_id, strategy_id, asset_id, timeframe, start_date, end_date,
                initial_capital, parameters, data_fingerprint, status, priority,
                max_attempts, scheduled_task_id, scheduled_for
            )
            values (
                scheduled.user_id, scheduled.strategy_id, scheduled.asset_id,
                scheduled.timeframe, scheduled.start_date, scheduled.end_date,
                scheduled.initial_capital, scheduled.parameters,
                scheduled.data_fingerprint, 'pending', scheduled.priority,
                scheduled.max_attempts, scheduled.id, due_slot
            )
            on conflict (scheduled_task_id, scheduled_for)
                where scheduled_task_id is not null and scheduled_for is not null
                do nothing
            returning * into queued;
            did_enqueue := found;
        end if;

        next_slot := due_slot + make_interval(secs => scheduled.interval_seconds);
        if next_slot <= now() then
            next_slot := now() + make_interval(secs => scheduled.interval_seconds);
        end if;
        update public.scheduled_tasks
        set next_run_at = next_slot,
            last_run_at = case when did_enqueue then due_slot else last_run_at end,
            updated_at = now()
        where id = scheduled.id;

        if did_enqueue then
            return next queued;
        end if;
    end loop;
    return;
end;
$$;
revoke all on function public.dispatch_due_scheduled_tasks(integer)
    from public, anon, authenticated;
grant execute on function public.dispatch_due_scheduled_tasks(integer)
    to service_role;

create or replace function public.cancel_scheduled_task(p_task_id uuid, p_user_id uuid)
returns setof public.scheduled_tasks
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    cancelled public.scheduled_tasks;
begin
    update public.scheduled_tasks
    set enabled = false,
        cancelled_at = now(),
        updated_at = now()
    where id = p_task_id
      and user_id is not distinct from p_user_id
    returning * into cancelled;

    if not found then
        return;
    end if;

    update public.backtest_runs
    set status = 'cancelled',
        completed_at = now(),
        error_message = 'Cancelled by the schedule owner before execution.'
    where scheduled_task_id = p_task_id
      and user_id is not distinct from p_user_id
      and status = 'pending';

    return next cancelled;
end;
$$;
revoke all on function public.cancel_scheduled_task(uuid, uuid)
    from public, anon, authenticated;
grant execute on function public.cancel_scheduled_task(uuid, uuid)
    to service_role;

create or replace function public.claim_backtest_run(p_node_id text)
returns setof public.backtest_runs
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    claimed public.backtest_runs;
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

    with candidate as (
        select id
        from public.backtest_runs
        where (
            status = 'pending'
            and (retry_after is null or retry_after <= now())
        ) or (
            status = 'running'
            and lease_expires_at is not null
            and lease_expires_at <= now()
            and attempt_count < max_attempts
        )
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
    return next claimed;
end;
$$;
revoke all on function public.claim_backtest_run(text)
    from public, anon, authenticated;
grant execute on function public.claim_backtest_run(text)
    to service_role;
