# FLOPPI — Problemas conocidos y brechas

**Fecha de revisión:** 2026-11-04  
**Versión del checkout:** 1.3.2.2

## Bloqueantes

| ID | Prioridad | Problema | Efecto | Cierre requerido |
|---|---|---|---|---|
| K-01 | Crítica | No hay acceso comprobable al proyecto Supabase staging en esta sesión. La CLI no está instalada, no hay MCP Supabase y la configuración local de staging es PostgreSQL vanilla sin Auth/RPC. | No se puede confirmar el esquema real, RLS/grants, estado de migration 017 o filas/credenciales afectadas. 1.3.2.2 no se acepta. | Conectar staging separado con acceso seguro; inspeccionar en solo lectura; luego autorizar y validar migration 017 en staging. |
| K-02 | Alta | Migration 017 revoca todas las credenciales worker con `expires_at IS NULL`. No se conoce el conteo real de filas afectadas ni los workers que dependen de ellas. | Workers pueden recibir 401 y tareas arrendadas pueden esperar recuperación al desplegar. | Medir impacto en staging, preparar renovación/reemisión y comprobar recuperación antes del despliegue. |
| K-03 | Alta | No hay aplicaciones desktop PySide6 ni mobile Flutter en el checkout. | Requisito EXE/APK del objetivo 2.0 no está implementado ni probado. | Diseñar contratos compartidos después de cerrar security gate; construir clientes por separado. |

## Brechas funcionales del objetivo 2.0

| ID | Prioridad | Estado observado | Acción futura |
|---|---|---|---|
| K-04 | Alta | Web actual es consola estática HTML/CSS/JS; no React/TypeScript. | Evaluar evolución incremental sin reemplazar la consola hasta contar con contratos y pruebas. |
| K-05 | Alta | No se encontró servidor WebSocket FastAPI ni sincronización en tiempo real de clientes. | Definir autorización y necesidad; implementar canal real y fallback REST con pruebas si se aprueba en plan. |
| K-06 | Alta | No se encontraron módulos Scikit-learn, evaluación/versionado de modelos ni detección de drift. | Planificar módulos ML después de aceptar 1.3.2.2 y verificar datos/validación temporal. |
| K-07 | Alta | Proveedor identificado es sintético DEMO; no hay adaptadores externos confirmados. | Mantener etiquetas DEMO y añadir integraciones solo por API oficial/documentada. |
| K-08 | Alta | Workers actuales ejecutan backtests DEMO y reportan recursos; no equivalen al ciclo genérico multiusuario de dispositivos del prompt. | Extender mecanismos actuales sin crear una segunda cola; comprobar propietario, capacidad, leases y revocación. |
| K-09 | Alta | Auth/token y ownership existen en superficies concretas, pero no hay evidencia de aislamiento completo para todas las futuras APIs y clientes. | Probar dos usuarios, permisos positivos/negativos y RLS real en staging. |
| K-10 | Media | No se verificó compatibilidad de Blacki y Blanquita conectados simultáneamente ni recuperación cruzada real. | Ejecutar pruebas distribuidas DEMO en entorno separado y registrar límites. |
| K-11 | Media | No se midieron rendimiento, concurrencia, memoria ni latencias con el servidor de 8 GB descrito. | Establecer benchmark y luego comparar antes/después en hardware o entorno equivalente. |
| K-12 | Media | TLS, gateway/proxy externo y rate limiting compartido no están validados por las pruebas locales. | Verificar infraestructura de staging antes de exposición externa. |

## Evidencia y limitaciones

- `reports/audit_latest.md` describe la última auditoría como 17/17 y 162 pruebas, con fecha 2026-11-02. Esta inspección del 2026-11-04 no volvió a ejecutar la suite.
- La prueba de migration 017 documentada usó una base PostgreSQL aislada, backup local de 851 bytes y filas sintéticas; no valida una instancia Supabase real.
- Migration 017 no cambia políticas RLS, pero eso no demuestra que las políticas/grants efectivos del proyecto remoto sean correctos.
- El checkout contiene migraciones 001–007 y 010–017. Los números 008 y 009 están ausentes intencionalmente según la documentación; no deben inventarse ni rellenarse.
- No se inspeccionaron ni imprimieron los valores de `.env` o `.env.staging`.
- No se modificaron datos, configuraciones de producción ni secretos.
