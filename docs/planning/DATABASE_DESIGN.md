# Persistencia y aislamiento multiempresa

El esquema PostgreSQL disponible usa el namespace `pentest_agent` y la tabla `public.pentest_agent_alembic_version`. Las revisiones 0001 a 0006 incorporan tenancy, autenticación, inventario y decisiones, planes offline, importación histórica y cuentas y membresías del piloto. Las sesiones, los documentos cifrados y los planes se almacenan en PostgreSQL. Los comandos locales de resultados siguen usando SQLite y JSON. [Copia y recuperación](../OPERATIONS.md#copia-de-postgresql-y-clave-de-documentos)

Las entidades y dependencias adicionales de la matriz corresponden al modelo objetivo.

PostgreSQL, SQLAlchemy 2 y Alembic. UUID opacos en recursos, timestamps UTC, claves de máquina estables para tipos y JSONB validado para extensiones. Usar constraints de unicidad y estado de dominio. Los campos de versión y hash se congelan al aprobar. Campos de plazo y evidencia derivados por servicio, nunca por cliente.

| Entidad | Relación y diseño |
|---|---|
| Organization | Raíz de tenancy. Slug único. Estado, política de retención y kill switch. |
| User | Identidad global por `(issuer, subject)` único. PII mínima. |
| Role | Permisos estables por acción. `organization_membership(org_id,user_id,role_id)` y `project_membership(org_id,project_id,user_id,role_id)`. |
| Customer | Pertenece a org. Slug único por org, datos de contacto restringidos. |
| Project | Pertenece a Customer en la misma org, slug único por org. Entorno y estado. |
| Authorization | Proyecto, solicitante, verificador, quien delega, estado, referencia y digest de documento, [inicio, fin), revisiones. |
| Scope | Reglas inmutables por autorización, revisión, acción allow/deny, tipo FQDN, subdominio, IP, CIDR, aplicación/ruta y entorno. Métodos, puertos, técnicas, tercero y cuotas. |
| Target | Proyecto, slug, entorno, dirección canónica y metadatos de propiedad. Unique en proyecto, entorno y dirección. |
| Assessment | Proyecto, actor, etiqueta y estado de ciclo de vida. Una evaluación admite varios planes/jobs. |
| AssessmentPlan | Assessment, revisión, targets y técnicas, opciones canónicas, autorización/revisión, hash y estimación. Relación explícita plan-target. |
| ScanJob | Plan, actor, origen, estado, lease, fencing token, intento, conteos, timestamps y error tipado. Un job por ejecución de plan en v0.5.0. |
| ToolExecution | Job, técnica, adaptador, artefacto y versión/digest, decisión de política e IP efectiva, start/end, código de salida. Identidad única por intento y paso. |
| Finding | Assessment, job y ejecución, target, tipo, confianza, gravedad, estado, localización redactada y huella para comparar. UNIQUE en job y huella. |
| Evidence | Ejecución, llave de objeto generada, digest SHA-256, tamaño, MIME, fechas de captura/expiración, retención legal y clasificación. M:N con hallazgo. |
| Vulnerability | Catálogo global externo de solo lectura. Clave fuente + identificador + versión. Relación hallazgo-contexto con reglas de correlación y confianza. |
| RiskScore | Finding y revisión. Esquema y vector CVSS, fuente, fecha y justificación del riesgo contextual. Índice por finding/fecha. |
| Report | Assessment, versión, autor/revisor, snapshot, formato, estado, digest, objeto y proveedor si aplica. Unique por assessment/formato/versión. |
| AuditLog | Org, proyecto opcional, secuencia, actor, acción, resultado, timestamp, request ID, hash anterior y hash actual. Append-only y anclaje. |
| Approval | Revisión y hash de plan + tipo, actor, decisión, motivo, vigencia y revocación. Autorizaciones tienen aprobaciones de su revisión. |
| Outbox / JobEvent / Idempotency | Outbox por transición, evento por `(org_id,job_id,seq)`, clave idempotente por actor y operación con hash de cuerpo. |

La migración `0004_scope_review` implementa evaluaciones y planes de revisión de alcance. La instantánea y su hash se guardan con las referencias de autorización y activos, el evento de creación y su entrada en outbox. El rol de ejecución de la API tiene acceso de solo inserción o lectura a estas tablas según el recurso, con claves compuestas y políticas de organización y proyecto.

## Invariantes

- Tablas de proyecto referencian `(org_id, project_id, id)` en recursos de alcance de proyecto cuando corresponda. Para recursos de org utilizar `(org_id,id)`. Evitar FK simple que permita referencias cruzadas. Restrict de borrado en custodia y aprobaciones. Relaciones de membresía y permisos se evalúan en cada operación.
- `FORCE ROW LEVEL SECURITY` en tablas de tenant. Contexto transaccional `SET LOCAL` sobre conexión sin rol propietario, superuser ni BYPASSRLS. Contexto ausente deniega. Autenticación determina sujeto y organización, sin confiar en IDs del cliente. Política de proyecto restringe membresía; procesos internos usan roles mínimos y lease ligado al job. Verificar reuso del pool con contextos alternados. [Row security de PostgreSQL](https://www.postgresql.org/docs/current/ddl-rowsecurity.html).
- Índices: prefijos de FK compuesta, `(org_id,project_id,created_at DESC,id)` para listas, `(state,run_after,id)` parcial para pendientes de dispatcher, `(org_id,job_id,seq)` para SSE, `(retention_until)` parcial para evidencia sin hold, `(org_id,seq)` para cadena. Validar con EXPLAIN y volumen de fixture. Bloquear escrituras de bitácora por rol de app salvo función append dedicada.
- Encolar y registrar evento con transacción. Transferir objetos en zona temporal, validar checksum y luego publicar referencia. Un reconciliador elimina huérfanos temporales vencidos y detecta referencias cuyo objeto falta. PostgreSQL confirma estado; tiempo de retención no depende de eventos Redis.

## Evolución prevista de migraciones y legado

1. Alembic inicial crea org, usuarios/roles, proyectos, autorizaciones, targets y RLS. Segunda revisión añade ejecución, outbox, evidencia y eventos. Cambios expand/contract y backfills reiniciables por rango. Usuario de migraciones distinto de API/worker.
2. Importador CLI offline, con `--dry-run` y org/proyecto obligatorios. Lee SQLite en modo solo lectura o JSON validado con límites. Reporta errores por registro y deduplica por digest de origen más ID/fila. No activa jobs. Marca `origin=legacy` y confianza no verificada. Sin inventar fecha, autorización ni URL específica ausentes. Conservar procedencia y preservar original bajo política de retención.
3. v1.0.0 exige restauración de backups PostgreSQL, evidencia y anclajes en un entorno aislado. Migraciones se ensayan con upgrade e intervención revertible. Hacer rollback de despliegue con versión compatible de esquema y respaldo previo.


## Ejecutar la migración inicial

Desde el repositorio, instala las dependencias de PostgreSQL con `uv sync --locked --extra postgres`. En una base PostgreSQL dedicada, prepara un usuario de migraciones con permisos para crear el esquema y la tabla de versiones de Alembic en `public`. Como administrador de la base, crea el rol de grupo y otórgalo a un login de ejecución independiente.

```sql
CREATE ROLE pentest_agent_runtime NOLOGIN NOSUPERUSER NOBYPASSRLS;
GRANT pentest_agent_runtime TO pentest_app;
```

El login `pentest_app` debe existir, carecer de privilegios administrativos y de otros roles con acceso al esquema, y no ser propietario de sus tablas. Define `PENTEST_AGENT_MIGRATION_URL` con el DSN `postgresql+psycopg://` del usuario de migraciones y ejecuta `uv run --no-sync alembic upgrade head`.

La migración crea el esquema `pentest_agent`. El login de ejecución usa `tenant_transaction` para establecer organización, identidad y proyecto durante la transacción. Es responsabilidad del backend derivar esos datos de una sesión autenticada antes de abrir la transacción. La migración inicial concede escritura sobre objetivos dentro del proyecto visible. La gestión de identidades, membresías y revisiones de autorización requiere los servicios de las tareas siguientes. [Políticas de filas en PostgreSQL](https://www.postgresql.org/docs/17/ddl-rowsecurity.html)

Para ejecutar la integración, define `PENTEST_AGENT_TEST_POSTGRES_ADMIN_URL` con credenciales de administrador para una instancia desechable y vacía. La prueba crea roles y datos de prueba, aplica la migración, revierte a `base` y vuelve a aplicar `head`. Ejecuta `uv run --no-sync python -m pytest integration`.
