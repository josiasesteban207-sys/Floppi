-- FLOPPI 0.2 initial schema for Supabase PostgreSQL.
-- Apply in Supabase SQL Editor. Review RLS policies before production use.

create extension if not exists pgcrypto;

create table if not exists public.node_status (
    node_id text primary key,
    node_name text not null,
    capabilities jsonb not null default '[]'::jsonb,
    status text not null default 'offline'
        check (status in ('online', 'idle', 'offline')),
    last_seen timestamptz not null default now()
);

create table if not exists public.notification_preferences (
    user_id uuid primary key references auth.users(id) on delete cascade,
    market_alerts boolean not null default true,
    experiment_completed boolean not null default true,
    node_offline boolean not null default true,
    system_warnings boolean not null default true,
    channel_app boolean not null default true,
    channel_telegram boolean not null default false,
    quiet_hours_enabled boolean not null default false,
    quiet_hours_start time not null default '22:00',
    quiet_hours_end time not null default '07:00',
    updated_at timestamptz not null default now()
);

create table if not exists public.system_events (
    id uuid primary key default gen_random_uuid(),
    event_type text not null,
    severity text not null default 'info'
        check (severity in ('info', 'warning', 'critical')),
    message text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

alter table public.node_status enable row level security;
alter table public.notification_preferences enable row level security;
alter table public.system_events enable row level security;

create policy "Users read own notification preferences"
on public.notification_preferences for select
to authenticated
using (auth.uid() = user_id);

create policy "Users update own notification preferences"
on public.notification_preferences for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create policy "Users insert own notification preferences"
on public.notification_preferences for insert
to authenticated
with check (auth.uid() = user_id);

-- Node status and system events are server-managed.
-- No client-facing policies are intentionally added here.;
