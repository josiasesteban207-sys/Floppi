# FLOPPI 1.3.2.2 — Informe de estabilización

**Fecha:** 2026-11-04  
**Versión:** `VERSION` declara 1.3.2.2.  
**Estado:** VERIFICACIÓN LOCAL APROBADA; VALIDACIÓN SUPABASE STAGING BLOQUEADA.  
**Alcance:** estado del repositorio, dependencias, backend, worker, pruebas, estructura de migraciones, consola web y preparación multiplataforma. No se conectó a Supabase ni se aplicó ninguna migración.

## Resultados ejecutados en esta sesión

| Comprobación | Resultado real |
|---|---|
| Python | Python 3.10.0 |
| Dependencias Python (`python -m pip check`) | `No broken requirements found.` |
| Paquetes inspeccionados | FastAPI 0.141.1; supabase 2.31.0; pydantic-settings 2.15.0; httpx 0.28.1; psutil 7.2.2; pytest 8.4.2 |
| Suite | `python -m pytest -q`: **162 passed in 14.40s**, exit code 0 |
| Compilación Python | `python -m compileall -q backend worker`: exit code 0 |
| Auditoría estática | `python tools/audit.py --skip-tests`: **16/16 checks definitivos PASS**; check de pytest figura WARN porque se omitió dentro de ese comando. La suite se ejecutó y pasó por separado. |
| Sintaxis JS | `node --check` en `app.js`, `diagnostics.js`, `scheduler.js`, `monitoring-history.js`: los cuatro comandos pasaron |
| Node.js | v24.22.1 |
| npm | No disponible en PATH; `npm build` / `npm audit` no ejecutables |
| Dependencias web existentes | `web/node_modules` presente; esbuild 0.25.12. Compilación en memoria de `src/auth.js` con bundle/IIFE/browser/ES2020: pasó, 789641 bytes; no reemplazó el bundle del repo |
| Flutter / Dart | Flutter 3.44.9 stable; Dart 3.12.2 |
| PySide6 | No instalado |
| Scikit-learn | 1.7.2 instalado globalmente; el repositorio no contiene un módulo ML ni lo declara como dependencia del proyecto |
| Supabase CLI / MCP | CLI no reconocido en PATH; no hay herramienta MCP Supabase habilitada en esta sesión |

La auditoría actualizada se guardó en `reports/audit_latest.md` y `reports/audit_latest.json`; snapshots en `reports/history/`. Su check de pytest es WARN por haber usado `--skip-tests`, no por un fallo. La ejecución independiente de pytest anterior da el resultado completo indicado arriba.

## Backend y worker

La suite completa terminó sin fallos. `compileall` compiló `backend` y `worker`. Las pruebas cubren API, análisis, backtesting, calidad de datos, diagnóstico, eventos, monitoreo, scheduler, settings, staging local, walk-forward, autenticación worker, balanceador y recuperación.

No se detectó un error de backend/worker en las comprobaciones ejecutadas. Esto no valida una ejecución conectada a Supabase, workers Blacki/Blanquita reales, concurrencia en red, TLS/gateway ni carga de producción. Tampoco se ejecutó un smoke test HTTP independiente levantando el servicio.

## Migraciones y migration 017

Archivos presentes: 001–007 y 010–017. Las ausencias 008/009 son intencionales según la documentación y no se deben rellenar con placeholders. La cadena de archivos local es consistente en orden numérico; el estado aplicado en un proyecto remoto no se conoce.

Migration 004 define `public.worker_credentials`, habilita RLS, revoca privilegios de `public`, `anon` y `authenticated`, y concede `SELECT/UPDATE/INSERT` a `service_role`. Migration 017 marca inactivas todas las filas con `expires_at IS NULL`, establece `revoked_at` si faltaba y exige `expires_at NOT NULL`. No modifica RLS ni grants. Las migraciones intermedias 005–016 no alteran esa tabla según la búsqueda realizada.

`backend/tests/test_worker_auth.py` cubre validación, nodo equivocado, expiración, credenciales revocadas, credenciales sin expiración y comprobaciones estáticas de migration 017/RLS. `test_worker_expiry_migration_runner.py` valida que el runner exija una bandera explícita y use contenedor sin red con almacenamiento temporal. No ejecuté el runner, porque aplica la migración en scratch y el encargo solo autoriza revisar migration 017; tampoco hubo autorización específica para aplicar una migración remota. No se hizo cambio alguno a Supabase.

El informe anterior documenta una corrida del runner aislado con fixtures sintéticas. Es evidencia histórica, no ejecución de esta sesión ni validación del staging Supabase real.

## Consola y preparación multiplataforma

La consola `backend/app/static/` es HTML/CSS/JavaScript servido por FastAPI. Reutilizables: navegación, identidad visual, componentes de gráficos/tablas, estados de carga/error y llamadas a endpoints existentes. `web/src/auth.js` y el bundle existente contienen el flujo Auth web. `web/package.json` define esbuild; se validó el bundle en memoria aunque no se pudo invocar el script npm ni `npm audit` por falta de npm.

No hay proyecto React/TypeScript, PySide6 ni Flutter dentro del repositorio. El SDK Flutter/Dart está presente en el equipo, pero no constituye una app FLOPPI. No hay EXE/APK ni flujos para probarlos. El proveedor disponible es sintético DEMO.

## Cambios y límites

- No se modificó código funcional ni se aplicó SQL.
- Se crearon los seis documentos de estabilización/revisión/arquitectura/contratos/plan solicitados.
- El staging disponible en los archivos del proyecto es PostgreSQL vanilla local; no tiene Auth/RPC Supabase. La conexión Supabase no pudo verificarse con herramientas disponibles.
- No exponer valores de `.env`; no fueron incluidos en el informe.

## Resultado

La base local FLOPPI está estable en las pruebas ejecutadas: **162 aprobadas**, con compilación y sintaxis JS aprobadas. La aceptación completa de 1.3.2.2 permanece **BLOCKED** hasta inspeccionar staging Supabase y validar allí RLS, privilegios, historial de migraciones, impacto de filas y migration 017. No avanzar a funcionalidades que dependan de declarar aceptada esta etapa.

## Estado de funcionalidades

| Funcionalidad | Estado | Evidencia / limitación |
|---|---|---|
| Backend FastAPI y rutas REST actuales | VERIFIED | Suite pytest 162/162 y compilación backend/worker en esta sesión. |
| Indicadores, análisis híbrido y backtesting DEMO | VERIFIED | Pruebas locales aprobadas; no equivale a rentabilidad ni a proveedor real. |
| Monitoreo, diagnósticos, eventos y scheduler existentes | VERIFIED | Suite local aprobada y auditoría estática; servicios remotos no se validaron. |
| Worker de backtesting, leases y recovery | PARTIAL | Lógica local cubierta; worker real distribuido y Blacki/Blanquita simultáneos no probados. |
| Autenticación Supabase y aislamiento entre usuarios | PARTIAL | Código y pruebas con mocks; conexión/Auth/RLS real no comprobados. |
| Consola web estática actual | PARTIAL | JS revisado pasa `node --check`; esbuild en memoria pasó. `npm build` y `npm audit` no disponibles. |
| Migration 017 y compatibilidad con migration 004 | PARTIAL | SQL y pruebas estáticas inspeccionados; runner histórico en scratch; no se aplicó/verificó en staging. |
| Auditoría Supabase de RLS, políticas, GRANT y RPC | BLOCKED | No hay CLI, MCP o conexión remota confirmable en esta sesión. |
| Frontend FLOPPI Web React + TypeScript | MISSING | No existe proyecto React/TypeScript en el checkout. |
| FLOPPI Desktop PySide6 + EXE | MISSING | No existe cliente; PySide6 no está instalado. |
| FLOPPI Mobile Flutter + APK | MISSING | SDK Flutter instalado, proyecto cliente ausente. |
| WebSocket FastAPI FLOPPI | MISSING | No se encontró endpoint servidor; no confundir con SDK Supabase bundlado. |
| Adaptadores de proveedores externos | MISSING | Solo se verificó proveedor sintético DEMO. |
| Lab de ML y drift | MISSING | Scikit-learn está en el entorno global, pero faltan módulos y dependencias declaradas del proyecto. |
