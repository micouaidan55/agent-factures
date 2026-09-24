"""Client Anthropic factice : renvoie des réponses scriptées, n'appelle jamais le réseau."""

from itertools import count
from types import SimpleNamespace

_ids = count(1)


def tool_use(name: str, tool_input: dict, id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id or f"toolu_{next(_ids)}", name=name, input=tool_input)


def reply(*blocks, stop_reason: str = "tool_use", input_tokens: int = 100, output_tokens: int = 50) -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=list(blocks),
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
