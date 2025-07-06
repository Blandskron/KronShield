import openai

_client = None

def init(token: str):
    global _client
    _client = openai.OpenAI(api_key=token)

def get_client():
    return _client
