from openai import OpenAI
import httpx
import json

client = None

def init(token: str):
    # Crear un cliente HTTPX sin proxies
    transport = httpx.HTTPTransport(proxy=None)
    http_client = httpx.Client(transport=transport)

    global client
    client = OpenAI(api_key=token, http_client=http_client)

def generate_summary(data: dict) -> str:
    prompt = build_prompt(data)

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Eres un experto en ciberseguridad y redactor de informes técnicos."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )

    return response.choices[0].message.content.strip()

def build_prompt(data: dict) -> str:
    json_content = json.dumps(data, indent=2)
    return f"""
A partir del siguiente JSON que representa el resultado de una auditoría web, redacta un informe técnico profesional con:

- Un resumen ejecutivo claro
- Diagnóstico técnico por secciones (cabeceras, puertos, vulnerabilidades)
- Riesgos y recomendaciones

FORMATO: Solo texto, sin markdown ni HTML.

--- JSON DE ENTRADA ---
{json_content}
"""
