create index if not exists backtest_runs_worker_latency_idx on public.backtest_runs(node_id,completed_at desc) where node_id is not null and status='completed';
create index if not exists backtest_runs_worker_active_idx on public.backtest_runs(node_id,lease_expires_at) where node_id is not null and status='running';
create index if not exists backtest_runs_worker_started_idx on public.backtest_runs(started_at desc) where node_id is not null;
create or replace function public.claim_backtest_run(p_node_id text) returns setof public.backtest_runs language plpgsql security definer set search_path=public,pg_temp as $$
declare claimed public.backtest_runs; selected_node text;
begin
 update public.backtest_runs set status='failed',error_message=coalesce(last_error,'Worker lease expired after maximum attempts.'),completed_at=now(),node_id=null,lease_token=null,lease_expires_at=null
 where status='running' and lease_expires_at is not null and lease_expires_at<=now() and attempt_count>=max_attempts;
 select node.node_id into selected_node from public.node_status as node
 cross join lateral(select case when jsonb_typeof(node.resource_metrics->'cpu_percent')='number' and (node.resource_metrics->>'cpu_percent')~'^[0-9]+([.][0-9]+)?$' then (node.resource_metrics->>'cpu_percent')::numeric else null end as cpu_percent,
 case when jsonb_typeof(node.resource_metrics->'memory_percent')='number' and (node.resource_metrics->>'memory_percent')~'^[0-9]+([.][0-9]+)?$' then (node.resource_metrics->>'memory_percent')::numeric else null end as memory_percent) as resources
 left join lateral(select avg(extract(epoch from(recent.completed_at-recent.started_at))*1000) as average_ms from(
 select run.started_at,run.completed_at from public.backtest_runs as run where run.node_id=node.node_id and run.status='completed' and run.started_at is not null and run.completed_at>run.started_at order by run.completed_at desc limit 20) as recent) as latency on true
 where node.status in('online','idle') and node.last_seen>=now()-interval '90 seconds'
 and node.metrics_collected_at>=now()-interval '90 seconds' and node.metrics_collected_at<=now()+interval '30 seconds'
 and resources.cpu_percent between 0 and 100 and resources.memory_percent between 0 and 100
 and node.active_job_id is null and not exists(select 1 from public.backtest_runs as active where active.node_id=node.node_id and active.status='running' and active.lease_expires_at>now())
 order by (resources.cpu_percent is null or resources.memory_percent is null),
 coalesce(resources.cpu_percent,0)+coalesce(resources.memory_percent,0)+coalesce(latency.average_ms/1000,0),
 latency.average_ms nulls last,node.last_seen desc,node.node_id
 for update of node skip locked limit 1;
 if selected_node is null or selected_node<>p_node_id then return; end if;
 with candidate as(select id from public.backtest_runs where(status='pending' and(retry_after is null or retry_after<=now()))
 or(status='running' and lease_expires_at is not null and lease_expires_at<=now() and attempt_count<max_attempts)
 order by priority desc,created_at,id for update skip locked limit 1)
 update public.backtest_runs as run set status='running',node_id=p_node_id,started_at=now(),claimed_at=now(),
 lease_expires_at=now()+interval '5 minutes',lease_token=gen_random_uuid(),attempt_count=run.attempt_count+1,retry_after=null,last_error=null
 from candidate where run.id=candidate.id returning run.* into claimed;
 if not found then return; end if;
 update public.node_status set status='busy',active_job_id=claimed.id::text where node_id=p_node_id;
 return next claimed;
end; $$;
revoke all on function public.claim_backtest_run(text) from public,anon,authenticated;
grant execute on function public.claim_backtest_run(text) to service_role;;
