# FLOPPI — Arquitectura actual observada

**Versión declarada:** 1.3.2.2  
**Fecha de inspección:** 2026-11-04

## Vista general

```text
Navegador
  └─ Consola HTML/CSS/JavaScript estática
       └─ FastAPI /api/v1
            ├─ datos y proveedor sintético DEMO
            ├─ análisis e historial de señales
            ├─ backtesting / walk-forward / estrategias
            ├─ monitoreo / diagnósticos / eventos
            ├─ scheduler y recuperación de leases
            └─ almacenamiento Supabase (si está configurado)

Worker Python
  ├─ heartbeat y métricas de CPU/RAM/disco
  └─ reclama y ejecuta backtests DEMO encolados

PostgreSQL/Supabase remoto (opcional en el runtime local)
  └─ persistencia definida por migraciones SQL
```

No se encontró un servicio WebSocket implementado en FastAPI. La comunicación de la consola observada usa HTTP/REST. El SDK web empaquetado de Supabase contiene soporte interno de Realtime/WebSocket, pero eso no demuestra que FLOPPI tenga un servidor WebSocket ni un flujo Realtime integrado.

## Árbol funcional

| Área | Ubicación | Responsabilidad observada |
|---|---|---|
| API y ciclo de vida | `backend/app/main.py`, `backend/app/api/` | FastAPI, routers, middleware, muestreo de salud, retención de eventos, scheduler y recuperación. |
| Datos | `backend/app/data/`, `backend/app/providers/` | Modelos OHLCV, validación, normalización, repositorios y proveedor sintético. |
| Análisis | `backend/app/analysis/`, `backend/app/indicators/` | Indicadores técnicos, análisis híbrido e historial de señales. |
| Backtesting | `backend/app/backtesting/` | Estrategias, cartera virtual, ejecución simulada, métricas y walk-forward. |
| Observabilidad | `backend/app/monitoring*.py`, `diagnostics.py`, `event_log.py` | Salud, estadísticas históricas, incidentes y eventos sanitizados. |
| Tareas distribuidas | `backend/app/scheduler.py`, `worker_balancer.py`, `worker_recovery.py`, `worker/local_worker.py` | Planificación DEMO, asignación por telemetría y recuperación de leases. |
| Auth | `backend/app/api/auth.py`, `worker_auth.py`, `web/src/auth.js` | Validación de usuario con Supabase Auth, rol admin y credenciales de worker. |
| Persistencia | `backend/app/supabase_store.py`, `database/migrations/` | Cliente Supabase de servidor y contratos SQL/RLS. |
| Web | `backend/app/static/`, `web/src/auth.js` | Consola estática; fuente JS para bundle de Auth. No es una aplicación React/TypeScript. |
| Herramientas | `tools/` | Auditoría local, preparación PostgreSQL local, provisioning de worker y verificación aislada de migration 017. |
| Pruebas | `backend/tests/` | Suite pytest agrupada por módulos existentes. |

## Contratos API observados

Los routers se montan bajo `/api/v1`. Las áreas incluyen:

- Salud, autenticación/configuración, nodos y preferencias de notificación.
- Mercados, activos, recolección DEMO, velas y calidad de datos.
- Indicadores, análisis técnico/híbrido, comparación multi-timeframe e historial de señales.
- Estrategias, backtesting, walk-forward, comparaciones, trabajos de worker y métricas.
- Rendimiento, salud e historial estadístico.
- Resumen, historial, resolución manual y exportación de diagnósticos.
- Eventos de workers, búsqueda/paginación y exportación.
- Creación, consulta, pausa, reanudación y cancelación de tareas programadas.

No se halló un grupo completo de APIs para registro de dispositivos multiusuario, cuentas de proveedor, sesión multiplataforma o administración de clientes de escritorio/móvil.

## Persistencia y migraciones

Migraciones presentes: 001–007 y 010–017. Las migraciones 008 y 009 no están en este checkout y se documentan como huecos deliberados; no deben inventarse.

Migration 017 depende de `public.worker_credentials` definido en 004. Desactiva registros con `expires_at IS NULL`, establece `revoked_at` si falta y convierte `expires_at` a NOT NULL. No crea políticas RLS. La RLS/grants efectivos del proyecto Supabase real no se pudieron inspeccionar.

La configuración `docker-compose.staging.yml` es PostgreSQL vanilla local, aislado, sin puertos publicados y sin Auth/RPC Supabase. No prueba la integración real.

## Cliente web, móvil y escritorio

| Plataforma | Estado del checkout |
|---|---|
| Web | Consola HTML/CSS/JS servida por FastAPI; algunas acciones usan endpoints reales existentes. No se encontró React/TypeScript. |
| Windows | No se encontró proyecto de escritorio, PySide6 ni configuración de empaquetado EXE. |
| Android | No se encontró proyecto Flutter, `pubspec.yaml`, ni configuración de empaquetado APK. |

## Entorno y límites de la inspección

El proyecto declara Python 3.10 y dependencias FastAPI, Supabase Python SDK, Pydantic Settings, HTTPX y psutil. La última evidencia automatizada disponible es el informe del 2026-11-02; no se ejecutó una validación nueva durante la inspección del 2026-11-04. No se accedió a secretos locales ni se logró confirmar un proyecto Supabase conectado en esta sesión.
