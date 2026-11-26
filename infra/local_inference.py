"""Bounded client for the isolated, opt-in llama.cpp service."""

import asyncio
import json

import httpx

from application.analysis_proposals import (
    PROPOSAL, ModelVersion, ProposalBudgetExceeded, ProposalDependencyMissing, ProviderReply,
)


MODEL = ModelVersion(id="qwen2.5-1.5b-instruct-q4_k_m",
                     digest="6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e")
BASE_URL = "http://inference:8080"
CONTEXT_TOKENS = 2048
TIMEOUT_SECONDS = 12
ENVELOPE_BYTES = 65536


async def _request(client: httpx.AsyncClient, path: str, payload: dict) -> dict:
    try:
        async with client.stream("POST", path, json=payload, headers={"Accept-Encoding": "identity"}) as response:
            if response.status_code == 503:
                raise ProposalDependencyMissing
            response.raise_for_status()
            if response.headers.get("content-encoding", "identity") != "identity":
                raise ValueError("Unexpected inference response encoding")
            body = bytearray()
            async for chunk in response.aiter_raw(chunk_size=8192):
                if len(body) + len(chunk) > ENVELOPE_BYTES:
                    raise ProposalBudgetExceeded
                body.extend(chunk)
    except httpx.ConnectError:
        raise ProposalDependencyMissing from None
    result = json.loads(body.decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Invalid inference response")
    return result


class LocalProposalProvider:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    def complete(self, instructions: str, context: bytes, *, input_token_limit: int,
                 output_token_limit: int, output_byte_limit: int) -> ProviderReply:
        # The application calls this synchronous port from a worker outside database transactions.
        async def bounded() -> ProviderReply:
            return await asyncio.wait_for(
                self._complete(instructions, context, input_token_limit, output_token_limit, output_byte_limit),
                timeout=TIMEOUT_SECONDS,
            )

        try:
            return asyncio.run(bounded())
        except (asyncio.TimeoutError, httpx.TimeoutException):
            raise TimeoutError from None

    async def _complete(self, instructions: str, context: bytes, input_limit: int,
                        output_limit: int, byte_limit: int) -> ProviderReply:
        async with httpx.AsyncClient(base_url=BASE_URL, trust_env=False, follow_redirects=False, timeout=None,
                                     transport=self._transport) as client:
            formatted = await _request(client, "/apply-template", {"messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": context.decode("utf-8")},
            ]})
            prompt = formatted["prompt"]
            if not isinstance(prompt, str):
                raise ValueError("Invalid chat template response")
            tokenized = await _request(client, "/tokenize", {"content": prompt, "add_special": True})
            tokens = tokenized["tokens"]
            if not isinstance(tokens, list) or not tokens or any(type(token) is not int or token < 0 for token in tokens):
                raise ValueError("Invalid tokenization response")
            if len(tokens) > input_limit or len(tokens) + output_limit > CONTEXT_TOKENS:
                raise ProposalBudgetExceeded
            result = await _request(client, "/completion", {
                "prompt": tokens, "n_predict": output_limit, "stream": False, "temperature": 0,
                "cache_prompt": False, "json_schema": PROPOSAL.json_schema(),
            })
        if (result.get("truncated") is not False or result.get("stop_type") != "eos"
                or result.get("tokens_evaluated") != len(tokens)):
            raise ValueError("Incomplete inference response")
        body = result["content"].encode("utf-8")
        if len(body) > byte_limit:
            raise ProposalBudgetExceeded
        return ProviderReply(body=body, input_tokens=len(tokens), output_tokens=result["tokens_predicted"])
