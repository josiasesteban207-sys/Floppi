-- FLOPPI 0.3.1-0.4.0 multimarket data and paper backtesting schema.
create extension if not exists pgcrypto;
create table if not exists public.markets (
 id uuid primary key default gen_random_uuid(), name text not null, code text not null unique,
 description text not null default '', enabled boolean not null default true, created_at timestamptz not null default now()
);
create table if not exists public.assets (
 id uuid primary key default gen_random_uuid(), symbol text not null, name text not null,
 market_id uuid not null references public.markets(id) on delete restrict,
 base_currency text, quote_currency text, enabled boolean not null default true,
 created_at timestamptz not null default now(), unique (market_id, symbol)
);
create table if not exists public.data_providers (
 id uuid primary key default gen_random_uuid(), name text not null unique,
 provider_type text not null check (provider_type in ('synthetic', 'external')),
 enabled boolean not null default true, configuration jsonb not null default '{}'::jsonb,
 created_at timestamptz not null default now()
);
create table if not exists public.market_candles (
 id uuid primary key default gen_random_uuid(), asset_id uuid not null references public.assets(id) on delete cascade,
 provider_id uuid not null references public.data_providers(id) on delete restrict,
 timeframe text not null check (timeframe in ('1m', '5m', '15m', '1h', '4h', '1d', '1w')),
 open_time timestamptz not null, close_time timestamptz not null,
 open numeric(28,12) not null check(open>0), high numeric(28,12) not null check(high>0),
 low numeric(28,12) not null check(low>0), close numeric(28,12) not null check(close>0),
 volume numeric(36,12) not null check(volume>=0), created_at timestamptz not null default now(),
 check(extract(epoch from(close_time-open_time))=case timeframe when '1m' then 60 when '5m' then 300 when '15m' then 900 when '1h' then 3600 when '4h' then 14400 when '1d' then 86400 when '1w' then 604800 end),
 check(high>=low and high>=open and high>=close), check(low<=open and low<=close),
 unique(asset_id,provider_id,timeframe,open_time)
);
create table if not exists public.ingestion_jobs (
 id uuid primary key default gen_random_uuid(), asset_id uuid not null references public.assets(id) on delete cascade,
 provider_id uuid not null references public.data_providers(id) on delete restrict,
 timeframe text not null check(timeframe in ('1m','5m','15m','1h','4h','1d','1w')),
 status text not null check(status in ('running','completed','failed')), started_at timestamptz not null default now(),
 completed_at timestamptz, records_processed integer not null default 0 check(records_processed>=0), error_message text
);
create table if not exists public.data_quality_logs (
 id uuid primary key default gen_random_uuid(), asset_id uuid not null references public.assets(id) on delete cascade,
 candle_id uuid references public.market_candles(id) on delete set null,
 severity text not null check(severity in ('info','warning','error')), description text not null, created_at timestamptz not null default now()
);
create table if not exists public.strategies (
 id uuid primary key default gen_random_uuid(), user_id uuid references auth.users(id) on delete cascade,
 name text not null, description text not null default '', version text not null default '1.0.0',
 parameters jsonb not null default '{}'::jsonb, indicators_required jsonb not null default '[]'::jsonb,
 entry_conditions jsonb not null default '{}'::jsonb, exit_conditions jsonb not null default '{}'::jsonb,
 risk_configuration jsonb not null default '{}'::jsonb, created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists public.backtest_runs (
 id uuid primary key default gen_random_uuid(), user_id uuid references auth.users(id) on delete cascade,
 strategy_id uuid not null references public.strategies(id) on delete restrict,
 asset_id uuid not null references public.assets(id) on delete restrict,
 timeframe text not null check(timeframe in ('1m','5m','15m','1h','4h','1d','1w')),
 start_date timestamptz not null, end_date timestamptz not null,
 initial_capital numeric(28,12) not null check(initial_capital>0), final_capital numeric(28,12),
 status text not null default 'pending' check(status in ('pending','running','completed','failed')),
 parameters jsonb not null default '{}'::jsonb, data_fingerprint text not null check(length(data_fingerprint)=64),
 result_summary jsonb not null default '{}'::jsonb, node_id text, error_message text,
 created_at timestamptz not null default now(), started_at timestamptz, completed_at timestamptz, check(end_date>start_date)
);
create table if not exists public.backtest_trades (
 id uuid primary key default gen_random_uuid(), run_id uuid not null references public.backtest_runs(id) on delete cascade,
 entry_time timestamptz not null, exit_time timestamptz, entry_price numeric(28,12) not null check(entry_price>0),
 exit_price numeric(28,12), quantity numeric(28,12) not null check(quantity>0), simulated_pnl numeric(28,12),
 simulated_fees numeric(28,12) not null default 0 check(simulated_fees>=0),
 result text not null check(result in ('open','win','loss','breakeven')), check(exit_time is null or exit_time>=entry_time)
);
create table if not exists public.backtest_metrics (
 run_id uuid primary key references public.backtest_runs(id) on delete cascade,
 total_return numeric(28,12) not null, max_drawdown numeric(28,12) not null,
 win_rate numeric(12,8), profit_factor numeric(28,12), sharpe_ratio numeric(28,12),
 total_trades integer not null check(total_trades>=0), winning_trades integer not null check(winning_trades>=0),
 losing_trades integer not null check(losing_trades>=0), average_gain numeric(28,12), average_loss numeric(28,12),
 created_at timestamptz not null default now()
);
create index if not exists idx_assets_market on public.assets(market_id,symbol);
create index if not exists idx_market_candles_history on public.market_candles(asset_id,timeframe,open_time);
create index if not exists idx_market_candles_provider on public.market_candles(provider_id,created_at desc);
create index if not exists idx_ingestion_jobs_asset on public.ingestion_jobs(asset_id,started_at desc);
create index if not exists idx_data_quality_asset on public.data_quality_logs(asset_id,created_at desc);
create index if not exists idx_strategies_user on public.strategies(user_id,created_at desc);
create index if not exists idx_backtest_runs_queue on public.backtest_runs(status,created_at) where status='pending';
create index if not exists idx_backtest_runs_stale on public.backtest_runs(started_at) where status='running';
create index if not exists idx_backtest_runs_user on public.backtest_runs(user_id,created_at desc);
create index if not exists idx_backtest_trades_run on public.backtest_trades(run_id,entry_time);
insert into public.markets(name,code,description) values
('Stocks','stocks','Equities and publicly traded companies.'),('ETFs','etf','Exchange-traded funds.'),
('Forex','forex','Foreign exchange currency pairs.'),('Cryptocurrency','crypto','Digital asset markets.'),
('Indices','indices','Market indices.') on conflict(code) do nothing;
insert into public.assets(symbol,name,market_id,base_currency,quote_currency)
select seed.symbol,seed.name,markets.id,seed.base_currency,seed.quote_currency from (values
('AAPL','Apple Inc. (DEMO)','stocks','AAPL','USD'),('SPY','S&P 500 ETF (DEMO)','etf','SPY','USD'),
('EURUSD','Euro / US Dollar (DEMO)','forex','EUR','USD'),('BTCUSD','Bitcoin / US Dollar (DEMO)','crypto','BTC','USD'),
('SPX','S&P 500 Index (DEMO)','indices','SPX','USD')
) as seed(symbol,name,market_code,base_currency,quote_currency) join public.markets on markets.code=seed.market_code
on conflict(market_id,symbol) do nothing;
insert into public.data_providers(id,name,provider_type,configuration) values
('00000000-0000-4000-8000-000000000001','DEMO Synthetic Provider','synthetic','{"label":"DEMO","not_real_market_data":true}'::jsonb)
on conflict(name) do nothing;
alter table public.markets enable row level security;
alter table public.assets enable row level security;
alter table public.data_providers enable row level security;
alter table public.market_candles enable row level security;
alter table public.ingestion_jobs enable row level security;
alter table public.data_quality_logs enable row level security;
alter table public.strategies enable row level security;
alter table public.backtest_runs enable row level security;
alter table public.backtest_trades enable row level security;
alter table public.backtest_metrics enable row level security;
drop policy if exists "Public read enabled markets" on public.markets;
create policy "Public read enabled markets" on public.markets for select to anon,authenticated using(enabled);
drop policy if exists "Public read enabled assets" on public.assets;
create policy "Public read enabled assets" on public.assets for select to anon,authenticated using(enabled);
drop policy if exists "Public read enabled providers" on public.data_providers;
drop policy if exists "Public read market candles" on public.market_candles;
create policy "Public read market candles" on public.market_candles for select to anon,authenticated using(true);
drop policy if exists "Users read own strategies" on public.strategies;
create policy "Users read own strategies" on public.strategies for select to authenticated using(auth.uid()=user_id);
drop policy if exists "Users create own strategies" on public.strategies;
create policy "Users create own strategies" on public.strategies for insert to authenticated with check(auth.uid()=user_id);
drop policy if exists "Users update own strategies" on public.strategies;
create policy "Users update own strategies" on public.strategies for update to authenticated using(auth.uid()=user_id) with check(auth.uid()=user_id);
drop policy if exists "Users read own backtest runs" on public.backtest_runs;
create policy "Users read own backtest runs" on public.backtest_runs for select to authenticated using(auth.uid()=user_id);
drop policy if exists "Users create own backtest runs" on public.backtest_runs;
create policy "Users create own backtest runs" on public.backtest_runs for insert to authenticated with check(auth.uid()=user_id);
drop policy if exists "Users read own backtest trades" on public.backtest_trades;
create policy "Users read own backtest trades" on public.backtest_trades for select to authenticated using(exists(select 1 from public.backtest_runs r where r.id=run_id and r.user_id=auth.uid()));
drop policy if exists "Users read own backtest metrics" on public.backtest_metrics;
create policy "Users read own backtest metrics" on public.backtest_metrics for select to authenticated using(exists(select 1 from public.backtest_runs r where r.id=run_id and r.user_id=auth.uid()));
create or replace function public.claim_backtest_run(p_node_id text)
returns setof public.backtest_runs language sql security definer set search_path=public as $$
 with candidate as (select id from public.backtest_runs where status='pending' or (status='running' and started_at<now()-interval '1 hour')
 order by created_at,id for update skip locked limit 1)
 update public.backtest_runs as run set status='running',node_id=p_node_id,started_at=now()
 from candidate where run.id=candidate.id returning run.*;
$$;
revoke all on function public.claim_backtest_run(text) from public,anon,authenticated;
grant execute on function public.claim_backtest_run(text) to service_role;
create or replace function public.complete_backtest_run(p_run_id uuid,p_node_id text,p_result jsonb)
returns setof public.backtest_runs language plpgsql security definer set search_path=public as $$
declare completed_run public.backtest_runs;
begin
 update public.backtest_runs set status='completed',final_capital=(p_result->>'final_capital')::numeric,
 result_summary=jsonb_build_object('warnings',coalesce(p_result->'warnings','[]'::jsonb),'equity_curve',coalesce(p_result->'equity_curve','[]'::jsonb),
 'methodology',coalesce(p_result->'methodology','{}'::jsonb),'disclaimer',coalesce(p_result->'disclaimer','""'::jsonb)),
 completed_at=now(),error_message=null where id=p_run_id and status='running' and node_id=p_node_id returning * into completed_run;
 if not found then return; end if;
 delete from public.backtest_trades where run_id=p_run_id;
 insert into public.backtest_trades(run_id,entry_time,exit_time,entry_price,exit_price,quantity,simulated_pnl,simulated_fees,result)
 select p_run_id,trade.entry_time,trade.exit_time,trade.entry_price,trade.exit_price,trade.quantity,trade.simulated_pnl,trade.simulated_fees,trade.result
 from jsonb_to_recordset(coalesce(p_result->'trades','[]'::jsonb)) as trade(entry_time timestamptz,exit_time timestamptz,entry_price numeric,exit_price numeric,quantity numeric,simulated_pnl numeric,simulated_fees numeric,result text);
 insert into public.backtest_metrics(run_id,total_return,max_drawdown,win_rate,profit_factor,sharpe_ratio,total_trades,winning_trades,losing_trades,average_gain,average_loss)
 select p_run_id,metric.total_return,metric.max_drawdown,metric.win_rate,metric.profit_factor,metric.sharpe_ratio,metric.total_trades,metric.winning_trades,metric.losing_trades,metric.average_gain,metric.average_loss
 from jsonb_to_record(p_result->'metrics') as metric(total_return numeric,max_drawdown numeric,win_rate numeric,profit_factor numeric,sharpe_ratio numeric,total_trades integer,winning_trades integer,losing_trades integer,average_gain numeric,average_loss numeric)
 on conflict(run_id) do update set total_return=excluded.total_return,max_drawdown=excluded.max_drawdown,win_rate=excluded.win_rate,profit_factor=excluded.profit_factor,sharpe_ratio=excluded.sharpe_ratio,total_trades=excluded.total_trades,winning_trades=excluded.winning_trades,losing_trades=excluded.losing_trades,average_gain=excluded.average_gain,average_loss=excluded.average_loss,created_at=now();
 return next completed_run;
end; $$;
revoke all on function public.complete_backtest_run(uuid,text,jsonb) from public,anon,authenticated;
grant execute on function public.complete_backtest_run(uuid,text,jsonb) to service_role;;
