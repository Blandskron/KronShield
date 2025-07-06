from fpdf import FPDF
from datetime import datetime
from pathlib import Path
import textwrap
from gpt import summarize
from typing import Any

class StyledPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 10, "Informe Técnico de Auditoría", ln=1, align="C")
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Página {self.page_no()}", align="C")

    def add_section(self, title: str, content: str):
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(30, 30, 30)
        self.cell(0, 10, title, ln=True)

        self.set_font("Helvetica", "", 11)
        self.set_text_color(50, 50, 50)

        wrapped = textwrap.wrap(content, 100)
        for line in wrapped:
            self.cell(0, 6, line, ln=True)
        self.ln(5)

def generate_pdf_report(content: str) -> str:
    pdf = StyledPDF()
    pdf.add_page()

    sections = content.strip().split("\n\n")

    for section in sections:
        if ":" in section:
            title, body = section.split(":", 1)
        else:
            title, body = "Sección", section
        pdf.add_section(title.strip(), body.strip())

    filename = f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    output_path = Path("reports") / filename
    output_path.parent.mkdir(exist_ok=True, parents=True)
    pdf.output(str(output_path))

    return str(output_path)

def generate_pdf_report_from_json(url: str, findings: list[Any], api_key: str) -> str:
    data = {"url": url, "findings": findings}
    content = summarize.generate_summary(data)
    return generate_pdf_report(content)