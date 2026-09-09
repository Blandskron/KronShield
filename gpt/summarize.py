"""Generate a professional audit report from findings using Groq."""
from gpt import prompts, client


def generate_summary(data: dict) -> str:
    """
    Generate a professional web-audit report using the Groq LLM.

    Args:
        data: dict with audit metadata and findings.

    Returns:
        The generated Markdown report as a string.
    """
    prompt = prompts.summary_prompt(data)
    return client.chat(
        messages=[
            {
                "role": "system",
                "content": "Eres un experto en ciberseguridad que redacta informes de auditoría claros y accionables.",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=2048,
    )
