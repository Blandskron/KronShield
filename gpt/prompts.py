def xss_prompt(url: str):
    """
    Returns a prompt instructing GPT to generate modern XSS payloads.

    The payloads are intended for GET parameters targeting the specified URL.
    Each payload should be returned on a separate line with no explanations.

    Args:
        url (str): The target URL to include in the context.

    Returns:
        str: A formatted prompt for XSS payload generation.
    """
    return f"""
Genera 10 payloads modernos y difíciles de detectar de Cross Site Scripting (XSS) para atacar parámetros GET en la URL:
{url}
Cada payload debe estar en una línea diferente sin explicaciones.
"""

def sqli_prompt(url: str):
    """
    Returns a prompt instructing GPT to generate SQL Injection payloads.

    The payloads target 'user' and 'pass' parameters using various SQLi techniques.
    Each payload should be listed on a new line without additional commentary.

    Args:
        url (str): The target URL to contextualize the injection.

    Returns:
        str: A formatted prompt for SQLi payload generation.
    """
    return f"""
Genera 10 payloads efectivos de SQL Injection para URLs con parámetros 'user' y 'pass'.
Incluye UNION, comentarios, combinaciones de bypass, y técnicas modernas.
Aplica sobre esta URL: {url}
Formato: uno por línea, sin texto adicional.
"""

def summary_prompt(data: dict):
    """
    Returns a prompt instructing GPT to write a technical audit summary.

    Includes structured findings extracted from a prior audit execution.
    Output is meant to be clear, concise, and professional.

    Args:
        data (dict): A dictionary containing 'url' and 'findings' keys.

    Returns:
        str: A formatted prompt for audit summary generation.
    """
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
