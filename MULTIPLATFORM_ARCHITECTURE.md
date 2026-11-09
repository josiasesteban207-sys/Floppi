# FLOPPI — Arquitectura objetivo multiplataforma

**Estado:** diseño propuesto; no implementado ni conectado entre clientes. El backend y la consola actuales deben conservarse hasta que cada reemplazo tenga paridad comprobada.

## Componentes

```text
                 ┌───────────────────────────┐
 Web React/TS ───┤                           ├── Desktop PySide6
 Android Flutter ┤   API central FastAPI     ├── REST /api/v1
                 │ Auth, permisos, contratos │── WebSocket (propuesto)
                 └─────────────┬─────────────┘
                               │
            Supabase Auth + PostgreSQL/RLS + RPC seguro
                               │
           Coordinador (reutilizar scheduler/leases/recovery)
                ┌──────────────┴──────────────┐
         Clientes genéricos registrados; workers DEMO
```

## Autoridad y modelo de permisos único

- Supabase Auth identifica al usuario; roles administrativos confiables provienen de `app_metadata`, no de metadata editable por el usuario.
- El backend verifica identidad y autorización para cada recurso. RLS constituye defensa de base de datos; los grants son una capa independiente.
- Roles conceptuales de aplicación: `user`, `analyst` y `admin`, restringidos a permisos explícitos. No son grants directos automáticos a tablas.
- Un dispositivo es un cliente de una identidad de usuario; hardware, nombre de máquina y etiquetas Blacki/Blanquita no otorgan privilegios.
- Un worker usa credencial de dispositivo hasheada, con expiración/revocación, alcance y capacidad limitados. No se entrega `service_role` a clientes.
- Recursos propiedad de usuario llevan `owner_id`/relación validada. Recursos compartidos requieren membresía explícita y pruebas de dos usuarios.

## API central

FastAPI conserva REST `/api/v1/` y los módulos existentes de análisis/backtesting/monitoring/diagnostics/events/scheduler. Nuevos routers se agregan solo después de estabilizar el modelo de datos y definir contratos en `API_CONTRACTS.md`.

REST es el canal de comandos, consulta paginada, autenticación y recuperación. WebSocket se reserva para notificaciones/progreso/telemetría no autoritativa; la autorización de cada conexión y suscripciones se vuelve a comprobar en servidor. La desconexión debe poder recuperarse desde REST y la base, no depender de mensajes perdidos.

## Dispositivos y heartbeats

El registro propuesto asocia `device_id`, `owner_id`, plataforma, versión, capacidades y estado. El heartbeat autenticado informa métricas acotadas, timestamp y tarea activa opcional. Solo el servidor decide `connected/stale/revoked`; no confiar en la hora o estado declarado por el cliente sin validación.

El esquema existente de nodes y worker credentials se debe comparar con esta entidad antes de añadir tabla. Puede representar workers de backtest, pero no demuestra soporte general de todos los clientes ni propietario multiusuario.

## Coordinador, cola y recuperación

Reutilizar cola `backtest_runs`, leases, scheduler, balanceador y recovery existentes cuando el tipo de trabajo sea compatible. No construir una segunda cola paralela. El coordinador reclama trabajo mediante RPC/transacción de mínimo privilegio, filtra por capacidad y disponibilidad, respeta concurrencia y usa leases/idempotencia.

Estados de negocio propuestos: `PENDING`, `QUEUED`, `ASSIGNED`, `RUNNING`, `PAUSED`, `COMPLETED`, `FAILED`, `CANCELLED`, `EXPIRED`. Debe elaborarse una máquina de transición antes de ampliar el estado actual, que está especializado en backtests.

La recuperación sólo reasigna trabajos reintentables con input/fingerprint estable y lease vencido. Una tarea terminal o ya completada no se ejecuta de nuevo. Cancelar en cliente no sustituye confirmación de estado del servidor.

## Eventos

El registro centralizado existente conserva `event_id`, timestamp, severidad, componente, `request_id`/`task_id` y sanitización. Añadir `user_id`/`device_id` solo si es necesario y minimizado. Nunca registrar contraseñas, tokens, cabeceras Authorization, claves privadas ni datos secretos de cuentas proveedor.

## Clientes

| Cliente | Presentación | Transporte | Persistencia local |
|---|---|---|---|
| Web | React + TypeScript (propuesto); conservar/rescatar interacciones útiles de HTML/CSS/JS estático | REST; WebSocket opcional con reconexión | sesión segura del navegador según diseño Auth existente; no service role |
| Desktop Windows | PySide6 (propuesto), instalación EXE repetible | REST/WebSocket | configuración y caché no sensibles; secretos mediante almacén del sistema si se incorporan |
| Android | Flutter (propuesto), APK | REST/WebSocket; notificaciones con servicio autorizado | sesión en almacenamiento seguro; no depender de ejecución permanente en background |

Cada cliente comparte contratos, identidad, permisos y reglas de negocio. El backend es autoridad para transiciones de tarea y resultados.

## Requisitos operativos

- Servidor de 8 GB: límites de concurrencia, lotes paginados, retención y observabilidad; medir antes/después.
- Transportes externos solo mediante HTTPS/gateway; no exponer el puerto de desarrollo.
- Mercado y backtesting se mantienen DEMO/simulación; no órdenes reales ni accesos ocultos.
- No realizar migraciones hasta inspeccionar staging, backup, RLS, grants, historial y autorización explícita.
