# Pentest Agent

Auditoría profesional automatizada con GPT-4.

## Uso

```bash
# 1. Instalar
pip install -r requirements.txt

# 2. Ejecutar auditoría
python main.py audit run -u https://blandskron.com -t $OPENAI_API_KEY
python main.py audit run -u https://blandskron.com -t $OPENAI_API_KEY

# 3. Generar reporte PDF
python main.py report generate -i output.json -t $OPENAI_API_KEY
```
