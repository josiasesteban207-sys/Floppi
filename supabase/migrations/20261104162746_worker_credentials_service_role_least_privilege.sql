revoke all on table public.worker_credentials from service_role;
grant select, insert, update on table public.worker_credentials to service_role;;
