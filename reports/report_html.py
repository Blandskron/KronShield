import re
from pathlib import Path
from datetime import datetime, timezone


def _inline(text: str) -> str:
    """Render inline Markdown (bold/italic/code) to HTML, escaping angle brackets."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
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


def generate_html_report(content: str, domain: str) -> str:
    """Convert a Markdown audit report into a styled HTML file under results/{domain}."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Parse line by line so that headings are detected only at the start of a
    # line (avoids "### " being mistaken for a "## " section).
    body_html = ""
    buffer: list[str] = []

    def flush_buffer():
        nonlocal body_html
        text = "\n".join(buffer).strip()
        if text:
            body_html += _render_body(text) + "\n"
        buffer.clear()

    for line in content.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith("### "):
            flush_buffer()
            body_html += f"<h3>{_inline(stripped[4:].strip())}</h3>\n"
        elif stripped.startswith("## "):
            flush_buffer()
            body_html += f"<h2>{_inline(stripped[3:].strip())}</h2>\n"
        elif stripped.startswith("# "):
            flush_buffer()
            body_html += f"<h2>{_inline(stripped[2:].strip())}</h2>\n"
        else:
            buffer.append(line)
    flush_buffer()

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Informe de Auditoría - {domain}</title>
    <style>
        body {{ font-family: Arial, Helvetica, sans-serif; margin: 2em; background: #fefefe; color: #333; }}
        h1 {{ text-align: center; color: #004080; }}
        h2 {{ color: #0055a5; border-bottom: 1px solid #ccc; margin-top: 1.5em; padding-bottom: .2em; }}
        h3 {{ color: #003366; margin-top: 1em; }}
        p {{ line-height: 1.6; }}
        ul {{ line-height: 1.6; }}
        code {{ background: #f2f2f2; padding: 1px 4px; border-radius: 3px; font-family: Consolas, monospace; }}
        .timestamp {{ font-size: 0.9em; color: #888; text-align: center; margin-bottom: 2em; }}
        .container {{ max-width: 820px; margin: auto; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Informe Técnico de Auditoría</h1>
        <div class="timestamp">Objetivo: {domain} &middot; Generado el {now}</div>
{body_html}
    </div>
</body>
</html>"""

    output_dir = Path("results") / domain
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{domain}.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return str(output_path)
