create table if not exists public.system_health_observations (
 sample_bucket timestamptz not null, sampled_at timestamptz not null,
 overall_status text not null check(overall_status in ('healthy','degraded','unhealthy')),
 component_statuses jsonb not null check(jsonb_typeof(component_statuses)='object'),
 worker_statuses jsonb not null check(jsonb_typeof(worker_statuses)='object'),
 task_counts jsonb not null check(jsonb_typeof(task_counts)='object'),
 resource_metrics jsonb, created_at timestamptz not null default now()
);
alter table public.system_health_observations add column if not exists resource_metrics jsonb;
alter table public.system_health_observations add column if not exists sample_bucket timestamptz;
alter table public.system_health_observations add column if not exists sampled_at timestamptz;
update public.system_health_observations set sampled_at=coalesce(sampled_at,created_at) where sampled_at is null;
update public.system_health_observations set sample_bucket=to_timestamp(floor(extract(epoch from sampled_at)/300)*300) where sample_bucket is null;
alter table public.system_health_observations alter column sampled_at set not null, alter column sample_bucket set not null;
create unique index if not exists system_health_observations_sample_bucket_key on public.system_health_observations(sample_bucket);
create index if not exists system_health_observations_sampled_at_idx on public.system_health_observations(sampled_at desc);
alter table public.system_health_observations drop constraint if exists system_health_observations_resource_metrics_object_check;
alter table public.system_health_observations add constraint system_health_observations_resource_metrics_object_check check(resource_metrics is null or jsonb_typeof(resource_metrics)='object');
alter table public.system_health_observations enable row level security;
revoke all on table public.system_health_observations from anon,authenticated;
grant select,insert on table public.system_health_observations to service_role;;
