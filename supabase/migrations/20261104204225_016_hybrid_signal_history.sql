create table if not exists public.hybrid_signal_history(
 id uuid primary key default gen_random_uuid(),asset_id uuid not null references public.assets(id) on delete cascade,
 timeframe text not null check(timeframe in('1m','5m','15m','1h','4h','1d','1w')),signal_at timestamptz not null,
 input_fingerprint text not null check(length(input_fingerprint)=64),sample_size integer not null check(sample_size>0),
 status text not null check(status in('concordant','provisional','abstain')),bias text not null check(bias in('bullish','bearish','undetermined')),
 agreement_ratio numeric(6,5) not null check(agreement_ratio between 0 and 1),evidence_coverage numeric(6,5) not null check(evidence_coverage between 0 and 1),
 directional_family_count smallint not null check(directional_family_count between 0 and 3),outcome_horizon_bars smallint check(outcome_horizon_bars>0),
 outcome_direction text check(outcome_direction in('aligned','opposed','flat')),outcome_change_pct numeric,outcome_close_price numeric,
 summary jsonb not null check(jsonb_typeof(summary)='object'),created_at timestamptz not null default now(),
 unique(asset_id,timeframe,signal_at),check(outcome_direction is null or bias in('bullish','bearish')),
 check((outcome_direction is null and outcome_change_pct is null and outcome_close_price is null) or
 (outcome_direction is not null and outcome_horizon_bars is not null and outcome_change_pct is not null and outcome_close_price is not null))
);
alter table public.hybrid_signal_history enable row level security;
revoke all on table public.hybrid_signal_history from public,anon,authenticated;
grant select on table public.hybrid_signal_history to service_role;
create index if not exists hybrid_signal_history_asset_time_idx on public.hybrid_signal_history(asset_id,timeframe,signal_at desc);
create or replace function public.record_hybrid_signal_history(p_rows jsonb) returns table(recorded_count integer)
language plpgsql security definer set search_path=public,pg_temp as $$
declare rows_saved integer:=0;
begin
 if p_rows is null or jsonb_typeof(p_rows)<>'array' then raise exception 'Signal history must be a JSON array.'; end if;
 if jsonb_array_length(p_rows)>1000 then raise exception 'Signal history must be an array of at most 1000 rows.'; end if;
 insert into public.hybrid_signal_history(asset_id,timeframe,signal_at,input_fingerprint,sample_size,status,bias,agreement_ratio,evidence_coverage,directional_family_count,outcome_horizon_bars,outcome_direction,outcome_change_pct,outcome_close_price,summary)
 select item.asset_id,item.timeframe,item.signal_at,item.input_fingerprint,item.sample_size,item.status,item.bias,item.agreement_ratio,item.evidence_coverage,item.directional_family_count,item.outcome_horizon_bars,item.outcome_direction,item.outcome_change_pct,item.outcome_close_price,item.summary
 from jsonb_to_recordset(p_rows) as item(asset_id uuid,timeframe text,signal_at timestamptz,input_fingerprint text,sample_size integer,status text,bias text,agreement_ratio numeric,evidence_coverage numeric,directional_family_count smallint,outcome_horizon_bars smallint,outcome_direction text,outcome_change_pct numeric,outcome_close_price numeric,summary jsonb)
 on conflict(asset_id,timeframe,signal_at) do update set outcome_horizon_bars=excluded.outcome_horizon_bars,outcome_direction=excluded.outcome_direction,outcome_change_pct=excluded.outcome_change_pct,outcome_close_price=excluded.outcome_close_price
 where public.hybrid_signal_history.outcome_direction is null and excluded.outcome_direction is not null;
 get diagnostics rows_saved=row_count; return query select rows_saved;
end; $$;
revoke all on function public.record_hybrid_signal_history(jsonb) from public,anon,authenticated;
grant execute on function public.record_hybrid_signal_history(jsonb) to service_role;;
