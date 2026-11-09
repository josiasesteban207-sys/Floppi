-- FLOPPI staging hardening: least-privilege table grants, RLS initplans,
-- covering FK indexes, and a primary key for health observations.
-- Intended only for project FLOPPI-STAGING.

-- 1) Remove broad default client grants from existing public tables.
revoke all privileges on all tables in schema public from anon, authenticated;

-- Explicit public read-only market catalogue and candle history.
grant select on public.markets, public.assets, public.market_candles to anon, authenticated;

-- Authenticated users may access only their own application records through RLS.
grant select, insert, update on public.notification_preferences to authenticated;
grant select, insert, update on public.strategies to authenticated;
grant select, insert on public.backtest_runs to authenticated;
grant select on public.backtest_trades, public.backtest_metrics to authenticated;

-- No direct client table access to server-managed operational data.
revoke all privileges on public.node_status, public.data_providers, public.ingestion_jobs,
 public.data_quality_logs, public.worker_credentials, public.system_health_observations,
 public.diagnostic_incidents, public.scheduled_tasks, public.system_events,
 public.hybrid_signal_history from anon, authenticated;

-- Prevent future tables created by postgres in public from inheriting broad client grants.
alter default privileges for role postgres in schema public
 revoke all on tables from anon, authenticated;

-- 2) Optimize auth.uid() policies to evaluate once per statement.
drop policy if exists "Users read own notification preferences" on public.notification_preferences;
create policy "Users read own notification preferences"
 on public.notification_preferences for select to authenticated
 using (user_id = (select auth.uid()));
drop policy if exists "Users update own notification preferences" on public.notification_preferences;
create policy "Users update own notification preferences"
 on public.notification_preferences for update to authenticated
 using (user_id = (select auth.uid()))
 with check (user_id = (select auth.uid()));
drop policy if exists "Users insert own notification preferences" on public.notification_preferences;
create policy "Users insert own notification preferences"
 on public.notification_preferences for insert to authenticated
 with check (user_id = (select auth.uid()));

drop policy if exists "Users read own strategies" on public.strategies;
create policy "Users read own strategies"
 on public.strategies for select to authenticated
 using (user_id is null or user_id = (select auth.uid()));
drop policy if exists "Users create own strategies" on public.strategies;
create policy "Users create own strategies"
 on public.strategies for insert to authenticated
 with check (user_id = (select auth.uid()));
drop policy if exists "Users update own strategies" on public.strategies;
create policy "Users update own strategies"
 on public.strategies for update to authenticated
 using (user_id = (select auth.uid()))
 with check (user_id = (select auth.uid()));

drop policy if exists "Users read own backtest runs" on public.backtest_runs;
create policy "Users read own backtest runs"
 on public.backtest_runs for select to authenticated
 using (user_id = (select auth.uid()));
drop policy if exists "Users create own backtest runs" on public.backtest_runs;
create policy "Users create own backtest runs"
 on public.backtest_runs for insert to authenticated
 with check (user_id = (select auth.uid()));

drop policy if exists "Users read own backtest trades" on public.backtest_trades;
create policy "Users read own backtest trades"
 on public.backtest_trades for select to authenticated
 using (exists (
  select 1 from public.backtest_runs r
  where r.id = backtest_trades.run_id and r.user_id = (select auth.uid())
 ));
drop policy if exists "Users read own backtest metrics" on public.backtest_metrics;
create policy "Users read own backtest metrics"
 on public.backtest_metrics for select to authenticated
 using (exists (
  select 1 from public.backtest_runs r
  where r.id = backtest_metrics.run_id and r.user_id = (select auth.uid())
 ));

-- 3) Cover the seven foreign keys reported by the database advisor.
create index if not exists idx_backtest_runs_asset_id on public.backtest_runs(asset_id);
create index if not exists idx_backtest_runs_strategy_id on public.backtest_runs(strategy_id);
create index if not exists idx_data_quality_logs_candle_id on public.data_quality_logs(candle_id);
create index if not exists idx_ingestion_jobs_provider_id on public.ingestion_jobs(provider_id);
create index if not exists idx_scheduled_tasks_asset_id on public.scheduled_tasks(asset_id);
create index if not exists idx_scheduled_tasks_strategy_id on public.scheduled_tasks(strategy_id);
create index if not exists idx_scheduled_tasks_user_id on public.scheduled_tasks(user_id);

-- 4) Give health observations a stable row identity while retaining bucket uniqueness.
alter table public.system_health_observations
 add column if not exists id uuid default gen_random_uuid();
update public.system_health_observations set id=gen_random_uuid() where id is null;
alter table public.system_health_observations alter column id set default gen_random_uuid();
alter table public.system_health_observations alter column id set not null;
do $$
begin
 if not exists (
  select 1 from pg_constraint
  where conrelid='public.system_health_observations'::regclass and contype='p'
 ) then
  alter table public.system_health_observations
   add constraint system_health_observations_pkey primary key(id);
 end if;
end; $$;;
