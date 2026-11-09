# FLOPPI — Informe de auditoría inicial

**Fecha:** 2026-11-04  
**Versión declarada en `VERSION`:** 1.3.2.2  
**Estado:** auditoría documental y estructural completada; aceptación de Security Validation Core pendiente de Supabase staging.  
**Alcance:** inspección del checkout local, documentación, archivos de dependencias, endpoints, migraciones, pruebas y artefactos de auditoría. No se ejecutaron pruebas ni se aplicaron cambios de base de datos en esta revisión.

## Resumen ejecutivo

FLOPPI ya cuenta con un backend FastAPI para análisis de mercado DEMO, backtesting, monitoreo, diagnóstico, registro de eventos y coordinación de trabajos con workers Python. La interfaz actual es una consola web servida como archivos estáticos por FastAPI. El repositorio declara Python 3.10 y Supabase/PostgreSQL como persistencia remota opcional.

El objetivo multiplataforma del Prompt Maestro FLOPPI 2.0 excede lo que contiene este checkout: no hay aplicaciones de escritorio PySide6 ni Android Flutter, la web no es React/TypeScript, y no se encontró un endpoint WebSocket del servidor. El proveedor presente es sintético DEMO; no se hallaron adaptadores oficiales para cuentas externas. Tampoco se encontraron módulos de ML, gestión general de usuarios/dispositivos/cuentas o sincronización entre clientes con el alcance descrito.

La etapa actual continúa siendo **1.3.2.2 Security Validation Core, pendiente de aceptación**. Existe una validación de migration 017 en PostgreSQL desechable y una auditoría local anterior con 17/17 checks y 162 pruebas. No existe evidencia de que esas comprobaciones se hayan ejecutado contra Supabase staging. La configuración de staging documentada es PostgreSQL local aislado y excluye conexiones Supabase. Esta sesión no dispone de Supabase MCP ni CLI; el acceso real al proyecto no se pudo verificar.

## Hallazgos

### Componentes existentes

- API FastAPI con routers de mercados/datos, análisis, backtesting, monitoreo, diagnósticos, eventos y scheduler bajo `/api/v1/`.
- Autenticación de usuario mediante validación de access token Supabase y rol administrativo en `app_metadata`; autenticación separada para workers.
- Motor de indicadores, análisis híbrido, historial de señales, simulador de cartera, métricas de riesgo y walk-forward.
- Persistencia Supabase desde backend y almacenamiento DEMO en memoria en los modos previstos por el proyecto.
- Worker Python para heartbeats, métricas de recursos y backtests históricos encolados.
- Consola web adaptable basada en HTML/CSS/JavaScript estático, servida por FastAPI; `web/` contiene una pequeña fuente JS para compilar el bundle Auth, no una app React.
- Migraciones 001–007 y 010–017. Los huecos 008 y 009 se documentan como intencionales.
- Suite backend con 15 archivos de pruebas por área (API, análisis, datos, backtesting, diagnóstico, eventos, monitoreo, scheduler, entorno, autenticación y workers).

### Evidencia previa, no repetida en esta auditoría

`reports/audit_latest.md`, generado el 2026-11-02, registra Python 3.10.0, 17/17 checks y 162 pruebas aprobadas. `docs/MIGRATION_017_REVIEW_1_3_2_2.md` registra una prueba de la migration 017 en una base desechable y aislada, con fixtures sintéticas. Esta ejecución no volvió a correr esos comandos; los resultados son históricos del reporte.

### Brechas frente al objetivo 2.0

1. No hay `desktop/`, `mobile/` ni proyectos Flutter/PySide6 en el checkout.
2. No hay frontend React/TypeScript; la consola actual es estática y depende de la API.
3. No se halló WebSocket del lado FastAPI.
4. No se hallaron módulos Scikit-learn, experimentos, versionado de modelos o monitoreo de drift.
5. No se hallaron adaptadores de proveedores externos ni administración de credenciales/cuentas de proveedor; el proveedor de datos identificado es sintético DEMO.
6. El modelo actual de workers y jobs se centra en nodos y backtests distribuidos; no satisface aún todo el registro genérico multiusuario de dispositivos descrito por el prompt.
7. Supabase Auth y filtrado por usuario están implementados en superficies existentes, pero el aislamiento completo de todas las nuevas superficies multiplataforma no está demostrado.
8. No hay validación de staging Supabase, RLS efectiva, grants, estado de aplicación de migration 017, ni prueba con Blacki y Blanquita conectados simultáneamente.
9. Las comprobaciones de TLS/gateway, rate limiting compartido, rendimiento de 8 GB y despliegue no están certificadas por la auditoría local.

## Decisión de avance

No declarar FLOPPI 2.0 terminado ni aceptar la etapa 1.3.2.2 con la evidencia disponible. El primer bloqueo operativo es conseguir una conexión comprobable y autorizada al proyecto Supabase **staging separado**, revisar su identidad/esquema y medir el impacto de migration 017 antes de aplicarla. No usar producción ni desactivar RLS.

## Archivos revisados

`VERSION`, `README.md`, `CHANGELOG.md`, `requirements*.txt`, `web/package.json`, `backend/app/`, `backend/tests/`, `database/migrations/`, `docs/MIGRATION_017_REVIEW_1_3_2_2.md`, `docs/STAGING_ENVIRONMENT_1_3_2_1.md`, `docs/SECURITY_1_3_1_TEST_PLAN.md`, `docs/SECURITY_1_3_1_REMEDIATION_MATRIX.md` y `reports/audit_latest.md`.

## Fuentes Supabase consultadas

- [Supabase Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security) — la revisión de tablas expuestas debe considerar tanto RLS como grants efectivos.
- [Supabase Changelog](https://supabase.com/changelog) — consultado para comprobar cambios recientes de plataforma; no se ejecutaron operaciones de administración de Supabase.
