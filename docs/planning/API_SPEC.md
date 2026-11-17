# Contratos API y CLI

API base `/api/v1`, OpenAPI generado y cliente TS fijado a esquema en CI. JSON UTF-8. UUID para identificadores en API. CLI traduce slugs dentro de la org activa. Listas usan cursor opaco ligado a filtros y `limit` 1–100, orden por timestamp e ID. Fechas RFC 3339 UTC, expiración exclusiva. Modelos Pydantic estrictos, claves extras rechazadas, `schema_version` en jobs, eventos y herramientas. Usar enums discriminados por `profile_id`, sin campos abiertos para flags.

## Identidad y errores

Web inicia sesión OIDC Authorization Code + PKCE mediante API. Sesión de servidor, cookie HttpOnly, SameSite=Lax, Secure en TLS (única excepción de piloto localhost). Mutaciones con token CSRF y chequeo Origin. CLI interactiva usa OIDC Device Flow cuando esté disponible o Authorization Code + PKCE mediante loopback. El bootstrap Compose emite token de alta de un solo uso, limitado a loopback y con expiración. La identidad local de piloto se enrola con ese token y puede obtener un token CLI de corta duración vía `POST /auth/local/token` y una sesión web vía `POST /auth/local/login`. Configuración productiva deshabilita bootstrap y auth local. Automatización usa credenciales de servicio de alcance y TTL explícitos. Prohibir tokens en query. CORS cerrado por defecto. API evalúa roles y membresía. Recursos fuera del espacio visible devuelven 404. Sesión y rol se revalidan al conectar SSE y periódicamente durante el stream.

Errores `application/problem+json`: `type,title,status,code,detail,request_id,errors?`. `401` identidad, `403` rol o política con `code=scope_denied|approval_required|kill_switch`, `404` fuera de visibilidad, `409` transición o idempotencia, `422` contrato, `429` presupuesto con Retry-After y `503` dependencia indispensable caída. Respuestas redactadas. Mutaciones con idempotencia requieren `Idempotency-Key` de 16–128 caracteres. La misma clave y hash canónico devuelve el resultado inicial por al menos 24 h. Cuerpo distinto devuelve 409.

## Rutas

Los recursos de proyecto se anidan bajo `/projects/{project_id}` donde se indica `P`. El tenant activo deriva de sesión u organización elegida y se verifica con membresía.

| Método y ruta | Entrada / salida | Privilegio |
|---|---|---|
| GET /health, GET /ready | Liveness/readiness mínimas. 503 en readiness si falta migración o dependencia requerida | Salud |
| GET /auth/login, GET /auth/callback, POST /auth/logout, GET /me | Redirección a IdP y sesión; roles, org activa y permisos efectivos | Usuario/sesión |
| POST /bootstrap/redeem, POST /auth/local/login, POST /auth/local/token, POST /lab/seed | Secreto único + enrolamiento → identidad de admin local; login → sesión; token → token CLI; seed idempotente → IDs laboratorio | Bootstrap / admin local |
| GET/POST /organizations; PATCH /organizations/{id} | Membresías visibles, slug y nombre. Configuración con versión | Admin plataforma/organización |
| GET/POST /memberships; PATCH/DELETE /memberships/{id} | Subject, org, proyecto opcional, role | Admin organización |
| GET/POST /customers; GET/POST /projects; GET/PATCH P | Slugs, nombre, cliente, estado. Cambios con versión/If-Match | Ver proyecto / admin |
| GET/POST P/targets; PATCH P/targets/{id} | Host/URL/IP, entorno, propiedad y etiquetas | Ver / operador |
| GET/POST P/authorizations; POST P/authorizations/{id}/decisions | `valid_from,valid_until,document_evidence_id,scope_rules[],limits`. Decisión `approve\|revoke`, motivo y revisión | Operador / aprobador |
| GET/POST P/assessments; GET P/assessments/{id} | Evaluaciones y estado | Ver / operador |
| POST P/plans; GET P/plans/{id} | Evaluación, autorización/revisión, targets, perfil, opciones. Retorna hash, estimación, riesgo y denegaciones redactadas | Operador |
| POST P/plans/{id}/approvals | Revisión, hash, decisión, motivo y expiración. Retorna approval | Aprobador |
| GET /tools; GET/POST /integrations; PATCH /integrations/{id} | Campos de catálogo, flags habilitados, referencia de secreto y salud | Ver / admin |
| GET/POST P/jobs; GET P/jobs/{id} | POST `{plan_id,plan_hash}` + idempotencia → 202 y Location. GET estado y conteos | Ver / operador |
| POST P/jobs/{id}/cancel | Razón → 202 y estado duradero. Job terminal devuelve estado actual sin repetir IO | Operador |
| GET P/jobs/{id}/events | SSE, `Last-Event-ID` o `after`. Snapshot disponible en GET job | Ver |
| GET P/findings; POST P/findings/{id}/reviews | Filtros y cursor; decisión de confianza y severidad basada en evidencia | Ver / revisor |
| GET/POST P/evidence; GET P/evidence/{id}/download | Carga autorizada para mandato/artefacto, validación MIME/bytes/digest; descarga por flujo autorizado | Operador / lector autorizado |
| GET/POST P/reports; POST P/reports/{id}/publish; GET P/reports/{id}/download | Evaluación y formato, 202 con ID, generación asíncrona, revisión/publicación | Operador / aprobador |
| GET P/risk; GET P/assessments/{id}/comparison?baseline={id} | Distribución y cambios por huella dentro de proyecto | Ver |
| POST P/assessments/{id}/analysis | Tipo de agente y evidencia autorizada → 202 | Analista |
| GET/POST /kill-switch | Estado o cambio registrado con motivo y revisión | Admin autorizado |

### Cargas y eventos del recorrido integrado

```json
{"assessment_id":"7eac185d-3118-4645-8f18-120b086994a4","authorization_id":"27ad3fc6-f994-4ebe-b698-be9638b565de","authorization_revision":2,"target_ids":["9d0048cf-b747-4daf-9bf5-6ba31eec2560"],"profile_id":"web-baseline","options":{"max_requests":12}}
```

El plan devuelve `id,revision,hash,risk,status,effective_limits,denials[]`. Crear plan es simulación, puede devolver `blocked` con 201 y motivo. Encolar recalcula autorización. Job incluye `id,plan_id,state,created_at,started_at,finished_at,counters,terminal_reason`. Transiciones: `queued → running → succeeded|failed|interrupted`; desde queued/running puede avanzar a `cancel_requested → cancelled|interrupted`. Revocación, kill switch y falta de lease impiden nuevas operaciones. Estados terminales conservan evidencia parcial.

SSE usa `id: <seq>` monotónico por job y `event: job.state|tool.progress|finding.created|job.log`. Payload `{schema_version,job_id,seq,ts,level,message,data}`. Datos con allowlist, límite por evento y cursor confirmado después de commit. Heartbeat cada 15 s, reconexión con backoff. Cursor vencido devuelve 410 antes de abrir; cliente refresca job y reinicia desde marca visible. Redactar siempre; mostrar como texto literal.

## Paridad del catálogo web/CLI

| CLI objetivo | Interfaz web | Contrato |
|---|---|---|
| `status`, `auth login/logout` | Estado / inicio y cierre de sesión | Health y sesión |
| `target list`, `authorization list` | Inventario / autorizaciones | GET targets/authorizations |
| `audit plan --project P --target T --profile X` | Planificador | POST plans, resolver evaluación activa o crear una con autorización elegida |
| `audit run --project P --plan ID [--wait]` | Ejecutar plan seleccionado | POST jobs, GET job, SSE |
| `jobs logs ID --follow`, `jobs cancel ID` | Consola y cancelar | Eventos y cancelación |
| `report generate --assessment ID --format html` | Generar y descargar | POST reports, GET reporte y descarga |

Identidad y proyecto efectivos son los del usuario. La web pasa recursos y parámetros tipados al caso de uso compartido. La UI puede copiar una representación CLI con quoting para Bash y PowerShell. Ese texto se usa como ayuda visual. El backend consume exclusivamente el esquema de operación. CLI exit codes: 0 operación/espera exitosa, 2 uso inválido, 3 auth, 4 política, 5 ejecución fallida, 6 cancelada, 7 dependencia no disponible. JSON en stdout en `--json`, diagnóstico en stderr y token vía input seguro.
