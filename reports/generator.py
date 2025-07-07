from fpdf import FPDF
from datetime import datetime
from pathlib import Path
import textwrap
from gpt import summarize
from typing import Any

class StyledPDF(FPDF):
    """
    Custom PDF class with a predefined header, footer, and styling
    for rendering structured audit reports.
    """
    def header(self):
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 10, "Informe Técnico de Auditoría", ln=1, align="C")
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Página {self.page_no()}", align="C")

    def add_section(self, title: str, content: str):
        """
        Adds a titled section with wrapped text to the PDF document.

        Args:
            title (str): Section title.
            content (str): Section body content.
        """
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
    """
    Generates a PDF report from the given summary content.

    The report is divided into sections and saved in the 'reports/' directory
    with a timestamped filename.

    Args:
        content (str): Textual content structured with optional section titles.

    Returns:
        str: Path to the generated PDF file.
    """
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
    """
    Generates a PDF report by summarizing findings using GPT and rendering it.

    Args:
        url (str): Audited target URL.
        findings (list): List of findings from the audit.
        api_key (str): OpenAI API token for summary generation.

    Returns:
        str: Path to the generated PDF report.
    """
    data = {"url": url, "findings": findings}
    content = summarize.generate_summary(data)
    return generate_pdf_report(content)