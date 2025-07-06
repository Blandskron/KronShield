import openai

_client = None

def init(token: str):
    """Initialize OpenAI client with API key."""
    global _client
    _client = openai.OpenAI(api_key=token)

def get_client():
    """Returns the initialized OpenAI client."""
    return _client

def generate_payloads(prompt: str, max_tokens: int = 200):
    """Generate payloads from a given prompt using OpenAI."""
    if _client is None:
        raise RuntimeError("Client not initialized. Call init(token) first.")

    try:
        response = _client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Eres un experto en hacking ético y generador de payloads evasivos."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=max_tokens,
            temperature=0.7
        )
        return response.choices[0].message.content.strip().splitlines()
    except Exception as e:
        return [f"ERROR: {e}"]
