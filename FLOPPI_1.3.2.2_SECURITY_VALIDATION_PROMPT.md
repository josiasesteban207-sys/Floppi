# FLOPPI 1.3.2.2 — SECURITY VALIDATION CORE

## REGLAS OBLIGATORIAS DE DESARROLLO FLOPPI

Eres un ingeniero de software sénior encargado de continuar FLOPPI.

Antes de modificar:

1. Inspecciona todo el proyecto y su arquitectura actual.
2. Identifica la versión, módulos, endpoints, base de datos y pruebas existentes.
3. Reutiliza el código existente cuando sea correcto.
4. No elimines funcionalidades que ya funcionan.
5. No reemplaces módulos completos sin justificación técnica.
6. Mantén compatibilidad con Python 3.10.
7. Conserva FastAPI, PostgreSQL/Supabase y la arquitectura distribuida.
8. Mantén las políticas RLS de Supabase. Nunca desactives RLS para facilitar el desarrollo.
9. No escribas credenciales ni secretos dentro del código.
10. FLOPPI es una plataforma educativa DEMO: no debe ejecutar operaciones financieras reales ni conectar órdenes reales con brokers.

Al terminar cada versión:

- Ejecuta las pruebas automatizadas y la auditoría del proyecto.
- Comprueba los endpoints y las migraciones dentro de los entornos autorizados.
- Documenta los cambios y las limitaciones pendientes.
- Incluye instrucciones de instalación y actualización.
- No declares pruebas exitosas si no se ejecutaron realmente.
- Entrega un informe con versión anterior y nueva, funcionalidades, archivos creados/modificados, migraciones, pruebas y resultados reales, auditoría, riesgos, limitaciones y próximo objetivo.
- No avances a la siguiente etapa hasta completar y validar la actual.

## Etapa extra — Security Validation Core

Esta etapa se ejecuta después de **FLOPPI 1.3.2 — Strategy Lab** y antes de **FLOPPI 1.4.0 — Machine Learning Lab**. Su propósito es validar y cerrar de forma segura los controles de seguridad incorporados, sin ampliar el alcance funcional del laboratorio de estrategias.

### Objetivos

1. Inspeccionar la arquitectura, versión, módulos, endpoints, migraciones, configuración y pruebas existentes antes de cambiar código.
2. Validar autenticación Supabase, autorización por roles, aislamiento por propietario, sesiones de navegador y controles de acceso a tareas, informes y preferencias.
3. Revisar la seguridad de workers, expiración/revocación de credenciales y compatibilidad de Blacki y Blanquita.
4. Revisar validación de entradas, manejo de errores, redacción de datos sensibles, límites de API y configuración de despliegue.
5. Verificar migraciones y políticas RLS sin desactivar RLS ni debilitar permisos.
6. Validar la migración 017 (`worker_credentials.expires_at`) en una copia aislada y desechable de un backup autorizado. Nunca aplicar una migración destructiva a producción para probarla.
7. Si se requiere Supabase staging, usar un proyecto separado y autorizado; verificar primero esquema, filas afectadas, RLS, RPC y credenciales antes de aplicar cambios.
8. Ejecutar pruebas automatizadas, auditoría, comprobaciones de endpoints y validaciones de migraciones disponibles; separar resultados locales de comprobaciones externas pendientes.
9. Documentar riesgos residuales y criterios de salida. No llamar a esta etapa certificación de producción.

### Límites obligatorios

- No desactivar RLS ni conceder acceso amplio a `anon` o `authenticated` para facilitar pruebas.
- No imprimir, copiar, registrar ni incluir secretos en informes, prompts, fixtures o repositorios.
- No rotar ni revocar credenciales reales sin autorización operativa explícita y un plan de recuperación.
- No ejecutar órdenes, operaciones financieras reales ni conectar brokers.
- No ejecutar reparaciones destructivas automáticamente.
- No avanzar a FLOPPI 1.4.0 mientras queden criterios de salida obligatorios sin validar.
- No generar ZIP como requisito de esta ni de otras etapas.

### Criterios de salida e informe

Registrar:

- Versión anterior y nueva, y estado de la etapa: completa, pendiente o bloqueada por dependencia externa.
- Controles inspeccionados y archivos creados o modificados.
- Migraciones verificadas, entorno usado y si fueron aplicadas; nunca presentar una prueba scratch como aplicación real de staging.
- Comandos ejecutados y resultados exactos de pruebas, auditoría y comprobaciones de endpoints.
- Verificaciones de autenticación, roles, RLS, workers, secretos y despliegue que sí se realizaron.
- Comprobaciones externas pendientes, riesgos, limitaciones e instrucciones para continuar de forma segura.
- Próximo objetivo: completar las verificaciones pendientes de esta etapa antes de FLOPPI 1.4.0.

La etapa **FLOPPI 1.6.0 — Security Hardening** sigue siendo una fase posterior de la hoja de ruta. La existencia de esta etapa de validación 1.3.2.2 no la reemplaza ni la marca como completada.
