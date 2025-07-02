import openai

def init(token: str):
    openai.api_key = token

def generate_payloads(prompt: str, max_tokens=200):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Eres un experto en hacking ético y generador de payloads evasivos."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=max_tokens,
            temperature=0.7
        )
        return response['choices'][0]['message']['content'].strip().splitlines()
    except Exception as e:
        return [f"ERROR: {e}"]
