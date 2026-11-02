# FLOPPI Security Core 1.3.1 — Release Criteria

**Estado:** implementación autorizada; release no aprobado. La matriz local es evidencia de candidato, no certificación del despliegue.  
**Regla de decisión:** cualquier criterio Critical pendiente bloquea el release.

## 1. Puertas de autorización

- [x] El propietario autorizó explícitamente implementación de FLOPPI Security Core 1.3.1 (2026-11-01).
- [x] Se decidió integrar `@supabase/supabase-js` empaquetado; service role no se expone al navegador.
- [ ] Se identifica un proyecto Supabase de staging aislado, dos usuarios de prueba y credenciales temporales de Blacki/Blanquita.
- [ ] Se identifica el proxy/gateway, TLS, firewalls, publicación de puertos y owner de despliegue.
- [x] Estrategia local: `app_metadata.role` administrado por canal confiable de Supabase; no hay API pública para autoasignar rol.
- [x] El candidato general queda versionado como 1.3.1; 1.3.0 permanece como release anterior.

## 2. Requisitos de seguridad

Las casillas marcadas verifican el candidato local. Las verificaciones de
staging y de infraestructura desplegada siguen pendientes y bloquean el release.

- [x] `APP_ENV` ausente, vacío o desconocido no arranca; solo valores documentados son válidos (pruebas locales).
- [x] La configuración de producción exige HTTPS/secretos/origins correctos y rechaza placeholders (validación local; despliegue no verificado).
- [ ] Toda ruta tiene clasificación documentada (pública, autenticada, admin o worker), owner y permiso.
- [x] Rutas de usuario exigen identidad válida fuera de DEMO local y comprueban propiedad (suite local).
- [x] Rutas operativas, exports y resolución de incidentes exigen rol administrativo confiable; denegación por defecto (suite local).
- [x] Ningún `user_metadata`, header o campo de cliente puede elevar privilegios; el rol se obtiene de `app_metadata` (revisión y pruebas locales).
- [ ] Auth caído, token inválido/expirado/revocado y worker auth indisponible fallan de forma explícita y segura (credenciales worker inválidas/sin expiración tienen pruebas locales; Auth/revocación real pendiente).
- [ ] Service role solo en backend; no está en bundle, configuración, browser storage, worker o logs (el bundle no contiene service role; faltan pruebas canary para los otros canales).
- [ ] RLS permanece habilitada. ACL de tablas y RPC se verifican en staging con `anon`, `authenticated`, usuario A/B y `service_role`.
- [ ] Funciones `SECURITY DEFINER` tienen owner, `search_path`, firmas, SQL dinámico y grants revisados; clientes no pueden ejecutar funciones privilegiadas.
- [ ] Worker tokens se vinculan a nodo, tienen ciclo de vida/revocación probado, requieren HTTPS remoto y no permiten usar leases ajenos/expirados.
- [ ] Puerto HTTP del API no es accesible desde redes públicas; TLS/certificado y upstream privado están comprobados.
- [ ] Rate limits operan de forma consistente entre instancias y limitan endpoints sensibles/costosos.
- [ ] Secret canaries no aparecen en logs/eventos, diagnósticos, CSV/JSON ni errores; retención se aplica según política aprobada.
- [ ] SBOM/inventario reproducible de dependencias y fuentes/fecha de advisory están archivados; vulnerabilidades tienen disposición explícita.

## 3. Compatibilidad funcional y calidad

- [x] Python 3.10 build y suite completa ejecutados con resultado registrado.
- [ ] Pruebas positivas y negativas de login/roles, usuario A/B, API, Supabase RLS/RPC, TLS y worker pasan en el entorno acordado.
- [ ] Blacki y Blanquita completan heartbeat, claim, lease, finalización y recuperación con credenciales independientes.
- [ ] Endpoints smoke testados bajo los roles previstos; OpenAPI revisado por cambios de contrato.
- [x] Tests de análisis, historial, backtesting, scheduler, monitoreo, eventos y diagnósticos no tienen regresiones (suite local).
- [ ] La consola web completa ciclo login/refresh/logout/expiración y no hace solicitudes privadas sin token válido.
- [x] No se introducen órdenes reales, integración con brokers, transferencias ni cambios a algoritmos financieros.
- [x] Se ejecuta auditoría automatizada con salida real y alcance descrito; auditoría independiente sigue pendiente.
- [ ] No se declara aprobada ninguna prueba no ejecutada; casos bloqueados y limitaciones quedan visibles.

## Evidencia local disponible

- `python tools\audit.py --version 1.3.1`: 16/16 checks; suite en Python 3.10.0: 138 passed.
- `npm audit --json`: cero vulnerabilidades para 36 dependencias; build web completado.
- Browser smoke en `APP_ENV=development`: página, health, auth config, bundle y CSS disponibles.
- Migration 017 fue creada y probada estáticamente, pero no se ejecutó contra PostgreSQL.

## Bloqueos actuales

Sin `.env` ni Supabase staging: login/refresh/logout reales, RLS/grants/RPC, aislamiento A/B y aplicación de migraciones no se verificaron. Sin gateway configurado: TLS público, firewall y rate limiting no se probaron. Blacki/Blanquita no estuvieron conectados en paralelo y no hubo auditoría independiente. Estos puntos bloquean el release; no se deben marcar como aprobados.

## 4. Esquema, migración y rollback

- [ ] Se demuestra si se necesita o no una nueva migración; decisión respaldada por permisos efectivos y requisitos de auditoría.
- [ ] Si se necesita SQL: número revisado contra historial real (incluidos huecos conocidos), DDL idempotente, RLS, grants por rol, RPC segura, prueba de upgrade y rollback revisado.
- [ ] Migraciones se prueban primero en staging con snapshot/restauración; no hay aplicación directa a producción desde esta fase documental.
- [ ] Existe artefacto de backup verificado y plan de restauración probado para datos/esquema relevantes.
- [ ] Existe plan de reversión de código/configuración probado que conserva autenticación/RLS; no se revierte abriendo rutas operativas.
- [x] Release notes, changelog, instrucciones de instalación/actualización y limitaciones se actualizan con hechos comprobados.

## 5. Evidencias mínimas para aprobar

1. Hash exacto del código y configuración desplegados.
2. Comandos, versión de Python, salida completa y reportes de tests.
3. Evidencia de roles/RLS/ACL/RPC de staging sanitizada.
4. Resultados de smoke tests de endpoints por categoría de rol.
5. Evidencia de TLS, exposición de puertos, límites de gateway y expiración/revocación.
6. Resultado de análisis de dependencias con fecha y disposición de advisories.
7. Resultados de pruebas de logs/exports usando secretos señuelo.
8. Auditoría final independiente, riesgos residuales, dueños y aprobaciones.
9. Registro explícito de que no se ejecutan operaciones financieras reales ni órdenes de broker.

## 6. Criterios de rechazo

Rechazar/bloquear release si: alguna ruta operativa queda anónima sin aprobación de alcance; se desactiva RLS para facilitar acceso; la UI requiere un secreto privilegiado; un token puede reusarse tras revocación/expiración conforme al contrato; un worker puede afectar un job de otro nodo; HTTP remoto transmite credenciales; no se puede distinguir resultado pendiente de prueba aprobada; o los riesgos Critical no tienen evidencia de mitigación.
