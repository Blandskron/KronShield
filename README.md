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
python main.py audit analyze --input respuesta.txt --baseline base.txt --check xss --marker test-marker --content-type text/html
python main.py audit analyze --input respuesta.txt --baseline base.txt --check sqli
python main.py audit analyze --response-missing --check sqli
```

`audit plan` valida la estructura del destino y muestra el perfil, el presupuesto configurado y el estado de ejecución. El plan local indica `missing_authorization` y `disabled`. La CLI actual solo genera una vista previa, sin consultar DNS ni servicios. El laboratorio integrado se habilitará en v0.5.0.

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

Con `--with-ai`, la CLI envía el tipo y detalle de los hallazgos a Groq para añadir un resumen. Revisa si esos campos contienen datos sensibles y configura `GROQ_API_KEY` en el entorno o en `config/.env`. El modelo se configura en la sección `llm` o mediante `GROQ_MODEL`.

## Licencia

MIT © 2025 Bastián Landskron
