# BLANDSKRON Pentest Agent

CLI para preparar auditorías autorizadas y analizar respuestas HTTP guardadas. La ejecución activa está deshabilitada en esta etapa. El laboratorio integrado, el frontend y Docker Compose se detallan en el [plan de implementación](docs/planning/README.md).

## Instalación

Se requiere Python 3.10 o posterior.

```bash
git clone https://github.com/Blandskron/pentest-agent.git
cd pentest-agent
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

En PowerShell, activa el entorno con `.\.venv\Scripts\Activate.ps1` antes de instalar las dependencias.

## Planificación y análisis local

```bash
python main.py audit plan --url https://scope.example/api/ --environment lab
python main.py audit plan --url https://scope.example:8443 --profile tcp-baseline
python main.py audit analyze --input respuesta.txt --check xss --marker test-marker
python main.py audit analyze --input respuesta.txt --check sqli
```

`audit plan` valida la estructura del destino y muestra el perfil, el presupuesto configurado y el estado de ejecución. El plan local indica `missing_authorization` y `disabled`. La CLI actual solo genera una vista previa, sin consultar DNS ni servicios. El laboratorio integrado se habilitará en v0.5.0.

`audit analyze` recibe un cuerpo HTTP guardado en UTF-8 de hasta 256 KiB. Reporta indicadores que requieren corroboración. Los comandos de planificación y análisis funcionan sin una clave Groq.

Si conservas un `config/config.yaml` anterior, elimina `xss_payloads` y `sqli_payloads`. Los parámetros de límites se configuran en `execution`. El comando heredado `audit run` informa que la ejecución activa está cerrada.

## Informes guardados

`report generate` sigue procesando el JSON de auditorías anteriores. Envía los hallazgos a Groq para redactar el informe. Úsalo con datos autorizados para ese proveedor. Configura `GROQ_API_KEY` en el entorno o en `config/.env` y ejecuta:

```bash
python main.py report generate --input ruta/al/resultado.json
```

El modelo se configura en la sección `llm` de `config/config.yaml`. `GROQ_MODEL` permite elegir un modelo desde el entorno.

## Licencia

MIT © 2025 Bastián Landskron
