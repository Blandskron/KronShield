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

`report generate` procesa el JSON de auditorías anteriores y crea un HTML local sin credenciales. Admite hasta 1 MiB de entrada y 1.000 hallazgos. Cada ejecución publica un archivo `results/report-<id>.html` con nombre propio. El directorio `results` debe ser local al directorio de trabajo y estar en un sistema de archivos que admita enlaces duros.

```bash
python main.py report generate --input ruta/al/resultado.json
```

Con `--with-ai`, la CLI envía el tipo y detalle de los hallazgos a Groq para añadir un resumen. Revisa si esos campos contienen datos sensibles y configura `GROQ_API_KEY` en el entorno o en `config/.env`. El modelo se configura en la sección `llm` o mediante `GROQ_MODEL`.

## Licencia

MIT © 2025 Bastián Landskron
