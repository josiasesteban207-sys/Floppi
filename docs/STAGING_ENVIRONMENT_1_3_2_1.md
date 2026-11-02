# FLOPPI 1.3.2.1 — Preparación local de staging

**Estado:** PostgreSQL local arrancó y se verificó dentro de Docker; backup y
restauración scratch pasaron. Esta evidencia no autoriza ni valida conexiones
a producción.

## Alcance y arquitectura

El backend actual usa el cliente Supabase para persistencia; no consume un
`DATABASE_URL` PostgreSQL genérico. Las migraciones usan objetos y funciones
de Supabase (incluidos `auth.uid()` y tablas previas), por lo que un PostgreSQL
vanilla no es un sustituto de un proyecto Supabase de staging y no puede
demostrar por sí solo la aplicación de la migración 017.

`docker-compose.staging.yml` prepara exclusivamente una instancia PostgreSQL
16 local fijada al digest verificado
`sha256:0cefaabd882e42bcb2a2f3dc56d3ce4770560ba62fd7f197f1a2e008fd5731ab`.
No inicia la API, workers, Supabase Auth ni servicios de producción.
No publica ningún puerto en el host; el contenedor solo pertenece a una red
Docker `internal`; el volumen se llama
`floppi-staging-postgres-data`. El archivo Compose no carga migraciones ni
monta scripts de inicialización.

La configuración privada `.env.staging` acepta únicamente cuatro campos de
esta base local. Rechaza `SUPABASE_URL`, `DATABASE_URL`, variables de la app y
otros ajustes, evita endpoints remotos, exige el nombre/usuario reservados y
prohíbe contraseñas de ejemplo. No reutilices contraseñas de desarrollo ni
producción.

La conexión administrativa se ejecuta mediante `docker compose exec` dentro
del propio contenedor, a `127.0.0.1:5432`; no se abre un socket TCP accesible
desde el host ni desde otros contenedores.

## Inicialización y verificación

Requisitos: Docker Desktop con el motor Linux activo y Python 3.10+.
Desde PowerShell, en la raíz del proyecto:

```powershell
python tools\staging_environment.py init
python tools\staging_environment.py validate
python tools\staging_environment.py start
python tools\staging_environment.py check
```

`init` crea `.env.staging` con una contraseña aleatoria local, no la imprime y
no sobrescribe un archivo existente. Si ya tenías la configuración de una
iteración previa con host/puerto publicados, ejecuta una vez
`python tools\staging_environment.py migrate-config`; conserva la contraseña,
elimina esas opciones de conexión y no modifica la base. `.gitignore` excluye
la configuración privada y los backups, pero permite versionar
`.env.staging.example`. `validate` revisa el contenido privado y la configuración Compose renderizada,
sin iniciar contenedores. `start` levanta solo el servicio PostgreSQL, espera
el healthcheck y verifica que no haya puertos publicados, que esté conectado
solo a la red interna y que el proyecto/base/usuario correspondan a staging.
También comprueba una conexión TCP al loopback del contenedor con los valores
privados. No aplica migraciones. `check` repite las comprobaciones; no imprime
credenciales.

`validate` confirma el contrato estático de Compose. `start` y `check`
comprueban adicionalmente el contenedor en ejecución, network mode, puertos
vacíos, red `internal`, readiness y la identidad de la sesión PostgreSQL.

## Backup, recuperación y apagado

```powershell
python tools\staging_environment.py backup
python tools\staging_environment.py restore backups\staging\<archivo>.dump --confirm-staging-restore
python tools\staging_environment.py stop
```

El backup es un dump PostgreSQL custom, guardado en `backups/staging/`. Ese
directorio está excluido de Git. Antes de restaurar, crea y comprueba un backup
reciente. `restore` exige confirmación explícita, acepta únicamente archivos
`.dump` regulares dentro de ese directorio y vuelve a comprobar que el destino
es la instancia local staging; restaura con `pg_restore --clean` y sustituye
objetos/datos incluidos en el dump. No uses ese comando sobre otra base.
`stop` para el contenedor y conserva el volumen. No ejecutes `docker compose
down --volumes` ni borres el volumen si necesitas conservar o recuperar datos.

La recuperación de pérdida del contenedor consiste en volver a iniciar Compose
con el volumen nombrado; la recuperación de datos consiste en restaurar un dump
verificado. Los backups de esta máquina no sustituyen una copia externa ni un
plan de recuperación de Supabase.

## Migración 017 y preparación del staging Supabase

La migración 017 **no se ejecuta** en la instancia local. Antes de una futura
prueba en staging Supabase:

1. Crear/confirmar un proyecto separado, con Auth, almacenamiento y credenciales
   propios; no copiar ningún valor de producción.
2. Guardar la configuración de API en un archivo privado distinto de
   `.env.staging`, con URL de proyecto staging comprobada por un operador.
3. Confirmar backup/restauración y presencia de las migraciones existentes
   001–007 y 010–016. Los huecos 008/009 son intencionales en este checkout.
4. Probar primero la migración 017 en ese proyecto aislado, sin desactivar RLS;
   verificar la revocación de credenciales legacy y `expires_at NOT NULL`.
5. Reemitir credenciales de workers afectados antes de desplegar el API/worker
   candidato; conservar evidencia sanitizada y nunca exportar tokens.

La URL de staging y las claves de Supabase no deben añadirse a este archivo
Compose, a `.env.staging`, a Git ni a logs. No se conectó ningún proyecto
Supabase y no se aplicó migración alguna en esta etapa.

## Pruebas y estado de aprobación

Las pruebas unitarias cubren variables obligatorias, campos de producción
prohibidos, hosts/nombres no permitidos, contraseña de ejemplo, configuración
Compose, puertos publicados, red externa, servicios/volúmenes adicionales,
identidad de conexión, archivos privados, inicialización y restricciones de
restore.

Evidencia local obtenida el 2026-11-02:

- Docker Engine 29.9.2 y Compose 5.6.1; PostgreSQL 16 Alpine quedó fijado por
  el digest verificado arriba.
- El contenedor identificado como parte del proyecto `floppi-staging` quedó
  healthy, conectado únicamente a `floppi-staging-internal` (`Internal=true`).
- `HostConfig.PortBindings={}`: no publica puertos del contenedor al host.
- `python tools\staging_environment.py validate`, `start` y `check` pasaron.
  La identidad consultada fue `floppi_staging` / `floppi_staging`; la sesión
  PostgreSQL se verificó sobre loopback dentro del contenedor.
- Se generó `backups/staging/floppi-staging-20261102T163209Z.dump` (851 bytes)
  y PostgreSQL pudo listar su archivo custom. En una base scratch desechable
  dentro del mismo proyecto se modificó un registro después del dump, se
  restauró el backup y se recuperó el valor original; la base scratch se borró.
- No se ejecutó ni se detectó una migración de FLOPPI; no hubo tráfico a
  Supabase/producción. El backup local se conserva bajo un directorio ignorado
  por Git.

Esta evidencia demuestra aislamiento de red/puertos y conectividad **del
fixture PostgreSQL local** en este host. No prueba separación de credenciales
de proyectos Supabase ni aislamiento de Auth/RLS/RPC entre entornos reales.

También permanecen pendientes y no aprobados: Supabase Auth/RLS/RPC,
aislamiento de usuarios, aplicación de migration 017, workers Blacki/Blanquita,
TLS/certificados, firewall, rate limiting, restricciones de acceso y seguridad
de comunicaciones. No se probó ni se modificó producción.

## Riesgos pendientes

| Riesgo | Estado | Acción de cierre |
|---|---|---|
| Docker daemon detenido/no disponible | Cerrado para esta ejecución local | Repetir `start`/`check` en el host previsto para cada entorno |
| PostgreSQL vanilla no incluye Supabase Auth/RLS/RPC | Abierto | Preparar un Supabase local o proyecto staging separado; ejecutar pruebas SQL/RLS allí |
| Cambio de imagen/digest de PostgreSQL | Mitigado localmente mediante digest fijado | Revisar y actualizar el digest solo como cambio deliberado, con pruebas |
| Aislamiento Supabase frente a proyectos reales de producción | Abierto, no verificado | Usar un proyecto Supabase staging separado y comprobar identidad/RLS sin credenciales de producción |
| TLS, certificados, firewall y rate limiting no están configurados ni verificados | Pendiente externo | Probar solo mediante un gateway de staging autorizado |
| Migration 017 no se ejecutó ni probó con datos previos | Pendiente externo | Backup restaurable, prueba de upgrade/rollback en Supabase staging y rotación de credenciales |

No avanzar a 1.3.2.2 hasta que las verificaciones pendientes se ejecuten y el
propietario autorice expresamente esa etapa.
