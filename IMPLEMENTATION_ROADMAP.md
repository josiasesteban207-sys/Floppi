# FLOPPI — Hoja de ruta de estabilización multiplataforma

**Punto de inicio:** 1.3.2.2.  
**Prioridad inmediata:** validar seguridad en Supabase staging.  
**Política de avance:** cada fase necesita evidencia propia; no inferir staging desde PostgreSQL local ni aprobar una plataforma por compilar otra.

## Fase 0 — Estabilización local y aceptación 1.3.2.2

**Resultado de esta sesión:** 162/162 pytest; Python backend/worker compila; auditoría estática 16/16 checks definitivos PASS con pytest omitido en esa llamada; 4 archivos JS pasan `node --check`; `pip check` limpio.

**Pendiente:** conexión verificable a Supabase staging, catálogo/ledger, policies/grants/privilegios, funciones definer/execute, filas afectadas, backup y autorización para aplicar migration 017. No avanzar mientras siga pendiente la aceptación.

## Fase 1 — Contratos e identidad

1. Validar modelo Auth existente y propiedad de recursos con casos de dos usuarios.
2. Diseñar dispositivo genérico sobre `nodes` cuando compatible; decidir ampliación solo tras revisar esquema.
3. Establecer contrato REST, estados de tarea, correlación, errores y paginación.
4. Definir permiso único en backend y restricciones RLS equivalentes.

## Fase 2 — Coordinación distribuida

1. Reusar cola y leases actuales para trabajos compatibles.
2. Añadir registro/revocación de cliente, heartbeat y capacidades de forma compatible.
3. Validar asignación, cancelación, recuperación, idempotencia y concurrencia.
4. Evitar una segunda cola; demostrar recuperación con workers DEMO simulados.

## Fase 3 — Consolidación backend y proveedores

1. Mantener fuentes DEMO identificadas; establecer adaptador de proveedor sin afirmar integración externa.
2. Añadir proveedores solo con API oficial y credenciales protegidas en backend.
3. Completar contratos de análisis/resultados y trazabilidad de datos.
4. Aplicar límites del host 8 GB y medir benchmark antes/después.

## Fase 4 — Web React + TypeScript

1. Definir alcance incremental y ruta de convivencia con la consola estática.
2. Reutilizar diseño, componentes visuales y endpoints existentes; mantenerlos hasta paridad.
3. Implementar sesión, dashboard, análisis/backtest, tareas, dispositivos e historial.
4. Cubrir errores, carga, desconexión, accesibilidad y pruebas de navegación/API.

## Fase 5 — Desktop PySide6 + EXE

1. Instalar/definir entorno de build reproducible; PySide6 no está instalado actualmente.
2. Implementar cliente autenticado usando API central y almacenamiento seguro del sistema.
3. Cubrir supervisión y ejecución exclusivamente DEMO autorizada.
4. Compilar/instalar EXE en entorno Windows limpio y registrar limitaciones.

## Fase 6 — Android Flutter + APK

1. Flutter 3.44.9 y Dart 3.12.2 están instalados; no existe proyecto móvil en repo.
2. Crear estructura Flutter tras aprobar contratos y modelo visual.
3. Implementar sesión segura, supervisión y control remoto autorizado; respetar background limits.
4. Probar desconexión, reconexión, sesión y APK reproducible.

## Fase 7 — WebSocket y tiempo real

El servidor actual no tiene WebSocket FLOPPI detectado. Diseñar autorización, mensajes/eventos, límites, reconexión y mecanismo REST de recuperación antes de añadirlo. Evitar usar mensajes de socket como fuente autoritativa de estado.

## Fase 8 — QA, seguridad y rendimiento

Pruebas unitarias, API, integración, multiusuario, RLS, migraciones, concurrencia, fallos, Web/Desktop/Android, dependencia y rendimiento. Medir operación bajo 8 GB. Distinguir evidencia local, scratch, staging y producción; no usar producción como prueba.

## Fase 9 — Versión de entrega

Solo cuando estén disponibles y verificadas backend, Supabase/RLS, web, EXE, APK, sincronización, docs y suite cruzada. Cualquier componente no comprobado queda marcado como pendiente y el release no se declara completo.

## Bloqueo accionable actual

La sesión no ofrece CLI Supabase, MCP Supabase ni conexión remota confirmable. Proporcionar un mecanismo seguro de staging ya autenticado; no pegar claves al chat. Primero ejecutar solo consultas de inspección de `SUPABASE_SECURITY_REVIEW.md`; presentar impacto de migration 017; obtener autorización específica antes de aplicarla.
