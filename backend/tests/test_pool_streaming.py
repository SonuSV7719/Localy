from __future__ import annotations

import sys

import pytest

sys.path.insert(0, "src")

from localy.api.v1 import chat
from localy.schemas.openai import ChatCompletionRequest


class _FakeStreamResponse:
    status_code = 200

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def __aenter__(self) -> "_FakeStreamResponse":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeAsyncClient:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def stream(self, *_args: object, **_kwargs: object) -> _FakeStreamResponse:
        return _FakeStreamResponse(
            [
                'data: {"choices":[null]}',
                'data: {"choices":[{"delta":{"content":"hi"}}]}',
                "data: [DONE]",
            ]
        )


@pytest.mark.asyncio
async def test_pool_stream_metrics_do_not_break_on_unusual_choice_payload(monkeypatch) -> None:
    monkeypatch.setattr(chat.httpx, "AsyncClient", _FakeAsyncClient)
    request = ChatCompletionRequest(
        model="test:1b",
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
        max_tokens=4,
    )

    response = await chat._proxy_to_pool("http://pool.local", request)

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    body = "".join(chunks)

    assert '"choices":[null]' in body
    assert '"content":"hi"' in body
    assert '"type": "stream_metrics"' in body
    assert "pool proxy error" not in body
    assert body.rstrip().endswith("data: [DONE]")
