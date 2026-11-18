import re
from html import escape

from application.report_input import SavedAudit
from infra.artifacts import publish_report


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


def _document(target: str, body_html: str) -> str:
    label = escape(target)
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="Content-Security-Policy"
          content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
    <title>Informe de Auditoría - {label}</title>
    <style>
        body {{ font-family: Arial, Helvetica, sans-serif; margin: 2em; background: #fefefe; color: #333; }}
        h1 {{ text-align: center; color: #004080; }}
        h2 {{ color: #0055a5; border-bottom: 1px solid #ccc; margin-top: 1.5em; padding-bottom: .2em; }}
        h3 {{ color: #003366; margin-top: 1em; }}
        p {{ line-height: 1.6; }}
        ul {{ line-height: 1.6; }}
        code {{ background: #f2f2f2; padding: 1px 4px; border-radius: 3px; font-family: Consolas, monospace; }}
        .target {{ text-align: center; overflow-wrap: anywhere; }}
        p, code {{ overflow-wrap: anywhere; }}
        .container {{ max-width: 820px; margin: auto; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Informe Técnico de Auditoría</h1>
        <p class="target">Objetivo: {label}</p>
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
        blocks.append(f"<p>{escape(finding.detail)}</p>")
        if finding.url:
            blocks.append(f"<p>Ubicación: {escape(finding.url)}</p>")
        if finding.payload:
            blocks.append(f"<p>Valor de prueba: <code>{escape(finding.payload)}</code></p>")
        if finding.extra and finding.extra.missing_security_headers:
            headers = ", ".join(finding.extra.missing_security_headers)
            blocks.append(f"<p>Cabeceras ausentes: {escape(headers)}</p>")
    if summary:
        blocks.extend(("<h2>Resumen asistido por IA</h2>", _render_markdown(summary)))
    return str(publish_report(_document(audit.url, "\n".join(blocks)), "html"))
