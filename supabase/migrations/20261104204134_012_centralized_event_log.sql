create table if not exists public.system_events (
 event_id uuid primary key default gen_random_uuid(), occurred_at timestamptz not null default now(),
 level text not null constraint system_events_level_check check(level in ('INFO','WARNING','ERROR','CRITICAL')),
 component text not null constraint system_events_component_length_check check(length(component) between 1 and 64),
 code text not null constraint system_events_code_length_check check(length(code) between 1 and 96),
 message text not null constraint system_events_message_length_check check(length(message) between 1 and 500),
 request_id uuid, task_id uuid, metadata jsonb not null default '{}'::jsonb constraint system_events_metadata_object_check check(jsonb_typeof(metadata)='object')
);
alter table public.system_events add column if not exists event_id uuid, add column if not exists occurred_at timestamptz,
 add column if not exists level text, add column if not exists component text, add column if not exists code text,
 add column if not exists request_id uuid, add column if not exists task_id uuid;
do $$
begin
 if exists(select 1 from information_schema.columns where table_schema='public' and table_name='system_events' and column_name='id')
 and exists(select 1 from information_schema.columns where table_schema='public' and table_name='system_events' and column_name='event_type')
 and exists(select 1 from information_schema.columns where table_schema='public' and table_name='system_events' and column_name='severity')
 and exists(select 1 from information_schema.columns where table_schema='public' and table_name='system_events' and column_name='created_at') then
  execute $backfill$
   update public.system_events set event_id=coalesce(event_id,id),occurred_at=coalesce(occurred_at,created_at,now()),
   level=coalesce(level,case upper(coalesce(severity,'INFO')) when 'INFO' then 'INFO' when 'WARNING' then 'WARNING' when 'ERROR' then 'ERROR' when 'CRITICAL' then 'CRITICAL' else 'ERROR' end),
   component=coalesce(nullif(left(event_type,64),''),'legacy'),
   code=coalesce(nullif(left(regexp_replace(event_type,'[^A-Za-z0-9_.-]','_','g'),96),''),'LEGACY_EVENT'),
   message=coalesce(nullif(left(message,500),''),'Legacy event'),
   metadata=case when jsonb_typeof(metadata)='object' then metadata else '{}'::jsonb end
  $backfill$;
  alter table public.system_events alter column event_type drop not null;
  alter table public.system_events alter column severity drop not null;
 else
  update public.system_events set event_id=coalesce(event_id,gen_random_uuid()),occurred_at=coalesce(occurred_at,now()),
  level=coalesce(level,'INFO'),component=coalesce(component,'legacy'),code=coalesce(code,'LEGACY_EVENT'),
  message=coalesce(nullif(left(message,500),''),'Legacy event'),
  metadata=case when jsonb_typeof(metadata)='object' then metadata else '{}'::jsonb end;
 end if;
end; $$;
alter table public.system_events alter column event_id set default gen_random_uuid(),alter column event_id set not null,
 alter column occurred_at set default now(),alter column occurred_at set not null,alter column level set default 'INFO',
 alter column level set not null,alter column component set not null,alter column code set not null,alter column message set not null,
 alter column metadata set default '{}'::jsonb,alter column metadata set not null;
do $$
begin
 if not exists(select 1 from pg_constraint where conrelid='public.system_events'::regclass and conname='system_events_level_check') then
 alter table public.system_events add constraint system_events_level_check check(level in ('INFO','WARNING','ERROR','CRITICAL')); end if;
 if not exists(select 1 from pg_constraint where conrelid='public.system_events'::regclass and conname='system_events_component_length_check') then
 alter table public.system_events add constraint system_events_component_length_check check(length(component) between 1 and 64); end if;
 if not exists(select 1 from pg_constraint where conrelid='public.system_events'::regclass and conname='system_events_code_length_check') then
 alter table public.system_events add constraint system_events_code_length_check check(length(code) between 1 and 96); end if;
 if not exists(select 1 from pg_constraint where conrelid='public.system_events'::regclass and conname='system_events_message_length_check') then
 alter table public.system_events add constraint system_events_message_length_check check(length(message) between 1 and 500); end if;
 if not exists(select 1 from pg_constraint where conrelid='public.system_events'::regclass and conname='system_events_metadata_object_check') then
 alter table public.system_events add constraint system_events_metadata_object_check check(jsonb_typeof(metadata)='object'); end if;
end; $$;
do $$
begin
 if not exists(select 1 from pg_index i join pg_attribute a on a.attrelid=i.indrelid and a.attnum=any(i.indkey)
 where i.indrelid='public.system_events'::regclass and i.indisunique and i.indnatts=1 and a.attname='event_id') then
 create unique index system_events_event_id_uidx on public.system_events(event_id); end if;
end; $$;
create index if not exists system_events_occurred_at_idx on public.system_events(occurred_at desc,event_id);
create index if not exists system_events_component_level_time_idx on public.system_events(component,level,occurred_at desc);
create index if not exists system_events_request_id_idx on public.system_events(request_id) where request_id is not null;
create index if not exists system_events_task_id_idx on public.system_events(task_id) where task_id is not null;
alter table public.system_events enable row level security;
revoke all on table public.system_events from public,anon,authenticated;
grant select,insert on table public.system_events to service_role;
create or replace function public.prune_system_events(p_retention_days integer)
returns bigint language plpgsql security definer set search_path=public,pg_temp as $$
declare removed_count bigint;
begin
 if p_retention_days is null or p_retention_days<1 or p_retention_days>3650 then raise exception 'Retention must be between 1 and 3650 days.'; end if;
 delete from public.system_events where occurred_at<now()-make_interval(days=>p_retention_days);
 get diagnostics removed_count=row_count; return removed_count;
end; $$;
revoke all on function public.prune_system_events(integer) from public,anon,authenticated;
grant execute on function public.prune_system_events(integer) to service_role;;
