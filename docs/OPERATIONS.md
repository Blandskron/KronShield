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

docker compose -p $Target up -d --wait
docker compose -p $Target run --rm --no-deps cli status
```

Inicia una sesión nueva en `http://localhost:18085`. Comprueba el hash de un plan de referencia, descarga su informe y compara sus bytes con la copia de origen. Como usuario autorizado, descarga un PDF de referencia y verifica su SHA-256. La limpieza de las tablas de sesión en el destino requiere volver a autenticar los clientes. Los datos y sesiones de la instancia de origen se conservan.

En el ensayo del 23 de noviembre de 2026, el destino conservó el hash del plan y los bytes del informe y del PDF. El token anterior fue rechazado en el destino y siguió siendo válido en el origen. El ensayo cubre el estado PostgreSQL usado por el piloto y la clave que descifra los mandatos. Inventaría por separado los volúmenes de Redis y objetos si tu instalación almacena allí datos adicionales, así como los archivos JSON y SQLite de la CLI local. Registra la duración observada de copia y restauración para definir objetivos medibles.
