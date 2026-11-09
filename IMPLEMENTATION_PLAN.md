# FLOPPI 2.0 — Plan de implementación por fases

**Base:** versión 1.3.2.2 declarada.  
**Regla:** avanzar en cambios pequeños, con evidencia por fase; detenerse ante bloqueos de staging, seguridad, compatibilidad o datos. No habilitar operaciones financieras reales.

## Fase 0 — Cerrar 1.3.2.2 Security Validation Core

**Estado:** bloqueada por la ausencia de conexión verificable a Supabase staging.  
**Trabajo:** identificar proyecto staging separado; inspeccionar esquema, estado de migraciones, `worker_credentials`, restricciones, índices, RLS, grants y filas afectadas; confirmar respaldo y workers dependientes; realizar aprobación explícita para aplicar migration 017 en staging; verificar postcondiciones, aislamiento y compatibilidad.  
**Aceptación:** evidencia reproducible de staging sanitizada, sin uso de producción, RLS activa y resultado de migration 017 documentado. Hasta entonces no marcar 1.3.2.2 como aceptada.

## Fase 1 — Estabilizar y especificar contratos

- Resolver hallazgos críticos de la auditoría existente.
- Definir contratos compartidos de usuario, sesión, dispositivo, capacidad, tarea, progreso y resultado sin duplicar la cola actual.
- Mapear endpoints existentes a esos contratos y registrar brechas antes de crear tablas o migraciones.
- Definir política de acceso por propietario y por recurso compartido; validar con RLS y permisos de API.
- Confirmar límites de operación para el servidor objetivo de 8 GB mediante mediciones de referencia.

**Aceptación:** contratos documentados, límites de seguridad definidos, regresión del sistema actual sin degradación. No crear nuevas tablas hasta demostrar que el esquema existente no cubre el caso.

## Fase 2 — Backend multiusuario y coordinador genérico

- Extender el sistema existente de nodos/jobs para admitir clientes genéricos y su identidad de propietario, si el análisis del esquema confirma que es necesario.
- Completar alta, heartbeat, capacidades, revocación, progreso, cancelación y recuperación con estados validados por servidor.
- Mantener leases, idempotencia, límites de concurrencia y el worker/backtest existente.
- Añadir pruebas unitarias, API, integración y permisos para usuarios separados.

**Aceptación:** dos usuarios aislados; varios clientes registrables; tareas DEMO recuperables y cancelables sin doble ejecución.

## Fase 3 — Proveedores y datos

- Formalizar una interfaz de adaptadores reutilizando el proveedor sintético existente.
- Integrar proveedor externo solo mediante API oficial/documentada y credenciales protegidas en backend.
- Distinguir datos reales, históricos, sintéticos y simulados en API/UI/informes.
- No afirmar detección automática universal ni extraer credenciales de otras aplicaciones.

**Aceptación:** pruebas por adaptador, trazabilidad de fuente y estado explícito de proveedor no disponible.

## Fase 4 — Web funcional

- Mantener endpoints y consola existentes mientras se define si una migración incremental a React/TypeScript aporta beneficio real.
- Conectar vistas a contratos autenticados, estados de carga/error/desconexión y aislamiento de usuario.
- Implementar actualización en tiempo real solo después de definir autorización, límites y fallback REST.

**Aceptación:** flujos clave navegables con datos de API reales; ningún botón funcionalmente engañoso; diseño accesible y responsive.

## Fase 5 — Windows Desktop

- Crear cliente PySide6 independiente como nuevo módulo, con sesión segura, API común y almacenamiento local mínimo.
- Implementar primero supervisión/análisis/backtesting DEMO; ejecutar tareas pesadas bajo permisos y límites del coordinador.
- Definir empaquetado repetible, actualizaciones y manejo de secretos antes de distribuir.

**Aceptación:** pruebas de conexión, sesión, reconexión, DEMO y paquete instalable en Windows.

## Fase 6 — Android Mobile

- Crear cliente Flutter centrado en supervisión y control remoto; no depender de procesos persistentes en background.
- Usar almacenamiento seguro de sesión, REST/avisos autorizados y estados de conectividad.
- Respetar restricciones de Android para notificaciones y ejecución en segundo plano.

**Aceptación:** pruebas de navegación, autenticación, desconexión, sesión y APK reproducible.

## Fase 7 — Seguridad, rendimiento y pruebas cruzadas

- Completar pruebas negativas de autorización/RLS y revocación de clientes.
- Medir CPU, RAM, latencia y concurrencia con escenario documentado de 8 GB.
- Revisar TLS/gateway, rate limits, secretos, dependencias y recuperación.
- Validar flujos end-to-end entre web, desktop, Android, API, Supabase y worker en staging.

**Aceptación:** resultados medidos; riesgos críticos/altos resueltos o explicitados como bloqueo; no declarar producción certificada por pruebas locales.

## Fase 8 — Entrega y versión mayor

- Instalación limpia, actualización desde la base declarada, migraciones, manuales y changelog.
- Construcción reproducible de backend, web, EXE y APK según los componentes realmente disponibles.
- Informe final que enumere componentes no terminados y límites de despliegue.

**Aceptación:** todas las condiciones de FLOPPI 2.0 se validan individualmente. Si EXE, APK, Supabase staging o integración multiusuario no pasan, el release se mantiene candidato y esas áreas figuran pendientes.

## Próxima acción autorizable

Habilitar una conexión de solo lectura al Supabase staging separado para el preflight de 1.3.2.2. Después de documentar filas afectadas y efectos de la migración, solicitar aprobación específica antes de aplicarla. No usar producción.
