# FLOPPI — Revisión de seguridad Supabase (plan de ejecución)

**Estado:** BLOCKED — sin conexión verificable a Supabase staging en esta sesión.  
**Entorno requerido:** proyecto Supabase de staging separado, identificado antes de ejecutar consultas. No usar producción. Las consultas siguientes son de solo lectura y no revelan valores de credenciales ni token hashes.

## Estado de acceso

- `supabase --version` y `supabase --help` no pudieron ejecutarse: el comando no está instalado/en PATH.
- No hay servidor MCP Supabase habilitado en la sesión.
- `.env.staging` y `docker-compose.staging.yml` del repo describen PostgreSQL 16 local aislado, no Supabase Auth, Data API ni RPC.
- No se leyó ni imprimió el contenido de archivos `.env`.

No se ejecutaron consultas a una base remota. Las consultas se deben ejecutar primero en el staging autorizado mediante SQL Editor de Supabase o una herramienta segura ya autenticada, después de confirmar visualmente el ref/nombre del proyecto.

## 1. Inventario de tablas, RLS y políticas

```sql
select n.nspname as schema_name,
       c.relname as relation_name,
       c.relkind as relation_kind,
       c.relrowsecurity as rls_enabled,
       c.relforcerowsecurity as rls_forced
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relkind in ('r', 'p', 'v', 'm', 'f')
order by c.relkind, c.relname;

select schemaname, tablename, policyname, permissive,
       roles, cmd, qual, with_check
from pg_policies
where schemaname = 'public'
order by tablename, policyname;
```

Comprobar todas las tablas en esquemas expuestos, no solo `worker_credentials`. RLS y GRANT son controles distintos: una política no concede por sí sola acceso a una tabla. Supabase recomienda RLS para tablas de esquemas expuestos y revisar también los privilegios efectivos ([guía oficial RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)).

## 2. Roles, GRANT y privilegios efectivos

Primero comprobar la existencia y atributos de roles objetivo:

```sql
select rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb,
       rolcanlogin, rolreplication, rolbypassrls
from pg_roles
where rolname in ('anon', 'authenticated', 'service_role', 'authenticator', 'postgres')
order by rolname;
```

Si falta alguno de `anon`, `authenticated` o `service_role`, detener la consulta de privilegios y documentar la diferencia. No crear roles para hacer pasar la revisión.

Esta consulta muestra privilegios efectivos para cada relación pública y los roles solicitados. No devuelve filas de usuario ni secretos.

```sql
select n.nspname as schema_name,
       c.relname as relation_name,
       r.role_name,
       has_table_privilege(r.role_name, c.oid, 'SELECT') as can_select,
       has_table_privilege(r.role_name, c.oid, 'INSERT') as can_insert,
       has_table_privilege(r.role_name, c.oid, 'UPDATE') as can_update,
       has_table_privilege(r.role_name, c.oid, 'DELETE') as can_delete,
       has_table_privilege(r.role_name, c.oid, 'TRUNCATE') as can_truncate,
       has_table_privilege(r.role_name, c.oid, 'REFERENCES') as can_reference,
       has_table_privilege(r.role_name, c.oid, 'TRIGGER') as can_trigger
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
cross join (values ('anon'), ('authenticated'), ('service_role')) as r(role_name)
where n.nspname = 'public'
  and c.relkind in ('r', 'p', 'v', 'm', 'f')
order by c.relname, r.role_name;

select n.nspname as schema_name,
       r.role_name,
       has_schema_privilege(r.role_name, n.oid, 'USAGE') as can_use,
       has_schema_privilege(r.role_name, n.oid, 'CREATE') as can_create
from pg_namespace n
cross join (values ('anon'), ('authenticated'), ('service_role')) as r(role_name)
where n.nspname in ('public', 'auth', 'storage')
order by n.nspname, r.role_name;
```

Si alguno de esos roles no existe en el proyecto revisado, detener y registrar la diferencia; no crear roles para hacer pasar la comprobación. Revisar privilegios heredados y ACLs directos con el administrador si algún resultado contradice el historial de migraciones.

## 3. Funciones SECURITY DEFINER y EXECUTE

```sql
select n.nspname as schema_name,
       p.proname as function_name,
       pg_get_function_identity_arguments(p.oid) as arguments,
       p.prosecdef as security_definer,
       p.proconfig as function_settings,
       has_function_privilege('anon', p.oid, 'EXECUTE') as anon_can_execute,
       has_function_privilege('authenticated', p.oid, 'EXECUTE') as authenticated_can_execute,
       has_function_privilege('service_role', p.oid, 'EXECUTE') as service_role_can_execute
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname in ('public', 'auth')
  and p.prokind in ('f', 'p')
order by n.nspname, p.proname, arguments;

select n.nspname as schema_name,
       p.proname as function_name,
       pg_get_function_identity_arguments(p.oid) as arguments,
       e.grantee,
       e.privilege_type,
       e.is_grantable
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
cross join lateral aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) e
where n.nspname in ('public', 'auth')
  and p.prokind in ('f', 'p')
  and e.grantee = 0
  and e.privilege_type = 'EXECUTE'
order by n.nspname, p.proname, arguments;
```

Para cada función `SECURITY DEFINER`, comprobar propietario, `search_path` fijo/seguro, validación de identidad dentro del cuerpo y mínimo privilegio de `EXECUTE`. Investigar especialmente funciones en esquemas expuestos, grants implícitos a `PUBLIC` y RPCs de claim/recovery. No cambiar a `SECURITY DEFINER` como arreglo de errores de permisos.

## 4. Índices, claves foráneas y worker_credentials

```sql
select schemaname, tablename, indexname, indexdef
from pg_indexes
where schemaname = 'public'
order by tablename, indexname;

select n.nspname as schema_name,
       c.relname as table_name,
       con.conname as constraint_name,
       con.contype as constraint_type,
       pg_get_constraintdef(con.oid, true) as definition,
       con.convalidated as validated
from pg_constraint con
join pg_class c on c.oid = con.conrelid
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
order by c.relname, con.contype, con.conname;

select to_regclass('public.worker_credentials') as worker_credentials_table;
```

Solo si `worker_credentials_table` no es NULL, ejecutar:

```sql
select count(*) as total_rows,
       count(*) filter (where expires_at is null) as null_expiry_rows,
       count(*) filter (where expires_at is null and active) as active_null_expiry_rows,
       count(*) filter (where expires_at is not null and active) as active_with_expiry_rows
from public.worker_credentials;

select column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public' and table_name = 'worker_credentials'
order by ordinal_position;
```

No seleccionar `token_hash` ni tokens. Comparar tabla/columnas/constraints/índices/RLS/grants con migrations 004 y 017. La cuenta `active_null_expiry_rows` determina cuántas credenciales activas quedarían revocadas por 017.

## 5. Historial e integridad de migraciones

```sql
select to_regclass('supabase_migrations.schema_migrations') as migration_ledger;
```

Si existe el ledger, inspeccionar sus columnas antes de consultar el historial; no asumir que distintas versiones del CLI usan los mismos campos:

```sql
select column_name, data_type, udt_name
from information_schema.columns
where table_schema = 'supabase_migrations'
  and table_name = 'schema_migrations'
order by ordinal_position;

select version
from supabase_migrations.schema_migrations
order by version;
```

Comparar con el checkout: 001–007, 010–017; 008/009 son ausencias intencionales documentadas. Revisar desalineaciones, migraciones omitidas/repetidas, orden y estado del DDL real. Si el ledger no existe, no inventarlo ni asumir que el proyecto está limpio. Conciliarlo con el administrador del proyecto antes de cualquier migración.

## Criterios de revisión

- RLS enabled para relaciones expuestas con datos sensibles.
- Privilegios anon/authenticated limitados a lo estrictamente público/autorizado.
- `worker_credentials` no accesible desde roles cliente; service_role solo desde backend seguro.
- RPCs de tareas/recovery ejecutables únicamente por los roles previstos.
- Funciones privilegiadas con propietario, search path, comprobaciones y grants revisados.
- Índices y restricciones reales compatibles con migraciones del repositorio.
- Ledger y esquema coinciden; backup restaurable confirmado.
- Nada se aplica hasta documentar filas afectadas, worker impactado, ventana y plan para reemitir credenciales.

**Ejecución en esta sesión:** ninguna consulta a Supabase; todos los campos remotos quedan **BLOCKED / PENDIENTE DE VALIDACIÓN**.
