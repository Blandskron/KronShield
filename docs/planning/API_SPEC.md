# Contratos API y CLI

API base `/api/v1`, OpenAPI generado y cliente TS fijado a esquema en CI. JSON UTF-8. UUID para identificadores en API. La CLI usa UUID de organización y proyecto. Las listas actuales aceptan `limit` de 1 a 100 y `after` como UUID de la página anterior. El campo `next_cursor` vale `null` al terminar. Fechas RFC 3339 UTC, expiración exclusiva. Los modelos de entrada rechazan claves adicionales. Las simulaciones guardadas incluyen `schema_version` y el perfil `scope-review`.

## Identidad y errores

En el piloto, `/auth/mode` devuelve `pilot` y el primer acceso usa `/bootstrap/redeem`. La web usa `/auth/local/login` y la CLI emite y revoca credenciales con `/auth/local/token` y `/auth/local/revoke`. En modo OIDC, la web usa `/auth/login` y `/auth/callback`; la CLI consume un access token emitido por el proveedor. Las mutaciones de una sesión web validan `Origin` y el token CSRF. [Operación del piloto](../OPERATIONS.md#inicio-y-comprobaciones)

La secuencia siguiente recoge el contrato objetivo de identidad. El OpenAPI versionado indica las rutas disponibles.

Web inicia sesión OIDC Authorization Code + PKCE mediante API. Sesión de servidor, cookie HttpOnly, SameSite=Lax, Secure en TLS (única excepción de piloto localhost). Mutaciones con token CSRF y chequeo Origin. CLI interactiva usa OIDC Device Flow cuando esté disponible o Authorization Code + PKCE mediante loopback. El bootstrap Compose emite token de alta de un solo uso, limitado a loopback y con expiración. La identidad local de piloto se enrola con ese token y puede obtener un token CLI de corta duración vía `POST /auth/local/token` y una sesión web vía `POST /auth/local/login`. Configuración productiva deshabilita bootstrap y auth local. Automatización usa credenciales de servicio de alcance y TTL explícitos. Prohibir tokens en query. CORS cerrado por defecto. API evalúa roles y membresía. Recursos fuera del espacio visible devuelven 404. Sesión y rol se revalidan al conectar SSE y periódicamente durante el stream.

Errores `application/problem+json`: `type,title,status,code,detail,request_id,errors?`. `401` identidad, `403` rol o política con `code=scope_denied|approval_required|kill_switch`, `404` fuera de visibilidad, `409` transición o idempotencia, `422` contrato, `429` presupuesto con Retry-After y `503` dependencia indispensable caída. Respuestas redactadas. Mutaciones con idempotencia requieren `Idempotency-Key` de 16–128 caracteres. La misma clave y hash canónico devuelve el resultado inicial por al menos 24 h. Cuerpo distinto devuelve 409.

### Configurar la autenticación de TASK-012

Aplica las [migraciones PostgreSQL](DATABASE_DESIGN.md#ejecutar-la-migración-inicial) y provisiona las identidades por emisor y subject, con sus membresías de organización y proyecto. Instala las dependencias con `uv sync --locked --extra api --extra postgres`.

Configura el DSN del login de ejecución en `PENTEST_AGENT_RUNTIME_URL` y el origen público HTTPS en `PENTEST_AGENT_WEB_ORIGIN`, sin barra final. Configura el proveedor con estas variables de entorno.

| Variable | Valor |
|---|---|
| `PENTEST_AGENT_OIDC_ISSUER` | Emisor exacto de los tokens |
| `PENTEST_AGENT_OIDC_AUTHORIZE_URL`, `PENTEST_AGENT_OIDC_TOKEN_URL`, `PENTEST_AGENT_OIDC_JWKS_URL` | Endpoints HTTPS de autorización, intercambio de código y claves de firma RS256 |
| `PENTEST_AGENT_OIDC_INTROSPECTION_URL` | Endpoint HTTPS de introspección de access tokens |
| `PENTEST_AGENT_OIDC_CLIENT_ID`, `PENTEST_AGENT_OIDC_CLIENT_SECRET` | Cliente confidencial con `client_secret_basic` |
| `PENTEST_AGENT_OIDC_API_AUDIENCE`, `PENTEST_AGENT_OIDC_API_SCOPE` | Audiencia distinta de la del cliente web y scope requerido para la API |

Registra `<origen>/api/v1/auth/callback` como URI de retorno fija. Inicia el servicio detrás del proxy HTTPS con `uv run --no-sync uvicorn --factory adapters.api.app:create_app --no-access-log`. Excluye la cadena de consulta del callback de los registros del proxy. En despliegue, limita las solicitudes al inicio de sesión en el proxy y elimina los registros expirados de `pentest_agent.login_attempt` y `pentest_agent.web_session` con mantenimiento de base de datos.

El navegador obtiene el token CSRF en `GET /api/v1/me` y lo envía en `X-CSRF-Token` junto al `Origin` del sitio en mutaciones. El inicio de sesión rota la cookie de sesión y el token CSRF, y el cierre revoca la sesión en PostgreSQL. La sesión web tiene una vigencia de ocho horas. La introspección se aplica en cada petición con credenciales de CLI y requiere `active`, emisor, audiencia, subject, scope y expiración. El flujo de adquisición y almacenamiento de credenciales en el cliente CLI corresponde a TASK-020. [OpenID Connect Core](https://openid.net/specs/openid-connect-core-1_0.html) · [Introspección OAuth 2.0](https://www.rfc-editor.org/rfc/rfc7662.html)

Consulta el rol de organización con `org_id` o los permisos de proyecto con `org_id` y `project_id` en `GET /api/v1/me`. La membresía de proyecto determina los permisos y se consulta en cada operación. Una membresía administrativa de organización no concede permisos de proyecto por sí sola.

| Rol de proyecto | Permisos |
|---|---|
| `viewer` | Leer |
| `operator` | Leer, gestionar objetivos y evaluaciones, y solicitar autorizaciones |
| `approver` | Leer y decidir sobre autorizaciones |
| `project_admin` | Leer y administrar el proyecto |

### Inventario y autorizaciones de TASK-013

Además de la configuración OIDC, define `PENTEST_AGENT_DOCUMENT_KEY` con una clave AES-256 aleatoria de 32 bytes codificada en Base64. Usa la misma clave en todas las instancias y conserva una copia recuperable separada de la base. Los documentos se cifran antes de guardarse en PostgreSQL. [Cifrado autenticado de Cryptography](https://cryptography.io/en/latest/hazmat/primitives/aead/)

El administrador de base provisiona las identidades y los administradores de plataforma en `pentest_agent.platform_admin`. Un administrador de plataforma puede crear una organización indicando una identidad distinta como administradora inicial. La membresía de organización es requisito para consultar sus datos. Un administrador de organización crea clientes y proyectos y obtiene el rol `project_admin` en los proyectos que crea. Las membresías adicionales se administran con `GET`, `PUT` y `DELETE` en `/memberships`, con `org_id` y `project_id` opcional.

Usa `org_id` como parámetro de consulta en las rutas de clientes, proyectos y recursos de proyecto. Las listas aceptan `after` con el UUID que devuelve `next_cursor`. Los cambios de inventario requieren `If-Match` con la versión entre comillas, como `"1"`. Eliminar una organización la suspende y eliminar un proyecto lo archiva. Los clientes con proyectos conservan la referencia y devuelven 409 al intentar eliminarlos.

El operador envía el PDF como cuerpo binario de hasta 1 MiB a `POST /projects/{project_id}/authorization-documents` con `Content-Type: application/pdf`. La respuesta incluye el ID y el SHA-256. El documento se descarga como adjunto mediante `GET /projects/{project_id}/authorization-documents/{document_id}`. El acceso al contenido se limita a quien lo subió y a los aprobadores del proyecto.

El operador registra el ID del documento, la identidad de quien delega, la vigencia, las reglas y los límites en `POST /projects/{project_id}/authorizations`. Otro usuario con rol de aprobador registra su decisión y motivo en `POST /projects/{project_id}/authorizations/{id}/decisions`. Para corregir un borrador o renovar una autorización revocada o vencida, usa `POST /projects/{project_id}/authorizations/{id}/revisions` con `previous_revision`. Antes de reemplazar una autorización aprobada que aún puede entrar en vigor, registra su revocación. Para recuperar un historial concreto, consulta el recurso con `revision`.

### Evaluaciones y planes de revisión de alcance

Un operador crea una evaluación con `POST /projects/{project_id}/assessments` y un objeto `{"label":"Revisión de alcance"}`. La lista y el detalle están disponibles para miembros del proyecto. Usa `org_id` como selector de organización.

`POST /projects/{project_id}/plans` registra una simulación con el perfil `scope-review`. Envía `assessment_id`, `authorization_id`, `authorization_revision` y entre uno y 50 UUID de inventario en `target_ids`. La solicitud requiere `Idempotency-Key` de 16 a 128 caracteres ASCII visibles. Repetir la misma selección con la misma clave devuelve el plan original, aunque cambie el orden de los UUID. Una selección diferente con esa clave devuelve 409.

El plan conserva la revisión, el digest del documento, las reglas, los límites, las versiones de los activos y el resultado por activo. Devuelve `status: reviewed` o `status: blocked`, junto con `execution: disabled`. `GET /projects/{project_id}/plans/{id}` consulta el registro original y `GET /projects/{project_id}/plans/{id}/events` devuelve el evento de creación. El plan y la entrada de outbox del evento se confirman en la misma transacción. `GET /projects/{project_id}/plans/{id}/report` descarga un adjunto HTML determinista con el hash del plan, la revisión de autorización y el resultado registrado para cada activo.

`POST /projects/{project_id}/plans/{id}/verify` recibe `{"hash":"…"}` y vuelve a comparar la autorización y el inventario actuales con el registro. Devuelve 409 si el hash es incorrecto, la revisión quedó desactualizada o el plan está bloqueado. Los activos referenciados por planes conservan su relación histórica en PostgreSQL.

### Importación histórica y contrato publicado

`POST /projects/{project_id}/legacy-imports` recibe el archivo como `application/octet-stream` con `org_id` y `format=json|sqlite`. Identifica el lote por el SHA-256 de sus bytes dentro del proyecto. El detalle se consulta con `GET /projects/{project_id}/legacy-imports/{id}`. Los hallazgos importados muestran procedencia `legacy`, confianza `unverified` y la confianza original si estaba registrada.

El esquema [OpenAPI v1](../../contracts/openapi-v1.json) se publica en `/api/v1/openapi.json`. Las respuestas de error usan `application/problem+json` con un identificador de petición. `/api/v1/health` mide disponibilidad del proceso y `/api/v1/ready` comprueba PostgreSQL y la revisión de Alembic. Desde la raíz, genera el contrato con `uv run --no-sync python -m contracts.export`. Desde `frontend`, ejecuta `npm run contract` para generar los tipos TypeScript.

## Rutas y contratos objetivo

El [OpenAPI versionado](../../contracts/openapi-v1.json) enumera las rutas disponibles. La matriz siguiente también conserva contratos de etapas futuras. Los recursos de proyecto se anidan bajo `/projects/{project_id}` donde se indica `P`. El tenant activo deriva de sesión u organización elegida y se verifica con membresía.

| Método y ruta | Entrada / salida | Privilegio |
|---|---|---|
| GET /health, GET /ready | Liveness/readiness mínimas. 503 en readiness si falta migración o dependencia requerida | Salud |
| GET /auth/login, GET /auth/callback, POST /auth/logout, GET /me | Redirección a IdP y sesión; roles, org activa y permisos efectivos | Usuario/sesión |
| POST /bootstrap/redeem, POST /auth/local/login, POST /auth/local/token, POST /lab/seed | Secreto único + enrolamiento → identidad de admin local; login → sesión; token → token CLI; seed idempotente → IDs laboratorio | Bootstrap / admin local |
| GET/POST /organizations; PATCH /organizations/{id} | Membresías visibles, slug y nombre. Configuración con versión | Admin plataforma/organización |
| GET/PUT /memberships; DELETE /memberships/{user_id} | Subject, org, proyecto opcional, role | Admin organización |
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

### Ejemplo de simulación disponible

```json
{"assessment_id":"7eac185d-3118-4645-9fba-ac563f9063db","authorization_id":"27ad3fc6-f994-4e87-97c1-6593eb399cfc","authorization_revision":2,"target_ids":["9d0048cf-b747-4daf-8573-39a6095208f8"],"profile_id":"scope-review"}
```

Envía el objeto a `POST /api/v1/projects/{project_id}/plans?org_id=...` con una clave `Idempotency-Key`. El estado registrado es `reviewed` o `blocked` y el resultado incluye `execution: disabled`.

### Cargas y eventos del diseño objetivo

```json
{"assessment_id":"7eac185d-3118-4645-8f18-120b086994a4","authorization_id":"27ad3fc6-f994-4ebe-b698-be9638b565de","authorization_revision":2,"target_ids":["9d0048cf-b747-4daf-9bf5-6ba31eec2560"],"profile_id":"web-baseline","options":{"max_requests":12}}
```

El plan devuelve `id,revision,hash,risk,status,effective_limits,denials[]`. Crear plan es simulación, puede devolver `blocked` con 201 y motivo. Encolar recalcula autorización. Job incluye `id,plan_id,state,created_at,started_at,finished_at,counters,terminal_reason`. Transiciones: `queued → running → succeeded|failed|interrupted`; desde queued/running puede avanzar a `cancel_requested → cancelled|interrupted`. Revocación, kill switch y falta de lease impiden nuevas operaciones. Estados terminales conservan evidencia parcial.

SSE usa `id: <seq>` monotónico por job y `event: job.state|tool.progress|finding.created|job.log`. Payload `{schema_version,job_id,seq,ts,level,message,data}`. Datos con allowlist, límite por evento y cursor confirmado después de commit. Heartbeat cada 15 s, reconexión con backoff. Cursor vencido devuelve 410 antes de abrir; cliente refresca job y reinicia desde marca visible. Redactar siempre; mostrar como texto literal.

## Paridad del catálogo web/CLI

El cliente disponible ofrece `status`, `auth login`, `auth whoami`, `auth logout`, `project organizations`, listas de proyectos, objetivos, evaluaciones y autorizaciones, `lab seed`, `plan create`, `plan show` y `plan report`. La web y estos comandos comparten los ID y permisos de los recursos. Para los comandos locales sobre capturas, usa los grupos `audit` y `report`. [Comandos del piloto](../../README.md#piloto-en-docker-compose)

La matriz siguiente conserva los nombres **objetivo** de las fases posteriores.

| CLI objetivo | Interfaz web | Contrato |
|---|---|---|
| `status`, `auth login/logout` | Estado / inicio y cierre de sesión | Health y sesión |
| `target list`, `authorization list` | Inventario / autorizaciones | GET targets/authorizations |
| `audit plan --project P --target T --profile X` | Planificador | POST plans, resolver evaluación activa o crear una con autorización elegida |
| `audit run --project P --plan ID [--wait]` | Ejecutar plan seleccionado | POST jobs, GET job, SSE |
| `jobs logs ID --follow`, `jobs cancel ID` | Consola y cancelar | Eventos y cancelación |
| `report generate --assessment ID --format html` | Generar y descargar | POST reports, GET reporte y descarga |

Identidad y proyecto efectivos son los del usuario. La web pasa recursos y parámetros tipados al caso de uso compartido. La UI puede copiar una representación CLI con quoting para Bash y PowerShell. Ese texto se usa como ayuda visual. El backend consume exclusivamente el esquema de operación. CLI exit codes: 0 operación/espera exitosa, 2 uso inválido, 3 auth, 4 política, 5 ejecución fallida, 6 cancelada, 7 dependencia no disponible. JSON en stdout en `--json`, diagnóstico en stderr y token vía input seguro.
