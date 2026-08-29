"""
Output language for generated content.

The prompts themselves are partly written in Chinese, which the model handles
fine. What decides the language of the *output* — the report, the personas,
the simulated posts — is the explicit instruction inside them.

Those instructions carry a `{output_language}` token that is replaced once, at
import time, with Config.OUTPUT_LANGUAGE. Substituting at import rather than
adding a new .format() placeholder matters: several of these prompts are
.format()-ed later with other fields, and an unexpected placeholder would
raise KeyError at request time.
"""

from ..config import Config

TOKEN = "{output_language}"


def localize(text: str) -> str:
    """Replace the language token with the configured output language."""
    if not text:
        return text
    return text.replace(TOKEN, Config.OUTPUT_LANGUAGE)
