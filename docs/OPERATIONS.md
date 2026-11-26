# Operación y recuperación del piloto

El piloto se ejecuta en loopback. Los comandos de esta guía se lanzan desde la raíz del repositorio. Trabaja con proyectos Compose explícitos cuando mantengas más de una instancia.

## Inicio y comprobaciones

```bash
docker compose up --build -d --wait
docker compose ps
docker compose run --rm --no-deps cli status
```

Usa `http://localhost:8080` o el puerto que fijaste en `PILOT_PORT`. Mantén el hostname `localhost` para que coincida con el origen de sesión. La primera configuración se explica en el [README](../README.md#piloto-en-docker-compose). Consulta `/api/v1/health` para verificar el proceso y `/api/v1/ready` para verificar la conexión con PostgreSQL y la revisión de Alembic.

| Síntoma | Comprobación y acción |
|---|---|
| `ready` devuelve 503 | Revisa `docker compose ps -a` y `docker compose logs migrate api`. Una migración fallida impide el arranque de la API. Un esquema anterior produce `schema_not_ready`. |
| El navegador devuelve `origin_denied` | Usa `localhost` con el puerto configurado y el origen desde el que se cargó la web. |
| Un proyecto devuelve 404 | Confirma la organización seleccionada, el UUID del proyecto y la membresía del usuario. |
| Una operación devuelve 403 | Comprueba el rol de proyecto y, para una sesión web, el token CSRF. |
| Falla la descarga de un mandato tras restaurar | Comprueba que la clave de documentos corresponda al respaldo y que el usuario tenga permisos de lectura. |

El gateway publica el puerto de host. La API, PostgreSQL, Redis y el almacén de objetos usan redes de Compose. Los datos del flujo offline y los PDF cifrados residen en PostgreSQL. Redis y el almacén de objetos tienen sus propios volúmenes. La CLI local también puede mantener resultados JSON y SQLite fuera de Compose.

## Copia de PostgreSQL y clave de documentos

Usa un directorio protegido y fuera del repositorio para el dump y otro para la clave. La clave debe conservarse separada de la copia de la base. El dump es consistente y conserva la información de acceso, los mandatos cifrados y el historial del piloto. [pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html)

Ejemplo en PowerShell. Ajusta el proyecto de origen y los dos directorios antes de ejecutarlo. Conserva las variables en la misma consola para el ensayo de restauración.

```powershell
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$Source = 'pentest-agent'
$Dump = Join-Path 'C:\Copias\Base' 'pentest.dump'
$Key = Join-Path 'C:\Copias\Claves' 'pentest-document-key.b64'
if ((Test-Path -LiteralPath $Dump) -or (Test-Path -LiteralPath $Key)) {
    throw 'Elige nombres de archivo nuevos'
}

docker compose -p $Source exec -T postgres pg_dump -U postgres -d pentest -Fc -f /tmp/pentest-backup.dump
try {
    docker compose -p $Source cp 'postgres:/tmp/pentest-backup.dump' $Dump
    docker compose -p $Source cp 'api:/run/pilot/document-key' $Key
    Get-FileHash -LiteralPath $Dump -Algorithm SHA256
} finally {
    docker compose -p $Source exec -T postgres rm -f /tmp/pentest-backup.dump
}
```

Registra el SHA-256, la fecha y la revisión del repositorio junto al inventario de respaldos. Protege ambos archivos con el almacenamiento de respaldo de tu instalación. `docker compose cp` transporta el archivo binario sin aplicar la codificación de la consola. [docker compose cp](https://docs.docker.com/reference/cli/docker/compose/cp/)

## Ensayo de restauración aislado

Parte de un proyecto Compose nuevo con otro puerto, PostgreSQL 17 y la misma revisión del repositorio con la que se creó el dump. Usa únicamente respaldos de una fuente bajo tu control y compara el SHA-256 del dump con el inventario antes de restaurar. El arranque inicial crea los roles de PostgreSQL. La restauración reconstruye los objetos a partir del dump y conserva esos nombres de rol. [pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html)

```powershell
$Target = 'pentest-restore'
if ($Target -eq $Source) { throw 'Usa un proyecto separado para la restauración' }
$env:PILOT_PORT = '18085'
docker compose -p $Target up --build -d --wait
$existing = docker compose -p $Target exec -T postgres psql -U postgres -d pentest -At -c 'SELECT (SELECT count(*) FROM pentest_agent.identity) + (SELECT count(*) FROM pentest_agent.organization) + (SELECT count(*) FROM pentest_agent.assessment_plan)'
if (($existing | Out-String).Trim() -ne '0') {
    throw 'El destino ya contiene datos del piloto. Elige un proyecto nuevo'
}

docker compose -p $Target stop gateway api
docker compose -p $Target cp $Dump 'postgres:/tmp/pentest-restore.dump'
try {
    docker compose -p $Target exec -T postgres pg_restore --list /tmp/pentest-restore.dump | Out-Null
    docker compose -p $Target exec -T postgres pg_restore -U postgres -d pentest --clean --if-exists --single-transaction --exit-on-error /tmp/pentest-restore.dump
    Get-Content -LiteralPath $Key -Raw |
        docker compose -p $Target run --rm --no-deps -T secrets python deploy/pilot.py restore-document-key
    docker compose -p $Target exec -T postgres psql -U postgres -d pentest -v ON_ERROR_STOP=1 -c 'TRUNCATE TABLE pentest_agent.login_attempt, pentest_agent.web_session, pentest_agent.pilot_token'
} finally {
    docker compose -p $Target exec -T postgres rm -f /tmp/pentest-restore.dump
}

# Para copias con evidencia offline, aplica la sección de retención antes de este arranque.
docker compose -p $Target up -d --wait
docker compose -p $Target run --rm --no-deps cli status
```

Inicia una sesión nueva en `http://localhost:18085`. Comprueba el hash de un plan de referencia, descarga su informe y compara sus bytes con la copia de origen. Como usuario autorizado, descarga un PDF de referencia y verifica su SHA-256. La limpieza de las tablas de sesión en el destino requiere volver a autenticar los clientes. Los datos y sesiones de la instancia de origen se conservan.

En el ensayo del 23 de noviembre de 2026, el destino conservó el hash del plan y los bytes del informe y del PDF. El token anterior fue rechazado en el destino y siguió siendo válido en el origen. El ensayo cubre el estado PostgreSQL usado por el piloto y la clave que descifra los mandatos. Inventaría por separado los volúmenes de Redis y objetos si tu instalación almacena allí datos adicionales, así como los archivos JSON y SQLite de la CLI local. Registra la duración observada de copia y restauración para definir objetivos medibles.

## Retención y retiro de evidencia offline

Desde la migración `0009_evidence_retention`, una fuente dura hasta el primero de tres límites. Se aplica el final del permiso de evidencia aprobado, el plazo `retain_until` aprobado para la fuente cuando exista y el máximo por clase desde el inicio del permiso. Los máximos del piloto son 30 días para `internal` y 7 días para `restricted`. Un aprobador distinto del solicitante puede retirar una fuente antes de esa fecha. El vencimiento y el retiro bloquean la lectura de su proyección inmediatamente.

La operación de mantenimiento registra los vencimientos y elimina las proyecciones cifradas vencidas o retiradas de la base activa. Ejecútala con el proyecto Compose explícito y conserva el conteo con el registro operativo.

```powershell
docker compose -p $Source run --rm --no-deps -T migrate python deploy/pilot.py sweep-evidence
```

Los respaldos existentes conservan los datos que contenían al crearse. Define con el responsable de los datos su fecha de eliminación, conserva la clave separada y custodia un archivo de retiros más reciente que la copia que vas a restaurar. Captura los retiros en el origen antes de restaurar, con un corte en el que no se acepten nuevas decisiones. Genera el CSV desde PostgreSQL mediante `COPY` y conserva sus bytes y SHA-256 en el inventario de recuperación.

```sql
COPY (
    SELECT org_id, project_id, permission_id, revision, source_digest, kind, actor_id, reason, recorded_at
    FROM pentest_agent.evidence_disposition
    WHERE kind = 'withdrawn'
    ORDER BY org_id, project_id, permission_id, revision, source_digest
) TO STDOUT WITH (FORMAT CSV, HEADER);
```

En el destino aislado, con API y gateway detenidos, verifica el hash del CSV y carga sus filas en una tabla temporal de la misma sesión de `psql`. Usa `\copy` desde una copia local del archivo en esa sesión. Aplica los retiros de fuentes que existan en el destino y ejecuta la limpieza antes de habilitar la lectura.

```sql
BEGIN;
CREATE TEMP TABLE withdrawals (LIKE pentest_agent.evidence_disposition) ON COMMIT DROP;
\copy withdrawals FROM 'withdrawals.csv' WITH (FORMAT CSV, HEADER)
INSERT INTO pentest_agent.evidence_disposition
SELECT w.*
FROM withdrawals AS w
JOIN pentest_agent.evidence_permission AS p
  ON (p.org_id, p.project_id, p.id, p.revision) =
     (w.org_id, w.project_id, w.permission_id, w.revision)
WHERE w.kind = 'withdrawn'
  AND p.spec->'sources' @> jsonb_build_array(jsonb_build_object('digest', w.source_digest))
ON CONFLICT DO NOTHING;
SELECT pentest_agent.sweep_evidence_retention();
COMMIT;
```

Comprueba que reaparezcan los recibos de retiro pertinentes y que reejecutar la limpieza devuelva cero proyecciones eliminadas. Los planes v1 y las importaciones históricas originales siguen su propia política de conservación.

## Interruptor por organización

El administrador de la organización consulta `GET /api/v1/organizations/{org_id}/stop`. Para cambiar el estado, usa `PUT` sobre la misma ruta con el `ETag` recibido en `If-Match` y un cuerpo JSON con `enabled` y `reason`. Si otra decisión se registró primero, la API devuelve `412`. Consulta el estado vigente antes de decidir de nuevo.

Al activarlo, la verificación de alcance bloquea los planes y la admisión de evidencia. Los usuarios con acceso pueden seguir leyendo los planes históricos. Cada transición confirmada registra la fecha, el actor, el motivo y una revisión independiente de la versión del inventario de la organización.

## Presupuesto de análisis offline

La fase C registra borradores internos con la revisión y el digest del plan, permiso, especialidad, fuentes y revisión del interruptor. El despachador usa el orden del manifiesto y un registro cerrado de funciones en memoria. El catálogo sigue pendiente de habilitación y las funciones de prueba operan sobre proyecciones sintéticas.

| Límite piloto | Especialidad | Rainbow |
|---|---:|---:|
| Pasos reservados | 1 | 9 en total |
| Entrada total | 1 MiB | 4 MiB |
| Tiempo desde la primera reserva | 30 s | 120 s |
| Solicitudes de inferencia | 1 | 6 en total |
| Tokens de entrada / salida | 12.000 / 3.000 | 12.000 / 3.000 en total |

El sistema admite una reserva vigente por análisis y dos por proyecto, incluso si pertenecen a operadores distintos. Cada reserva cuenta como un paso. Repetir la misma clave devuelve el recibo con `replayed=true`, que el despachador debe tratar como consulta. El recibo con medición conserva el uso observado. Si el uso es desconocido o vence la reserva, se contabiliza el máximo reservado. La conciliación registra el vencimiento de forma idempotente.

Para medir estos límites en el piloto, registra el SHA, la versión de PostgreSQL, el número de sesiones concurrentes, el uso reservado y conciliado, y los rechazos por presupuesto, plazo o concurrencia. Compara la secuencia de eventos con los recibos antes de ajustar valores. El ensayo de capacidad con un proveedor se define en F03.

El despachador comprueba el permiso y las fuentes al iniciar y al confirmar. La función recibe únicamente la proyección de su paso y se ejecuta fuera de la transacción. Una clave repetida consulta el recibo sin volver a invocar la función. La auditoría conserva el paso y el código de bloqueo o fallo. El flujo de revisión humana tendrá su propia autorización para consultar resultados.

## Importar eventos de Blue Team

La API de permisos de evidencia admite lotes JSON de eventos minimizados. En la solicitud usa `mode_id: "blue"` con la versión y el digest del catálogo. Declara la fuente con `kind: "event-batch-v1"`, `capability: "event-review"`, el UUID del activo, la clasificación, el SHA-256 y el tamaño exacto del archivo. Usa un activo propio permitido por el plan. Una vez aprobado el permiso, carga el archivo con `PUT /api/v1/projects/{project_id}/evidence-permissions/{permission_id}/revisions/{revision}/sources/{digest}`, `org_id` como parámetro de consulta y `Content-Type: application/json`.

```json
{
  "target_id": "11111111-1111-4111-8111-111111111111",
  "producer": "identity-audit",
  "window_start": "2026-11-26T09:00:00-03:00",
  "window_end": "2026-11-26T10:00:00-03:00",
  "events": [
    {
      "event_id": "22222222-2222-4222-8222-222222222222",
      "occurred_at": "2026-11-26T09:15:00-03:00",
      "kind": "login-failure"
    }
  ]
}
```

El lote admite hasta 1 MiB y 2.000 eventos con UUID distintos. Los tipos admitidos son `login-success`, `login-failure`, `privilege-change` y `configuration-change`. El productor se identifica con hasta 64 caracteres en minúsculas, dígitos y guiones, empezando por una letra. El identificador es declarado por quien exporta el lote. Las fechas requieren zona horaria y cada evento debe caer desde el inicio inclusive hasta el fin exclusivo de la ventana. La ventana describe el período observado y el permiso controla cuándo puede usarse la evidencia.

La carga devuelve el digest del archivo original y el de la proyección cifrada. La proyección conserva el productor, normaliza las fechas a UTC y ordena por instante y UUID.

### Ejecutar y revisar el triaje

Selecciona Blue Team en el proyecto y abre un plan revisado. Desde el planificador, solicita permiso para el lote, comparte el enlace con el aprobador y carga el mismo archivo una vez aprobado. Crea el análisis, avanza **Triaje de eventos** y comparte el enlace con el aprobador para revisar y publicar la conclusión.

La regla disponible es `identity-login-failure-v1`. Examina lotes del productor declarado `identity-audit` y cuenta eventos de tipo `login-failure`, deduplicados por activo y UUID. La API de creación acepta `event_rule` con ese identificador. En Blue Team, si se omite, se aplica la misma regla. El paso usa la estrategia `deterministic`.

- **Observado** si al menos un evento coincide.
- **No observado** si hay un lote del productor requerido y ningún evento coincide. Un lote explícito con `events: []` cuenta como una ventana evaluada.
- **Sin datos de la fuente requerida** si falta un lote del productor requerido.

La conclusión y el informe publicable incluyen el identificador de la regla, los lotes evaluados, el número de coincidencias y los SHA-256 de las fuentes evaluadas. El resultado se limita a las ventanas aportadas. El permiso y las fuentes deben seguir vigentes para revisar y descargar el informe.

## API de análisis offline

Las rutas de ciclo de vida bajo `/api/v1/projects/{project_id}/analyses` requieren `org_id`, autenticación y el permiso `evidence:request`. El resumen del análisis es visible para su autor mientras conserve la membresía de operador. La creación congela la selección de especialidad y su versión. Las respuestas exponen el estado, el hash del plan y los recibos de avance. El aprobador autorizado accede a las conclusiones desde las rutas de revisión.

En el planificador, configura White Team en el proyecto y abre un plan revisado. Un operador puede solicitar permiso para un archivo JSON de observaciones de un activo propio dentro del alcance. Comparte el enlace del permiso con el aprobador, espera su decisión y vuelve a cargar exactamente el archivo registrado. Crea el análisis y avanza el siguiente paso. El modo determinista es el predeterminado y la inferencia local se ofrece con un permiso que la autorice.

Comparte el enlace del análisis cuando aparezca **En espera de revisión**. El aprobador del permiso registra una decisión por conclusión y publica el informe desde el mismo planificador. Quien tenga acceso vigente a todas las fuentes puede descargarlo. Los enlaces permiten retomar el recorrido al recargar o volver a iniciar sesión. También puedes localizar un permiso o análisis por UUID en el planificador.

| Método y recurso relativo | Comportamiento |
|---|---|
| `POST /` | Crea el borrador con la revisión aprobada del permiso de evidencia, la versión de selección y los digests autorizados. Requiere `Idempotency-Key`. |
| `POST /{analysis_id}/steps/{step_id}` | Avanza únicamente el siguiente paso del manifiesto. Requiere `Idempotency-Key`. El cuerpo admite `strategy` con valor `deterministic` por defecto o `assisted`. Una repetición devuelve el recibo vigente del mismo paso y estrategia. |
| `GET /{analysis_id}` | Consulta el resumen, el siguiente paso y el estado de publicación cuando el autor conserva acceso al informe. Si la reserva venció, registra el consumo reservado y el fallo una sola vez. |
| `PUT /{analysis_id}/cancellation` | Cancela el análisis. Las repeticiones conservan la fecha original. Si hay un paso en curso, su resultado se descarta y se registra la reserva sin medir. |

La capacidad disponible en C06 verifica registros de alcance. En modo asistido resulta aplicable el permiso adicional de inferencia local. El resultado del proveedor es una propuesta privada. Si el entorno se configuró para inferencia y el proveedor falla, se conserva el resultado determinista autorizado y se muestra `proposal_error`. Si el perfil está desactivado, solicitar `assisted` devuelve `503 proposal_dependency_missing` sin reservar el paso.

Para habilitar la asistencia en el piloto, prepara los pesos como se indica en el ensayo de inferencia local y carga la superposición. Usa el mismo nombre de proyecto Compose de tu piloto con `-p` para reutilizar sus volúmenes. Este comando conecta la API y el servidor de inferencia a una red interna dedicada.

```sh
docker compose -p pentest-agent -f compose.yaml -f compose.inference.yaml -f compose.inference-api.yaml --profile local-inference up -d --build gateway inference
```

## Revisión y publicación de análisis

Las rutas de revisión usan el mismo proyecto y `org_id` que las de análisis. El aprobador requiere `analyses:publish`, debe haber aprobado el permiso de evidencia y debe ser distinto del autor. Las conclusiones están disponibles al completar el flujo. Cada decisión conserva la identidad, el motivo y la fecha registrados por el servidor.

| Método y recurso relativo a `/{analysis_id}` | Comportamiento |
|---|---|
| `GET /review` | Devuelve conclusiones con citas autorizadas, decisiones registradas y el recibo de publicación si existe. |
| `PUT /review/decisions/{conclusion_id}` | Registra `approve` o `reject` y el motivo. Una repetición idéntica devuelve la decisión original. Un cambio posterior recibe un conflicto. |
| `PUT /publication` | Requiere una decisión para cada conclusión. Guarda la instantánea de las conclusiones aprobadas, la procedencia y los bytes del HTML con su SHA-256. Una repetición devuelve el mismo recibo mientras siga vigente el permiso. |
| `GET /publication/report` | Descarga el HTML para el autor o el aprobador con acceso vigente a todas las fuentes congeladas. La cabecera `ETag` contiene el SHA-256. |

Una fuente retirada, vencida o ajena al permiso bloquea el acceso al artefacto completo. Las decisiones rechazadas quedan en el registro de revisión y el informe solo incluye su recuento. Los motivos y las referencias aparecen como texto escapado. El HTML se almacena al publicar para que sus bytes se mantengan estables tras reiniciar o actualizar la plantilla.

## Ensayo de inferencia local

`compose.inference.yaml` permite ensayar la inferencia de forma independiente. El adaptador se conecta a `http://inference:8080` en una red interna sin puertos publicados. El servidor se ejecuta como UID 10001, con el sistema de archivos y los pesos montados como solo lectura. Para conectar el servicio a la API del piloto se añade `compose.inference-api.yaml`. El despacho determinista sigue siendo el predeterminado.

El servidor fijado es llama.cpp `1.0.0-dev`, build `12723`, revisión `abca69200` y licencia MIT. El digest de la imagen CPU está en Compose. El modelo es Qwen2.5-1.5B-Instruct GGUF Q4_K_M, con licencia Apache-2.0 y pesos de 1,12 GB. El contenedor comprueba su SHA-256 antes de iniciar. [Código del servidor](https://github.com/ggml-org/llama.cpp/tree/abca6920035ed77c1d80eaf23d066e9d3a7c5b23) · [Pesos y licencia del modelo](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/blob/dd26da440ef0330c47919d1ecae0966d24022222/qwen2.5-1.5b-instruct-q4_k_m.gguf)

Para reproducir el ensayo, guarda el archivo `qwen2.5-1.5b-instruct-q4_k_m.gguf` en el directorio indicado por `KRONSHIELD_MODEL_DIR` (por defecto, `./models`). El SHA-256 esperado es `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e`. Con Docker y Compose disponibles, ejecuta desde la raíz del repositorio:

```sh
docker compose -f compose.inference.yaml --profile local-inference build inference-smoke
docker compose -f compose.inference.yaml --profile local-inference up -d --wait --wait-timeout 120 inference
docker compose -f compose.inference.yaml --profile local-inference run --rm inference-smoke
docker compose -f compose.inference.yaml --profile local-inference down
```

El ensayo usa únicamente una observación sintética y su digest. Las instrucciones van separadas del contexto. El cliente tokeniza antes de generar, aplica un plazo total de 12 s y valida la propuesta con C04. Con un directorio vacío, el servicio registra `proposal_dependency_missing` y termina. En ese caso, el cliente de ensayo puede comprobar el mismo estado con `run --rm inference-smoke python -m deploy.inference_smoke --missing`.

El 25 de noviembre de 2026, Docker Desktop 4.99.0 ejecutó el ensayo en un Intel Core i7-1165G7, con 8 CPU lógicas y 15,5 GiB de RAM visibles en Linux. El perfil usó 4 hilos, un límite de 2 GiB, una única secuencia y 2.048 tokens de contexto. Las tres peticiones produjeron el mismo borrador admitido, con 213 tokens de entrada, 100 de salida y tiempos entre 6,46 y 6,91 s. Docker midió 775 MiB de memoria del contenedor después de la primera petición. La inspección confirmó el montaje de solo lectura, la red interna, la ausencia de ruta IPv4 por defecto y la ausencia de puertos publicados. Una conexión al servicio interno tuvo éxito y una conexión HTTPS a una IP externa devolvió `ENETUNREACH`.
