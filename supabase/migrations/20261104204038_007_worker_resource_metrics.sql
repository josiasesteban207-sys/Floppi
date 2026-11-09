-- FLOPPI 1.1.1: point-in-time host resource observations from workers.
alter table public.node_status
    add column if not exists resource_metrics jsonb,
    add column if not exists metrics_collected_at timestamptz;
alter table public.node_status drop constraint if exists node_status_resource_metrics_object_check;
alter table public.node_status add constraint node_status_resource_metrics_object_check
    check (resource_metrics is null or jsonb_typeof(resource_metrics) = 'object');
create index if not exists node_status_metrics_collected_at_idx
    on public.node_status (metrics_collected_at desc)
    where metrics_collected_at is not null;;
