"""The only file that talks to Gemini. Every tool goes through here,
so swapping models or providers later means editing one module."""
import time

import numpy as np
from google import genai
from google.genai import errors, types

from . import config

_client = None
RETRYABLE_CODES = {429, 500, 502, 503, 504}  # rate limit / overloaded / temporary server errors


def _http_options():
    """Short timeout and no silent SDK retries: our own retry + fallback loop handles failures
    quickly and shows real errors instead of hanging."""
    try:
        return types.HttpOptions(
            timeout=config.REQUEST_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=1),
        )
    except Exception:  # older SDK without retry_options
        return types.HttpOptions(timeout=config.REQUEST_TIMEOUT_MS)


def _get_client():
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("No API key found. Set GEMINI_API_KEY in your .env file.")
        _client = genai.Client(api_key=config.GEMINI_API_KEY, http_options=_http_options())
    return _client


def _is_transient(exc):
    """True for errors worth retrying (busy server, rate limit, timeout)."""
    if isinstance(exc, errors.APIError):
        return getattr(exc, "code", None) in RETRYABLE_CODES
    return isinstance(exc, (TimeoutError, ConnectionError)) or "timeout" in type(exc).__name__.lower()


def _call_with_retry(call, models):
    """Try each model in order, retrying transient errors with exponential backoff.
    A non-transient error on the first model (bad key, wrong model name) is raised immediately."""
    last_error = None
    for model in models:
        for attempt in range(config.MAX_RETRIES):
            try:
                return call(model)
            except Exception as exc:
                if not _is_transient(exc):
                    if last_error is None:
                        raise
                    break  # fallback model is misconfigured; report the original busy error below
                last_error = exc
                if attempt < config.MAX_RETRIES - 1:
                    time.sleep(config.RETRY_BASE_DELAY * (2 ** attempt))
    raise last_error


def _chat_models():
    models = [config.CHAT_MODEL]
    if config.FALLBACK_MODEL and config.FALLBACK_MODEL != config.CHAT_MODEL:
        models.append(config.FALLBACK_MODEL)
    return models


def embed(texts, task="RETRIEVAL_DOCUMENT", batch_size=100):
    """Return an (n, dim) float32 array of L2-normalised embeddings.

    task: RETRIEVAL_DOCUMENT for stored chunks, RETRIEVAL_QUERY for questions.
    """
    vectors = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        result = _call_with_retry(
            lambda model, batch=batch: _get_client().models.embed_content(
                model=model,
                contents=batch,
                config=types.EmbedContentConfig(task_type=task),
            ),
            [config.EMBED_MODEL],
        )
        vectors.extend(item.values for item in result.embeddings)

    array = np.array(vectors, dtype="float32")
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return array / norms  # normalised, so inner product == cosine similarity


def _to_contents(prompt, history, images=None):
    """history is [(role, text)] with role 'user' or 'assistant'; Gemini calls the latter 'model'.
    images is [(bytes, mime_type)] attached to the newest user message."""
    contents = []
    for role, text in history or []:
        contents.append(
            types.Content(
                role="model" if role == "assistant" else "user",
                parts=[types.Part(text=text)],
            )
        )
    parts = [types.Part.from_bytes(data=data, mime_type=mime) for data, mime in images or []]
    parts.append(types.Part(text=prompt))  # image first, then the question
    contents.append(types.Content(role="user", parts=parts))
    return contents


def generate(prompt, system=None, history=None, images=None, temperature=None):
    """Text generation with optional chat history and images, plus retries and a fallback model."""
    contents = _to_contents(prompt, history, images)
    options = {}
    if system:
        options["system_instruction"] = system
    if temperature is not None:
        options["temperature"] = temperature
    generation_config = types.GenerateContentConfig(**options) if options else None

    def call(model):
        response = _get_client().models.generate_content(
            model=model, contents=contents, config=generation_config
        )
        return response.text or ""

    return _call_with_retry(call, _chat_models())
