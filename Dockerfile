FROM node:24-bookworm-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54 AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts frontend/playwright.config.ts ./
COPY frontend/src/ ./src/
COPY frontend/tests/ ./tests/
RUN npm run build

FROM nginxinc/nginx-unprivileged:alpine@sha256:b5047b9b76845eac124358373c6852377c52e4b05834a47647e955dd91cb8f1e AS gateway
COPY deploy/gateway.conf /etc/nginx/conf.d/default.conf
COPY --from=web /web/dist/ /usr/share/nginx/html/

FROM python:3.10-slim@sha256:6ff506466f8b1e981719b468cc0023b8ef000b983cdec0eafe119d01f379e31d AS python
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PATH="/app/.venv/bin:$PATH" UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir uv==0.12.8
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-editable --no-install-project --extra api --extra postgres
COPY adapters/ adapters/
COPY application/ application/
COPY cli/ cli/
COPY core/ core/
COPY domain/ domain/
COPY gpt/ gpt/
COPY infra/ infra/
COPY reports/ reports/
COPY migrations/ migrations/
COPY deploy/pilot.py deploy/pilot.py
COPY alembic.ini ./
RUN uv sync --locked --no-dev --no-editable --extra api --extra postgres \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home app
USER 10001:10001
