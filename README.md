# Pentest Agent

**Pentest Agent** es una herramienta profesional de auditoría web automatizada que combina técnicas clásicas de pentesting con la generación de reportes redactados automáticamente por **GPT-4**, proporcionando resultados claros, ejecutivos y accionables.


## Características

- ✅ Escaneo automatizado de puertos abiertos
- ✅ Fingerprinting e información pasiva
- ✅ Testeo de vulnerabilidades XSS y SQL Injection
- ✅ Resultados persistentes en base de datos
- ✅ Generación de reportes en lenguaje natural usando GPT-4
- ✅ Exportación en HTML o PDF (próximamente solo HTML para evitar problemas de codificación)
- ✅ Estructura de carpetas profesional (`core`, `domain`, `infra`, `application`, `cli`, `reports`, etc.)

## Requisitos

- Python 3.10+
- OpenAI API Key (almacenada como variable de entorno `OPENAI_API_KEY`)
- Recomendado: entorno virtual (`venv`)

## Instalación

```bash
# Clona el repositorio
git clone https://github.com/tuusuario/pentest-agent.git
cd pentest-agent

# Crea entorno virtual y activa
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

# Instala dependencias
pip install -r requirements.txt
```


## Ejecución

```bash
# 1. Ejecutar auditoría web
python main.py audit run -u https://blandskron.com

# Esto genera un archivo JSON en:
# results/blandskron.com/blandskron.com.json

# 2. Generar reporte HTML profesional
python main.py report generate -i results/blandskron.com/blandskron.com.json
```

## Estructura del Proyecto

```
pentest-agent/
│
├── main.py               # Entry point CLI
├── requirements.txt
│
├── cli/                  # Comandos Typer: audit, report
├── core/                 # Lógica de fingerprinting, escaneo, pruebas XSS/SQLi
├── domain/               # Modelos de dominio (e.g. Finding)
├── application/          # Servicios de alto nivel como audit_website()
├── infra/                # Base de datos, repositorios
├── gpt/                  # Cliente GPT y prompts
├── reports/              # Generador HTML (antes PDF)
│
└── results/              # Salida de auditorías (JSON + HTML)
    └── blandskron.com/
        ├── blandskron.com.json
        └── blandskron.com.html
```

## GPT y Seguridad

Todos los hallazgos son interpretados y redactados usando el modelo `gpt-4`, contextualizando los resultados de la auditoría y generando recomendaciones con lenguaje natural profesional.

## Notas

* La salida en PDF fue reemplazada por HTML debido a problemas de codificación (ej. Unicode y símbolos).
* Próximamente: soporte para múltiples idiomas y generación de dashboard web.
* Los datos son almacenados localmente. No se realiza explotación ni vulneración real de los sistemas analizados.

## Licencia

MIT © 2025 - Bastián Landskron
