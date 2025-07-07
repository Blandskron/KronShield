from pathlib import Path
from datetime import datetime

def generate_html_report(content: str, domain: str) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Informe de Auditoría - {domain}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 2em; background: #fefefe; color: #333; }}
        h1 {{ text-align: center; color: #004080; }}
        h2 {{ color: #0055a5; border-bottom: 1px solid #ccc; margin-top: 1.5em; }}
        h3 {{ color: #003366; margin-top: 1em; }}
        p {{ line-height: 1.6; }}
        .timestamp {{ font-size: 0.9em; color: #888; text-align: center; }}
        .container {{ max-width: 800px; margin: auto; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Informe Técnico de Auditoría</h1>
        <div class="timestamp">Generado el {now}</div>
"""

    sections = content.strip().split("## ")
    for sec in sections:
        if not sec.strip():
            continue
        lines = sec.strip().split("\n", 1)
        title = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""
        html += f"<h2>{title}</h2>\n"

        subsections = body.split("### ")
        for sub in subsections:
            if not sub.strip():
                continue
            sub_lines = sub.strip().split("\n", 1)
            sub_title = sub_lines[0].strip()
            sub_body = sub_lines[1].strip() if len(sub_lines) > 1 else ""
            html += f"<h3>{sub_title}</h3>\n<p>{sub_body.replace('\n', '<br>')}</p>\n"

    html += "</div></body></html>"

    output_dir = Path("results") / domain
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{domain}.html"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return str(output_path)
