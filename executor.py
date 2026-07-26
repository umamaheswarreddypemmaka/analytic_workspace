"""
LLM access via OpenRouter.

The key is read from the environment only. Never paste a key into this file —
anything committed to a repo is a key you have to rotate.
"""

import os
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv

# Look for .env next to this file first, then fall back to the working
# directory. Streamlit is often launched from a different folder than the one
# the code lives in, and the default search misses the file when that happens.
_HERE = Path(__file__).resolve().parent
for candidate in (_HERE / ".env", Path.cwd() / ".env"):
    if candidate.is_file():
        load_dotenv(candidate, override=False)
        break
else:
    load_dotenv()

# Windows hides file extensions, so ".env" saved from Notepad is often
# ".env.txt". Read it anyway rather than making the person hunt for it.
_stray = _HERE / ".env.txt"
if not os.getenv("OPENROUTER_API_KEY") and _stray.is_file():
    load_dotenv(_stray, override=False)

DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-5")

# Known-good OpenRouter slugs, cheapest first. Model ids get retired without
# notice, so the app offers a list plus a free-text escape hatch rather than
# hardcoding one name that quietly stops working months from now.
KNOWN_MODELS = [
    "anthropic/claude-haiku-4.5",
    "anthropic/claude-sonnet-5",
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-opus-4.8",
    "openai/gpt-4.1-mini",
    "google/gemini-2.5-flash",
]
_client = None
_runtime_key = None          # set from the sidebar, lives for the session only


def set_api_key(key):
    """Supply a key at runtime instead of through .env. Not persisted."""
    global _runtime_key, _client
    _runtime_key = (key or "").strip() or None
    _client = None           # force a fresh client on the next call


def current_key():
    return _runtime_key or os.getenv("OPENROUTER_API_KEY")


def is_configured():
    return bool(current_key())


def key_source():
    """Where the key came from — shown in the sidebar so it's never a mystery."""
    if _runtime_key:
        return "entered in the sidebar"
    if os.getenv("OPENROUTER_API_KEY"):
        return "loaded from .env"
    return "not set"


class LLMNotConfigured(RuntimeError):
    pass


def get_client():
    global _client
    if _client is None:
        api_key = current_key()
        if not api_key:
            raise LLMNotConfigured(
                "No OpenRouter key found. Either paste one into the sidebar under "
                "'AI settings', or put OPENROUTER_API_KEY in a .env file next to "
                "app.py and restart the app."
            )
        _client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
    return _client


# A dashboard spec runs ~1,500 tokens and an insight summary ~800. Without an
# explicit ceiling the provider assumes its own maximum (often 64k) and
# reserves credit for all of it, which fails on small balances for no reason.
DEFAULT_MAX_TOKENS = 4096


def ask(prompt, system=None, model=None, temperature=0.2, json_mode=False,
        max_tokens=DEFAULT_MAX_TOKENS):
    """Single-turn completion. Returns the reply text."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs = dict(
        model=model or DEFAULT_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = get_client().chat.completions.create(**kwargs)
    except Exception as e:
        if "402" in str(e) or "credits" in str(e).lower():
            raise RuntimeError(
                "OpenRouter rejected the request for lack of credits. Add credit at "
                "openrouter.ai/settings/credits, or switch to a cheaper model "
                "(anthropic/claude-haiku-4.5)."
            ) from e
        # Not every model on OpenRouter honours response_format; retry without it.
        if json_mode:
            kwargs.pop("response_format", None)
            response = get_client().chat.completions.create(**kwargs)
        else:
            raise e
    return response.choices[0].message.content


# Backwards-compatible name used by the earlier version of this app.
def ask_openrouter(prompt):
    return ask(prompt)