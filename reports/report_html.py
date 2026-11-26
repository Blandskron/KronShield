import re
from html import escape

from application.report_input import SavedAudit
from domain.models import FindingConfidence, FindingStatus
from infra.artifacts import publish_report


_STATUS_LABELS = {
    FindingStatus.OBSERVED: "Observación",
    FindingStatus.SUSPECTED: "Sospecha",
    FindingStatus.INCONCLUSIVE: "Inconcluso",
}
_CONFIDENCE_LABELS = {FindingConfidence.LOW: "Baja", FindingConfidence.MEDIUM: "Media"}


def _inline(text: str) -> str:
    """Render the supported inline Markdown on escaped text."""
    text = escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def _render_body(body: str) -> str:
    """Render a block of Markdown (paragraphs + bullet/numbered lists) to HTML."""
    html_parts = []
    list_buffer = []

    def flush_list():
        if list_buffer:
            items = "".join(f"<li>{_inline(i)}</li>" for i in list_buffer)
            html_parts.append(f"<ul>{items}</ul>")
            list_buffer.clear()

    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            flush_list()
            continue
        m = re.match(r"^(?:[-*]|\d+[\.\)])\s+(.*)$", line)
        if m:
            list_buffer.append(m.group(1))
        else:
            flush_list()
            html_parts.append(f"<p>{_inline(line)}</p>")
    flush_list()
    return "\n".join(html_parts)


def _render_markdown(content: str) -> str:
    # Parse line by line so that headings are detected only at the start of a
    # line (avoids "### " being mistaken for a "## " section).
    blocks = []
    buffer: list[str] = []

    def flush_buffer():
        text = "\n".join(buffer).strip()
        if text:
            blocks.append(_render_body(text))
        buffer.clear()

    for line in content.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith("### "):
            flush_buffer()
            blocks.append(f"<h3>{_inline(stripped[4:].strip())}</h3>")
        elif stripped.startswith("## "):
            flush_buffer()
            blocks.append(f"<h2>{_inline(stripped[3:].strip())}</h2>")
        elif stripped.startswith("# "):
            flush_buffer()
            blocks.append(f"<h2>{_inline(stripped[2:].strip())}</h2>")
        else:
            buffer.append(line)
    flush_buffer()
    return "\n".join(blocks)


def _document(target: str, body_html: str, *, heading: str = "Informe Técnico de Auditoría",
              subject_label: str = "Objetivo", title: str = "Informe de Auditoría") -> str:
    label = escape(target)
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="Content-Security-Policy"
          content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
    <title>{escape(title)} - {label}</title>
    <style>
        body {{ font-family: Arial, Helvetica, sans-serif; margin: 2em; background: #fefefe; color: #333; }}
        h1 {{ text-align: center; color: #004080; }}
        h2 {{ color: #0055a5; border-bottom: 1px solid #ccc; margin-top: 1.5em; padding-bottom: .2em; }}
        h3 {{ color: #003366; margin-top: 1em; }}
        p {{ line-height: 1.6; }}
        ul {{ line-height: 1.6; }}
        code {{ background: #f2f2f2; padding: 1px 4px; border-radius: 3px; font-family: Consolas, monospace; }}
        .target {{ text-align: center; overflow-wrap: anywhere; }}
        p, code, dd, td {{ overflow-wrap: anywhere; }}
        dt {{ font-weight: bold; margin-top: .65em; }}
        dd {{ margin-left: 0; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ text-align: left; border-bottom: 1px solid #ddd; padding: .4em; }}
        .container {{ max-width: 820px; margin: auto; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{escape(heading)}</h1>
        <p class="target">{escape(subject_label)}: {label}</p>
{body_html}
    </div>
</body>
</html>"""


def generate_html_report(content: str, domain: str) -> str:
    """Publish the supported Markdown with the supplied label displayed as text."""
    return str(publish_report(_document(domain, _render_markdown(content)), "html"))


def generate_audit_html_report(audit: SavedAudit, summary: str | None = None) -> str:
    """Publish a deterministic report of the saved observations."""
    blocks = ["<h2>Hallazgos registrados</h2>", f"<p>Total de registros: {len(audit.findings)}</p>"]
    for index, finding in enumerate(audit.findings, 1):
        blocks.append(f"<h3>{index}. {escape(finding.type)}</h3>")
        if finding.status is not None:
            blocks.append(f"<p>Estado: {_STATUS_LABELS[finding.status]}</p>")
        if finding.confidence is not None:
            blocks.append(f"<p>Confianza: {_CONFIDENCE_LABELS[finding.confidence]}</p>")
        blocks.append(f"<p>{escape(finding.detail)}</p>")
        if finding.url:
            blocks.append(f"<p>Ubicación: {escape(finding.url)}</p>")
        if finding.payload:
            blocks.append(f"<p>Valor de prueba: <code>{escape(finding.payload)}</code></p>")
        if finding.extra and finding.extra.missing_security_headers:
            headers = ", ".join(finding.extra.missing_security_headers)
            blocks.append(f"<p>Cabeceras ausentes: {escape(headers)}</p>")
        if finding.extra and finding.extra.signatures:
            signatures = ", ".join(finding.extra.signatures)
            blocks.append(f"<p>Firmas de error: {escape(signatures)}</p>")
    if summary:
        blocks.extend(("<h2>Resumen asistido por IA</h2>", _render_markdown(summary)))
    return str(publish_report(_document(audit.url, "\n".join(blocks)), "html"))


def render_scope_review_report(plan: dict, assessment_label: str) -> str:
    """Render a deterministic HTML report from the saved review snapshot."""
    authorization = plan["authorization"]

    def fields(pairs):
        return "\n".join(f"<dt>{escape(label)}</dt><dd>{escape(str(value))}</dd>" for label, value in pairs)

    metadata = (
        ("Evaluación", assessment_label), ("Organización", plan["org_id"]), ("Proyecto", plan["project_id"]),
        ("Revisión registrada", plan["checked_at"]), ("Estado", plan["status"]), ("SHA-256 del plan", plan["hash"]),
    )
    mandate = (
        ("Autorización", authorization["id"]), ("Revisión", authorization["revision"]),
        ("Estado al revisar", authorization["status"]), ("Vigente desde", authorization["valid_from"]),
        ("Vigente hasta", authorization["valid_until"]), ("SHA-256 del mandato", authorization["document_digest"]),
    )
    denials = "".join(f"<li>{escape(reason)}</li>" for reason in plan["denials"])
    denial_list = f"<ul>{denials}</ul>" if denials else "<p>Sin motivos registrados.</p>"
    rows = "".join(
        "<tr>" + "".join(f"<td>{escape(str(field))}</td>" for field in (
            item["canonical_address"], item["environment"], item["version"], item["reason"], item["rule_id"] or "—",
        )) + "</tr>"
        for item in plan["targets"]
    )
    body = (
        "<p>Simulación de alcance. Ejecución deshabilitada.</p>"
        f"<h2>Registro de la revisión</h2><dl>{fields(metadata)}</dl>"
        f"<h2>Autorización revisada</h2><dl>{fields(mandate)}</dl>"
        f"<h2>Motivos de bloqueo</h2>{denial_list}"
        "<h2>Activos revisados</h2><table><thead><tr>"
        "<th scope='col'>Dirección</th><th scope='col'>Entorno</th><th scope='col'>Versión</th>"
        "<th scope='col'>Resultado</th><th scope='col'>Regla</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )
    return _document(str(plan["id"]), body, heading="Informe de revisión de alcance",
                     subject_label="Plan", title="Revisión de alcance")


def render_analysis_report(publication: dict) -> str:
    """Render the frozen offline publication with plain-text evidence references."""
    def fields(pairs):
        return "".join(f"<dt>{escape(label)}</dt><dd>{escape(str(value))}</dd>" for label, value in pairs)

    metadata = (
        ("Plan", publication["plan_id"]), ("SHA-256 del plan", publication["plan_hash"]),
        ("SHA-256 del análisis", publication["snapshot_digest"]), ("Autor", publication["author_id"]),
        ("Publicó", publication["publisher_id"]), ("Publicación", publication["published_at"]),
        ("Modo", publication["mode_id"]), ("Versión del modo", publication["mode_version"]),
        ("Versión de selección", publication["selection_version"]), ("Plantilla", publication["template_version"]),
        ("Conclusiones rechazadas", publication["rejected"]),
    )
    body = [f"<h2>Registro de publicación</h2><dl>{fields(metadata)}</dl>", "<h2>Conclusiones aprobadas</h2>"]
    if not publication["approved"]:
        body.append("<p>Sin conclusiones aprobadas.</p>")
    statuses = {"observed": "Observado", "missing": "No observado", "inconclusive": "Inconcluso"}
    for item in publication["approved"]:
        evidence = "".join(f"<li><code>{escape(digest)}</code></li>" for digest in item["citations"])
        proof = item["provenance"]
        conclusion = [
            ("Estado", statuses[item["status"]]), ("Revisor", item["reviewer_id"]),
            ("Motivo", item["reason"]), ("Decisión registrada", item["decided_at"]),
            ("Herramienta", proof["tool"]), ("Especialidad", proof["mode_id"]),
            ("Versión de especialidad", proof["mode_version"]),
        ]
        if item["observation"]:
            conclusion.append(("Control", item["observation"]["control"]))
        if "model" in proof:
            conclusion.extend((
                ("Política", proof["policy_version"]), ("Prompt", proof["prompt_version"]),
                ("Modelo", proof["model"]["id"]), ("SHA-256 del modelo", proof["model"]["digest"]),
            ))
        body.append(f"<h3>{escape(item['id'])}</h3><dl>{fields(conclusion)}</dl>")
        if evidence:
            body.append(f"<h4>Referencias de evidencia</h4><ul>{evidence}</ul>")
    return _document(publication["analysis_id"], "\n".join(body), heading="Informe de análisis offline",
                     subject_label="Análisis", title="Análisis offline")
