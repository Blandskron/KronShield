# BLANDSKRON Pentest Agent

Piloto offline para gestionar autorizaciones, revisar alcance y analizar respuestas HTTP guardadas. La API, la web y la CLI comparten las simulaciones guardadas y sus informes. La ejecución activa está deshabilitada.

- [Estado y tareas del proyecto](docs/STATUS.md)
- [Desarrollo y pruebas](docs/DEVELOPMENT.md)
- [Operación, copias y restauración](docs/OPERATIONS.md)
- [Arquitectura y planificación](docs/planning/README.md)

## Piloto en Docker Compose

```bash
docker compose up --build -d --wait
docker compose exec -T api cat /run/pilot/bootstrap
```

Abre [http://localhost:8080](http://localhost:8080/) y selecciona **Primer acceso**. Usa el código de un solo uso para crear el administrador de plataforma. En **Gestión**, crea las cuentas locales y asigna una cuenta distinta como administradora de cada organización. Con esa cuenta, registra un cliente y un proyecto. Asigna por separado los roles de operador y aprobador mediante las membresías de organización y proyecto.

El operador registra el activo, la evaluación y el mandato. El aprobador revisa la autorización. El planificador muestra el resultado de la simulación y sus motivos. Solo el gateway tiene puerto de host. PostgreSQL, Redis y el almacén de objetos tienen volúmenes persistentes. Los documentos de autorización se cifran y guardan en PostgreSQL. Conserva también el volumen de secretos al respaldar o recuperar la base. `docker compose down` conserva esos volúmenes. [Servicios de Docker Compose](https://docs.docker.com/reference/compose-file/services/)

```bash
docker compose run --rm cli status
docker compose run --rm cli auth login --username operador
docker compose run --rm cli project organizations
docker compose run --rm cli project list --org-id UUID_ORG
docker compose run --rm cli lab seed --org-id UUID_ORG --project-id UUID_PROYECTO
docker compose run --rm cli target list --org-id UUID_ORG --project-id UUID_PROYECTO
docker compose run --rm cli assessment list --org-id UUID_ORG --project-id UUID_PROYECTO
docker compose run --rm cli authorization list --org-id UUID_ORG --project-id UUID_PROYECTO
docker compose run --rm cli plan create --org-id UUID_ORG --project-id UUID_PROYECTO --assessment-id UUID_EVALUACION --authorization-id UUID_AUTORIZACION --revision 1 --target-id UUID_ACTIVO
docker compose run --rm cli auth logout
```

`plan create` y `plan show` devuelven JSON con `browser_url` para abrir el plan con una sesión web del mismo proyecto. Cada plan guardado ofrece un informe HTML descargable desde la web. También puedes exportarlo desde la CLI con `docker compose run --rm -T cli plan report --org-id UUID_ORG --project-id UUID_PROYECTO --plan-id UUID_PLAN > revision.html`. El informe conserva el hash y el resultado de la simulación registrada.

La CLI del piloto guarda una credencial revocable de una hora en un volumen dedicado. Para una API OIDC, define `PENTEST_AGENT_API_URL` con el origen HTTPS y proporciona un access token vigente mediante `PENTEST_AGENT_API_TOKEN`.

## Instalación

Se requiere Python 3.10 o posterior y [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/Blandskron/pentest-agent.git
cd pentest-agent
uv sync --locked --no-editable --no-dev
uv run --no-sync pentest-agent --help
```

Para usar `pentest-agent` desde otra carpeta, activa el entorno con `source .venv/bin/activate` en Bash o `.\.venv\Scripts\Activate.ps1` en PowerShell. Los ejemplos con `python main.py` siguen funcionando desde el repositorio.

Para elegir un archivo de configuración desde cualquier carpeta, define `PENTEST_AGENT_CONFIG` con su ruta absoluta. Sin esa variable, la CLI busca `config/config.yaml` en el directorio de trabajo y después usa `%APPDATA%/pentest-agent/config.yaml` en Windows o `$XDG_CONFIG_HOME/pentest-agent/config.yaml` en Linux (`~/.config/pentest-agent/config.yaml` si no se define la variable). Si no hay archivo, aplica valores por defecto. El archivo `.env` opcional se lee desde el directorio de configuración seleccionado.

## Planificación y análisis local

```bash
python main.py audit plan --url https://scope.example/api/ --environment lab
python main.py audit plan --url https://scope.example:8443 --profile tcp-baseline
python main.py audit analyze --input respuesta.txt --baseline base.txt --check xss --marker test-marker --content-type text/html
python main.py audit analyze --input respuesta.txt --baseline base.txt --check sqli
python main.py audit analyze --response-missing --check sqli
```

`audit plan` valida la estructura del destino y muestra el perfil, el presupuesto configurado y el estado de ejecución. El plan local indica `missing_authorization` y `disabled`. La vista previa funciona sin consultar DNS ni servicios. Para una revisión persistida con una autorización de proyecto, usa el planificador web o `plan create`.

`audit analyze` recibe capturas UTF-8 de hasta 256 KiB cada una. Usa una respuesta base comparable del mismo endpoint. Un reflejo escapado o una firma de base de datos que ya aparece en esa respuesta se registra como observación de confianza baja. Una señal nueva en el contexto adecuado puede quedar como sospecha de confianza media. Si falta la respuesta de prueba, `--response-missing` registra un resultado inconcluso. El análisis de XSS usa el tipo de contenido capturado y conserva el contexto estático del HTML. La confirmación se reserva para una validación posterior. Los comandos de planificación y análisis funcionan sin una clave Groq.

Si conservas un `config/config.yaml` anterior, elimina `xss_payloads` y `sqli_payloads`. Los parámetros de límites se configuran en `execution`. El comando heredado `audit run` informa que la ejecución activa está cerrada.

## Resultados guardados

`python main.py audit save --input captura.json` valida un JSON de auditoría, publica una copia con un ID propio en `results` y confirma sus hallazgos en SQLite. `--database ruta/base.db` selecciona la base local. La URL del objetivo y la URL observada de cada hallazgo se guardan por separado.

Si SQLite falla, el comando devuelve código 5 e indica la copia JSON conservada con estado `json_only`. Reintenta usando ese archivo como entrada para conservar el ID y evitar duplicados en la base. Una nueva entrada sin ID genera un resultado independiente. El comando admite bases heredadas mediante tablas adicionales.

## Informes guardados

`report generate` procesa el JSON de auditorías anteriores y crea un HTML local sin credenciales. Admite hasta 1 MiB de entrada y 1.000 hallazgos. Cada ejecución publica un archivo `results/report-<id>.html` con nombre propio. El directorio `results` debe ser local al directorio de trabajo y estar en un sistema de archivos que admita enlaces duros.

```bash
python main.py report generate --input ruta/al/resultado.json
```

Con `--with-ai`, la CLI envía el tipo y detalle de los hallazgos a Groq para añadir un resumen. Revisa si esos campos contienen datos sensibles y configura `GROQ_API_KEY` en el entorno o en el archivo `.env` del directorio de configuración. El modelo se configura en la sección `llm` o mediante `GROQ_MODEL`.

## Esquema PostgreSQL

El backend usa migraciones Alembic para identidad, aislamiento, inventario, autorizaciones, simulación, importación y cuentas del piloto. Consulta la [preparación de PostgreSQL](docs/planning/DATABASE_DESIGN.md#ejecutar-la-migración-inicial). `audit save` usa SQLite local.

## API de autenticación

La API ofrece inicio de sesión web OIDC y un contexto de acceso para clientes CLI. Consulta la [configuración del proveedor y los permisos de proyecto](docs/planning/API_SPEC.md#configurar-la-autenticación-de-task-012).

La API también gestiona inventario y autorizaciones revisadas, con almacenamiento cifrado de documentos. Consulta las [rutas, permisos y requisitos de configuración](docs/planning/API_SPEC.md#inventario-y-autorizaciones-de-task-013).

## Resultados históricos

Valida un JSON o SQLite local antes de importarlo:

```bash
pentest-agent audit import-legacy --input copia.db --format sqlite --org-id UUID_ORG --project-id UUID_PROYECTO --dry-run
```

Para guardar el lote en PostgreSQL, configura `PENTEST_AGENT_API_TOKEN`, usa `--api-url https://tu-api.example` y retira `--dry-run`. Para SQLite, usa un respaldo consistente en modo de rollback journal sin archivos `-wal` o `-journal` activos. La importación conserva el tipo, el detalle, las URL disponibles y la procedencia. Omite el payload y los campos libres de evidencia. El SHA-256 de los bytes identifica el lote dentro del proyecto.

## Contrato y aplicación web

El contrato OpenAPI v1 está en [contracts/openapi-v1.json](contracts/openapi-v1.json). Con la API iniciada, consulta `/api/v1/docs`, `/api/v1/health` y `/api/v1/ready`. El último comprueba la conexión y la revisión de Alembic.

```bash
cd frontend
npm ci
npm run build
```

Define `PENTEST_AGENT_WEB_DIST` con la ruta absoluta a `frontend/dist` antes de iniciar la API. Sirve la aplicación desde el mismo origen HTTPS configurado para OIDC. Para probar el shell con datos simulados, desde `frontend` ejecuta `npx playwright install chromium` y `npm test`.

## Licencia

MIT © 2025 Bastián Landskron
