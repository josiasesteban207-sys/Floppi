-- FLOPPI 1.1.5: persistent incident groups derived from observed system signals.
-- Apply after the migrations in this checkout using a Supabase admin connection.
-- No client-facing policies are defined; RLS stays enabled.

create table if not exists public.diagnostic_incidents (
    id uuid primary key default gen_random_uuid(),
    fingerprint text not null unique,
    component text not null,
    code text not null,
    severity text not null
        check (severity in ('info', 'warning', 'error', 'critical')),
    description text not null,
    occurrence_count bigint not null default 1
        check (occurrence_count > 0),
    status text not null default 'open'
        check (status in ('open', 'resolved')),
    first_seen timestamptz not null,
    last_seen timestamptz not null,
    last_occurrence_key text not null,
    resolved_at timestamptz,
    resolution_note text,
    affected_components jsonb not null default '[]'::jsonb
        check (jsonb_typeof(affected_components) = 'array'),
    possible_causes jsonb not null default '[]'::jsonb
        check (jsonb_typeof(possible_causes) = 'array'),
    recommended_actions jsonb not null default '[]'::jsonb
        check (jsonb_typeof(recommended_actions) = 'array'),
    evidence jsonb not null default '{}'::jsonb
        check (jsonb_typeof(evidence) = 'object'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists diagnostic_incidents_status_severity_idx
    on public.diagnostic_incidents (status, severity, last_seen desc);

create index if not exists diagnostic_incidents_component_last_seen_idx
    on public.diagnostic_incidents (component, last_seen desc);

alter table public.diagnostic_incidents enable row level security;
revoke all on table public.diagnostic_incidents from public, anon, authenticated;
grant select on table public.diagnostic_incidents to service_role;

create or replace function public.record_diagnostic_incident(
    p_fingerprint text,
    p_component text,
    p_code text,
    p_severity text,
    p_description text,
    p_affected_components jsonb,
    p_possible_causes jsonb,
    p_recommended_actions jsonb,
    p_evidence jsonb,
    p_observed_at timestamptz,
    p_occurrence_key text
)
returns setof public.diagnostic_incidents
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    return query
    insert into public.diagnostic_incidents as current_incident (
        fingerprint,
        component,
        code,
        severity,
        description,
        affected_components,
        possible_causes,
        recommended_actions,
        evidence,
        first_seen,
        last_seen,
        last_occurrence_key
    )
    values (
        p_fingerprint,
        p_component,
        p_code,
        p_severity,
        p_description,
        p_affected_components,
        p_possible_causes,
        p_recommended_actions,
        p_evidence,
        p_observed_at,
        p_observed_at,
        p_occurrence_key
    )
    on conflict (fingerprint) do update
    set component = excluded.component,
        code = excluded.code,
        severity = excluded.severity,
        description = excluded.description,
        occurrence_count = case
            when current_incident.status = 'open' then
                current_incident.occurrence_count
                + case
                    when current_incident.last_occurrence_key = excluded.last_occurrence_key
                        then 0
                    else 1
                end
            else 1
        end,
        status = 'open',
        first_seen = case
            when current_incident.status = 'open'
                then current_incident.first_seen
            else excluded.first_seen
        end,
        last_seen = greatest(public.diagnostic_incidents.last_seen, excluded.last_seen),
        last_occurrence_key = excluded.last_occurrence_key,
        resolved_at = null,
        resolution_note = null,
        affected_components = excluded.affected_components,
        possible_causes = excluded.possible_causes,
        recommended_actions = excluded.recommended_actions,
        evidence = excluded.evidence,
        updated_at = now()
    returning *;
end;
$$;

create or replace function public.resolve_diagnostic_incident(
    p_incident_id uuid,
    p_resolution_note text,
    p_resolved_at timestamptz
)
returns boolean
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    update public.diagnostic_incidents
    set status = 'resolved',
        resolved_at = p_resolved_at,
        resolution_note = p_resolution_note,
        updated_at = now()
    where id = p_incident_id
      and status = 'open';
    return found;
end;
$$;

create or replace function public.resolve_health_diagnostic_incident(
    p_fingerprint text,
    p_resolved_at timestamptz
)
returns boolean
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    update public.diagnostic_incidents
    set status = 'resolved',
        resolved_at = p_resolved_at,
        resolution_note = 'Resolved after a healthy system observation.',
        updated_at = now()
    where fingerprint = p_fingerprint
      and status = 'open';
    return found;
end;
$$;

revoke all on function public.record_diagnostic_incident(
    text, text, text, text, text, jsonb, jsonb, jsonb, jsonb, timestamptz, text
) from public, anon, authenticated;
revoke all on function public.resolve_diagnostic_incident(uuid, text, timestamptz)
    from public, anon, authenticated;
revoke all on function public.resolve_health_diagnostic_incident(text, timestamptz)
    from public, anon, authenticated;
grant execute on function public.record_diagnostic_incident(
    text, text, text, text, text, jsonb, jsonb, jsonb, jsonb, timestamptz, text
) to service_role;
grant execute on function public.resolve_diagnostic_incident(uuid, text, timestamptz)
    to service_role;
grant execute on function public.resolve_health_diagnostic_incident(text, timestamptz)
    to service_role;
