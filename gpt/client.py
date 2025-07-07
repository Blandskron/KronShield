import openai

_client = None

def init(token: str):
    """
    Initializes the OpenAI client with the provided API token.

    This must be called before attempting to generate any payloads.
    """
    global _client
    _client = openai.OpenAI(api_key=token)

def get_client():
    """
    Returns the initialized OpenAI client instance.
    
    Raises:
        RuntimeError: If the client has not been initialized.
    """
    return _client

def generate_payloads(prompt: str, max_tokens: int = 200):
    """
    Generates a list of attack payloads using GPT based on the provided prompt.

    Args:
        prompt (str): The prompt to be sent to GPT (e.g., XSS or SQLi instructions).
        max_tokens (int): Maximum number of tokens to allow in the response.

    Returns:
        list[str]: A list of payload strings or an error message if generation fails.
    """
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
