def xss_prompt(url: str):
    return f"""
Genera 10 payloads modernos y difíciles de detectar de Cross Site Scripting (XSS) para atacar parámetros GET en la URL:
{url}
Cada payload debe estar en una línea diferente sin explicaciones.
"""

def sqli_prompt(url: str):
    return f"""
Genera 10 payloads efectivos de SQL Injection para URLs con parámetros 'user' y 'pass'.
Incluye UNION, comentarios, combinaciones de bypass, y técnicas modernas.
Aplica sobre esta URL: {url}
Formato: uno por línea, sin texto adicional.
"""

def summary_prompt(data: dict):
    url = data.get("url", "URL no especificada")
    findings = data.get("findings", [])

    formatted_findings = ""
    for f in findings:
        formatted_findings += f"- Categoría: {f.get('category', 'N/A')}\n  Detalle: {f.get('description', 'Sin descripción')}\n\n"

    return f"""
Redacta un informe profesional de auditoría web para la URL: {url}

Incluye los siguientes hallazgos en formato estructurado y comprensible para un equipo técnico:

{formatted_findings}

Evita explicaciones redundantes, mantén un lenguaje técnico claro y profesional.
"""