"""Ragas import compatibility for LangChain package splits.

Ragas 0.4.x still imports ChatVertexAI from langchain_community, but newer
langchain-community releases moved it to langchain-google-vertexai. We do not
use Vertex AI here; this shim only satisfies Ragas' import-time dependency.
"""

import sys
import types

_VERTEXAI_MODULE = "langchain_community.chat_models.vertexai"


def _register_vertexai_shim() -> None:
    if _VERTEXAI_MODULE in sys.modules:
        return

    try:
        from langchain_google_vertexai import ChatVertexAI
    except ImportError:

        class ChatVertexAI:  # noqa: D101
            """Unused stub; Ragas imports this symbol at module load time."""

    module = types.ModuleType(_VERTEXAI_MODULE)
    module.ChatVertexAI = ChatVertexAI
    sys.modules[_VERTEXAI_MODULE] = module


_register_vertexai_shim()
