# Pentest Agent

**Pentest Agent** es una herramienta de auditoría web automatizada que combina técnicas
clásicas de pentesting con la redacción automática de informes mediante un modelo LLM
servido por **Groq** (`openai/gpt-oss-120b`), entregando resultados claros, ejecutivos y accionables.

> Uso exclusivo para auditorías **autorizadas** sobre sistemas propios o con consentimiento explícito.

## Características

- Escaneo de puertos abiertos comunes (80/443/8080/8443, configurable)
- Reconocimiento pasivo: status HTTP, fingerprint de servidor y cabeceras de seguridad ausentes
- Testeo de XSS reflejado y SQL Injection con payloads generados por LLM (con fallback estático)
- Persistencia de hallazgos en base de datos SQLite
- Generación de informes en lenguaje natural con Groq / `openai/gpt-oss-120b`
- Exportación de informes en HTML
- Arquitectura por capas (`core`, `domain`, `infra`, `application`, `cli`, `gpt`, `reports`)

## Requisitos

- Python 3.10+
- API Key de Groq (https://console.groq.com/keys), almacenada como `GROQ_API_KEY`
- Recomendado: entorno virtual (`venv`)

## Instalación

```bash
git clone https://github.com/tuusuario/pentest-agent.git
cd pentest-agent

python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

pip install -r requirements.txt
```

## Configuración

Crea el archivo `config/.env` (ya está en `.gitignore`, no se versiona):

```bash
GROQ_API_KEY=tu_api_key_de_groq
GROQ_MODEL=openai/gpt-oss-120b   # opcional, sobreescribe config.yaml
```

Los parámetros del modelo y del escaneo se ajustan en `config/config.yaml`
(sección `llm`: `model`, `temperature`, `top_p`, `max_completion_tokens`, `reasoning_effort`).

Inicializa la base de datos una vez:

```bash
python migrate.py
```

## Ejecución

```bash
# 1. Ejecutar auditoría web
python main.py audit run -u https://nxtara.com

# Genera: results/nxtara.com/nxtara.com.json  y guarda hallazgos en pentest.db

# 2. Generar informe HTML profesional
python main.py report generate -i results/nxtara.com/nxtara.com.json
# Genera: results/nxtara.com/nxtara.com.html
```

## Estructura del Proyecto

```
pentest-agent/
├── main.py               # Entry point CLI (Typer)
├── migrate.py            # Crea el esquema de la base de datos
├── requirements.txt
├── config/
│   ├── config.yaml       # Parámetros de escaneo y del LLM (Groq)
│   └── .env              # GROQ_API_KEY (no versionado)
├── cli/                  # Comandos Typer: audit, report
├── core/                 # recon, scanner, xss, sqli, settings
├── domain/               # Modelos de dominio (Finding)
├── application/          # audit_website() (orquestación)
├── infra/                # Base de datos y repositorio (SQLAlchemy)
├── gpt/                  # Cliente Groq, prompts y summarize
├── reports/              # Generador de informe HTML
└── results/              # Salida de auditorías (JSON + HTML)
```

## LLM y Seguridad

Los hallazgos se interpretan y redactan con el modelo `openai/gpt-oss-120b` a través de
la API de Groq (compatible con OpenAI). La API key se lee desde `config/.env` y nunca
se sube al repositorio.

## Licencia

MIT © 2025 - Bastián Landskron
