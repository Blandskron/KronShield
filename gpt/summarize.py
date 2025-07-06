from gpt import prompts, client

def generate_summary(data: dict) -> str:
    prompt = prompts.summary_prompt(data)
    openai_client = client.get_client()

    response = openai_client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Eres un experto en ciberseguridad."},
            {"role": "user", "content": prompt},
        ]
    )
    return response.choices[0].message.content.strip()
