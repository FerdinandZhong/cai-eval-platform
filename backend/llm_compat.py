"""Compatibility shim for the chat-completions token-limit parameter.

Newer OpenAI models (GPT-5 / o-series) reject ``max_tokens`` and require
``max_completion_tokens``; self-hosted / older OpenAI-compatible servers (vLLM,
TGI, llama.cpp, older OpenAI) only accept ``max_tokens``. To stay compatible
with both, send ``max_tokens`` first and transparently retry with
``max_completion_tokens`` only when the server explicitly rejects it.
"""

import openai


def chat_completion(client, *, max_tokens=None, **kwargs):
    """``client.chat.completions.create`` with token-param auto-negotiation.

    Pass the token budget as ``max_tokens``; it is retried as
    ``max_completion_tokens`` if (and only if) the endpoint rejects the former.
    All other kwargs (model, messages, temperature, timeout, ...) pass through.
    """
    if max_tokens is None:
        return client.chat.completions.create(**kwargs)
    try:
        return client.chat.completions.create(max_tokens=max_tokens, **kwargs)
    except openai.BadRequestError as e:
        # The 400 body names the replacement, e.g. "Unsupported parameter:
        # 'max_tokens' is not supported with this model. Use
        # 'max_completion_tokens' instead." Only retry on that specific signal.
        if "max_completion_tokens" in str(e).lower():
            return client.chat.completions.create(
                max_completion_tokens=max_tokens, **kwargs
            )
        raise


def patch_async_client(client):
    """Make an ``AsyncOpenAI`` client negotiate the token-limit param.

    Wraps ``client.chat.completions.create`` so a ``max_tokens`` rejection is
    retried as ``max_completion_tokens``. Used for libraries (e.g. ragas) that
    own the call site and only let us inject the client. Idempotent; returns the
    client. Best-effort — if the client can't be patched it is returned as-is.
    """
    try:
        completions = client.chat.completions
        if getattr(completions, "_max_tokens_compat", False):
            return client
        original = completions.create

        async def _create(*args, **kwargs):
            try:
                return await original(*args, **kwargs)
            except openai.BadRequestError as e:
                if "max_completion_tokens" in str(e).lower() and "max_tokens" in kwargs:
                    kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                    return await original(*args, **kwargs)
                raise

        completions.create = _create
        completions._max_tokens_compat = True
    except Exception:  # noqa: BLE001 — never let the shim break the caller
        pass
    return client


if __name__ == "__main__":
    # Self-check: no network — a fake client proves the retry logic.
    import httpx

    def _bad_request():
        resp = httpx.Response(400, request=httpx.Request("POST", "http://x/v1"))
        return openai.BadRequestError(
            message="Unsupported parameter: 'max_tokens' is not supported. Use 'max_completion_tokens' instead.",
            response=resp,
            body=None,
        )

    class _Resp:
        def __init__(self, param):
            self.param = param

    class _Completions:
        def __init__(self, reject_max_tokens):
            self.reject = reject_max_tokens

        def create(self, **kw):
            if "max_tokens" in kw and self.reject:
                raise _bad_request()
            return _Resp(next(k for k in ("max_tokens", "max_completion_tokens") if k in kw))

    class _Client:
        def __init__(self, reject):
            self.chat = type("C", (), {"completions": _Completions(reject)})()

    # vLLM / old server: max_tokens accepted, no retry.
    assert chat_completion(_Client(reject=False), max_tokens=16, model="m", messages=[]).param == "max_tokens"
    # New GPT model: max_tokens rejected, retried as max_completion_tokens.
    assert chat_completion(_Client(reject=True), max_tokens=16, model="m", messages=[]).param == "max_completion_tokens"

    # Async path (ragas-style injected client).
    import asyncio

    class _AsyncCompletions:
        def __init__(self, reject):
            self.reject = reject

        async def create(self, **kw):
            if "max_tokens" in kw and self.reject:
                raise _bad_request()
            return _Resp(next(k for k in ("max_tokens", "max_completion_tokens") if k in kw))

    class _AsyncClient:
        def __init__(self, reject):
            self.chat = type("C", (), {"completions": _AsyncCompletions(reject)})()

    async def _call(reject):
        c = patch_async_client(_AsyncClient(reject))
        return (await c.chat.completions.create(max_tokens=16, model="m", messages=[])).param

    assert asyncio.run(_call(False)) == "max_tokens"
    assert asyncio.run(_call(True)) == "max_completion_tokens"
    print("llm_compat self-check passed")
