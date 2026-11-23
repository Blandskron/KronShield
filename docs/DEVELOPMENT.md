# Desarrollo y validación

El repositorio contiene una CLI Typer, una API FastAPI, migraciones Alembic y un frontend React con Vite. El [estado del proyecto](STATUS.md) enumera los flujos disponibles.

## Entorno local

Desde la raíz del repositorio, instala Python 3.10 o posterior, uv, Node.js 24 y Docker Compose para las pruebas con servicios. CI prueba Python 3.10 y 3.14 en Ubuntu y Windows.

```bash
uv sync --locked --no-editable --extra api --extra postgres
uv run --no-sync python -m pytest
uv run --no-sync python -m flake8 adapters application cli core domain gpt infra migrations reports tests integration contracts deploy --select=E9,F63,F7,F82
npm --prefix frontend ci
npm --prefix frontend run build
```

La suite Python normal bloquea DNS y conexiones de red en el proceso de pruebas. El caso de enlaces simbólicos puede omitirse en Windows según los permisos de la cuenta. Los tests de PostgreSQL usan una base vacía y desechable. El fixture crea roles y aplica, revierte y reaplica las migraciones. Configura `PENTEST_AGENT_TEST_POSTGRES_ADMIN_URL` con un DSN `postgresql+psycopg://` de administrador de esa instancia y ejecuta `uv run --no-sync python -m pytest integration`.

## Contrato de API

La fuente del contrato es la aplicación y sus modelos de entrada y salida. Si cambias una ruta o un esquema público, revisa el impacto en clientes y vuelve a generar los artefactos.

```bash
uv run --no-sync python -m contracts.export
npm --prefix frontend run contract
uv run --no-sync python -m contracts.export --check
```

Versiona juntos `contracts/openapi-v1.json` y `frontend/src/api.generated.ts`. CI comprueba que coincidan con el código y compara la compatibilidad del contrato en pull requests con una versión anterior del esquema. El [contrato publicado](../contracts/openapi-v1.json) es la referencia para rutas, parámetros y respuestas.

## Frontend y piloto

En `frontend`, `npm run dev` inicia Vite y usa el proxy de API local. El modo de desarrollo acepta `PENTEST_AGENT_API_PROXY` para cambiar el backend. Para probar el login real, usa el origen de loopback anunciado por Compose. Para OIDC, sirve frontend y API desde el mismo origen HTTPS configurado.

```bash
cd frontend
npx playwright install chromium
npm test -- shell.spec.ts
```

La prueba de extremo a extremo `pilot.spec.ts` necesita un proyecto Compose nuevo y verifica alta, permisos, aprobación separada, CLI, descarga y reinicio. Usa `PENTEST_AGENT_E2E_PROJECT` con el nombre del proyecto, `PENTEST_AGENT_E2E_ORIGIN` con su origen HTTP local y `PENTEST_AGENT_E2E_BOOTSTRAP` con el secreto de ese piloto de prueba. CI ejecuta el flujo en un proyecto desechable.

## Datos de desarrollo

`uv.lock` y `frontend/package-lock.json` fijan las dependencias de las instalaciones documentadas. Mantén capturas, bases locales, informes y claves fuera del repositorio y del contexto de Docker. Usa fixtures sintéticos en CI y en ensayos de recuperación. Consulta la [guía de operación](OPERATIONS.md) para respaldar los datos del piloto.
