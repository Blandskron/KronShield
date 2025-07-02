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
