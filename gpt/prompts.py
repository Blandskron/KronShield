def summary_prompt(data: dict) -> str:
    url = data.get("url", "URL no especificada")
    findings = data.get("findings", [])

    formatted_findings = ""
    for idx, f in enumerate(findings, 1):
        ftype = str(f.get("type", "info")).upper()
        detail = f.get("detail", "Sin descripción")
        formatted_findings += f"- Hallazgo {idx} [{ftype}]: {detail}\n"
        if f.get("url"):
            formatted_findings += f"  URL: {f['url']}\n"
        if f.get("payload"):
            formatted_findings += f"  Payload: {f['payload']}\n"
        extra = f.get("extra") or {}
        if isinstance(extra, dict) and extra.get("missing_security_headers"):
            formatted_findings += (
                "  Cabeceras ausentes: "
                + ", ".join(extra["missing_security_headers"]) + "\n"
            )

    return f"""
Redacta un informe profesional de auditoría de seguridad web para la URL: {url}

Basándote EXCLUSIVAMENTE en los siguientes hallazgos técnicos reales, redacta el informe.
No inventes vulnerabilidades que no estén listadas; si un hallazgo es solo informativo, indícalo.
Para cada hallazgo relevante, evalúa su severidad (Alta/Media/Baja/Informativa) e impacto.

Hallazgos detectados:
{formatted_findings}

El formato debe usar encabezados '##' y '###' para separar secciones y subsecciones. Usa viñetas y saltos de línea claros.

Estructura esperada:

## Resumen Ejecutivo

[Breve introducción profesional]

## Hallazgos Detallados

[Analiza cada hallazgo en su propia subsección '### <título descriptivo>', indicando severidad, descripción técnica e impacto]

## Recomendaciones Finales

[Incluir recomendaciones priorizadas y accionables]

El informe se renderizará como HTML, por lo tanto evita emojis y mantén un lenguaje técnico y claro.
"""
