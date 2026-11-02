-- FLOPPI 1.2.2: recover expired backtest leases after worker/API interruptions.
-- Apply after migration 014. RLS and client-facing policies are unchanged.

create index if not exists backtest_runs_expired_lease_idx
    on public.backtest_runs (lease_expires_at, id)
    where status = 'running';

create or replace function public.recover_expired_backtest_runs(p_limit integer default 100)
returns setof public.backtest_runs
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    if p_limit < 1 or p_limit > 500 then
        raise exception 'Recovery limit must be between 1 and 500.';
    end if;

    return query
    with expired as (
        select run.id
        from public.backtest_runs as run
        where run.status = 'running'
          and run.lease_expires_at is not null
          and run.lease_expires_at <= now()
        order by run.lease_expires_at, run.id
        for update skip locked
        limit p_limit
    )
    update public.backtest_runs as run
    set status = case
            when run.attempt_count < run.max_attempts then 'pending'
            else 'failed'
        end,
        last_error = coalesce(run.last_error, 'Worker lease expired before the task completed.'),
        error_message = case
            when run.attempt_count < run.max_attempts then null
            else coalesce(run.last_error, 'Worker lease expired after maximum attempts.')
        end,
        last_failed_at = now(),
        retry_after = case
            when run.attempt_count < run.max_attempts
            then now() + make_interval(
                secs => least(300, 5 * power(2, greatest(0, run.attempt_count - 1))::integer)
            )
            else null
        end,
        completed_at = case
            when run.attempt_count < run.max_attempts then null
            else now()
        end,
        node_id = null,
        lease_token = null,
        lease_expires_at = null
    from expired
    where run.id = expired.id
    returning run.*;
end;
$$;

revoke all on function public.recover_expired_backtest_runs(integer)
    from public, anon, authenticated;
grant execute on function public.recover_expired_backtest_runs(integer)
    to service_role;
