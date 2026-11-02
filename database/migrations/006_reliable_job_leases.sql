-- FLOPPI 0.9.0: leased jobs, bounded retries and worker ownership.
-- Apply after migrations 001-005. Run only with the Supabase SQL editor/admin role.

alter table public.backtest_runs
    add column if not exists attempt_count integer not null default 0 check (attempt_count >= 0),
    add column if not exists max_attempts integer not null default 3 check (max_attempts between 1 and 10),
    add column if not exists claimed_at timestamptz,
    add column if not exists lease_expires_at timestamptz,
    add column if not exists lease_token uuid,
    add column if not exists retry_after timestamptz,
    add column if not exists last_error text,
    add column if not exists last_failed_at timestamptz;

create index if not exists idx_backtest_runs_retry_queue
    on public.backtest_runs (status, retry_after, created_at)
    where status in ('pending', 'running');

-- Atomically claim one job. An expired lease can be reclaimed; a task is never
-- handed to two workers concurrently while its lease remains valid.
create or replace function public.claim_backtest_run(p_node_id text)
returns setof public.backtest_runs
language plpgsql
security definer
set search_path = public
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
        order by created_at, id
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
revoke all on function public.claim_backtest_run(text) from public, anon, authenticated;
grant execute on function public.claim_backtest_run(text) to service_role;

create or replace function public.renew_backtest_run_lease(
    p_run_id uuid, p_node_id text, p_lease_token uuid
)
returns setof public.backtest_runs
language sql
security definer
set search_path = public
as $$
    update public.backtest_runs
    set lease_expires_at = now() + interval '5 minutes'
    where id = p_run_id
      and status = 'running'
      and node_id = p_node_id
      and lease_token = p_lease_token
      and lease_expires_at > now()
    returning *;
$$;
revoke all on function public.renew_backtest_run_lease(uuid, text, uuid) from public, anon, authenticated;
grant execute on function public.renew_backtest_run_lease(uuid, text, uuid) to service_role;

-- Remove the legacy completion RPC so it cannot bypass lease-token ownership.
drop function if exists public.complete_backtest_run(uuid, text, jsonb);

create or replace function public.complete_backtest_run(
    p_run_id uuid, p_node_id text, p_lease_token uuid, p_result jsonb
)
returns setof public.backtest_runs
language plpgsql
security definer
set search_path = public
as $$
declare
    completed_run public.backtest_runs;
begin
    update public.backtest_runs
    set status = 'completed',
        final_capital = (p_result ->> 'final_capital')::numeric,
        result_summary = jsonb_build_object(
            'warnings', coalesce(p_result -> 'warnings', '[]'::jsonb),
            'equity_curve', coalesce(p_result -> 'equity_curve', '[]'::jsonb),
            'methodology', coalesce(p_result -> 'methodology', '{}'::jsonb),
            'disclaimer', coalesce(p_result -> 'disclaimer', '""'::jsonb)
        ),
        completed_at = now(),
        error_message = null,
        lease_token = null,
        lease_expires_at = null
    where id = p_run_id
      and status = 'running'
      and node_id = p_node_id
      and lease_token = p_lease_token
      and lease_expires_at > now()
    returning * into completed_run;

    if not found then
        return;
    end if;

    delete from public.backtest_trades where run_id = p_run_id;
    insert into public.backtest_trades (
        run_id, entry_time, exit_time, entry_price, exit_price,
        quantity, simulated_pnl, simulated_fees, result
    )
    select p_run_id, trade.entry_time, trade.exit_time, trade.entry_price,
           trade.exit_price, trade.quantity, trade.simulated_pnl,
           trade.simulated_fees, trade.result
    from jsonb_to_recordset(coalesce(p_result -> 'trades', '[]'::jsonb)) as trade(
        entry_time timestamptz, exit_time timestamptz, entry_price numeric,
        exit_price numeric, quantity numeric, simulated_pnl numeric,
        simulated_fees numeric, result text
    );

    insert into public.backtest_metrics (
        run_id, total_return, max_drawdown, win_rate, profit_factor,
        sharpe_ratio, total_trades, winning_trades, losing_trades,
        average_gain, average_loss
    )
    select p_run_id, metric.total_return, metric.max_drawdown, metric.win_rate,
           metric.profit_factor, metric.sharpe_ratio, metric.total_trades,
           metric.winning_trades, metric.losing_trades, metric.average_gain,
           metric.average_loss
    from jsonb_to_record(p_result -> 'metrics') as metric(
        total_return numeric, max_drawdown numeric, win_rate numeric,
        profit_factor numeric, sharpe_ratio numeric, total_trades integer,
        winning_trades integer, losing_trades integer, average_gain numeric,
        average_loss numeric
    )
    on conflict (run_id) do update set
        total_return = excluded.total_return,
        max_drawdown = excluded.max_drawdown,
        win_rate = excluded.win_rate,
        profit_factor = excluded.profit_factor,
        sharpe_ratio = excluded.sharpe_ratio,
        total_trades = excluded.total_trades,
        winning_trades = excluded.winning_trades,
        losing_trades = excluded.losing_trades,
        average_gain = excluded.average_gain,
        average_loss = excluded.average_loss,
        created_at = now();

    return next completed_run;
end;
$$;
revoke all on function public.complete_backtest_run(uuid, text, uuid, jsonb) from public, anon, authenticated;
grant execute on function public.complete_backtest_run(uuid, text, uuid, jsonb) to service_role;

create or replace function public.fail_backtest_run(
    p_run_id uuid, p_node_id text, p_lease_token uuid, p_error text, p_retryable boolean default true
)
returns setof public.backtest_runs
language plpgsql
security definer
set search_path = public
as $$
declare
    failed_run public.backtest_runs;
begin
    update public.backtest_runs
    set status = case when p_retryable and attempt_count < max_attempts then 'pending' else 'failed' end,
        last_error = left(p_error, 1000),
        error_message = case when p_retryable and attempt_count < max_attempts then null else left(p_error, 1000) end,
        last_failed_at = now(),
        retry_after = case
            when p_retryable and attempt_count < max_attempts
            then now() + make_interval(secs => least(300, 5 * power(2, greatest(0, attempt_count - 1))::integer))
            else null
        end,
        completed_at = case when p_retryable and attempt_count < max_attempts then null else now() end,
        node_id = null,
        lease_token = null,
        lease_expires_at = null
    where id = p_run_id
      and status = 'running'
      and node_id = p_node_id
      and lease_token = p_lease_token
      and lease_expires_at > now()
    returning * into failed_run;

    if not found then
        return;
    end if;
    return next failed_run;
end;
$$;
revoke all on function public.fail_backtest_run(uuid, text, uuid, text, boolean) from public, anon, authenticated;
grant execute on function public.fail_backtest_run(uuid, text, uuid, text, boolean) to service_role;
