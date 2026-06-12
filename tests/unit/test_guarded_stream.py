"""Unit tests for guarded_stream disconnect handling."""

from unittest.mock import MagicMock

import pytest

from src.api.streaming import guarded_stream


def make_request(*, disconnected_after: int = 999) -> MagicMock:
    """Return a mock Request whose is_disconnected() flips True after N calls."""
    request = MagicMock()
    call_count = 0

    async def is_disconnected():
        nonlocal call_count
        call_count += 1
        return call_count > disconnected_after

    request.is_disconnected = is_disconnected
    return request


class TrackingGen:
    """Async-iterable wrapper that records whether aclose() was called."""

    def __init__(self, *chunks):
        self._chunks = chunks
        self.aclose_called = False
        self._gen = self._source()

    async def _source(self):
        for chunk in self._chunks:
            yield chunk

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self._gen.__anext__()

    async def aclose(self):
        self.aclose_called = True
        await self._gen.aclose()


@pytest.mark.asyncio
async def test_yields_all_chunks_when_connected():
    request = make_request(disconnected_after=999)
    gen = TrackingGen("a", "b", "c")

    chunks = [chunk async for chunk in guarded_stream(request, gen)]

    assert chunks == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_stops_on_disconnect():
    """Disconnects after the first chunk; subsequent chunks must not be yielded."""
    request = make_request(disconnected_after=1)
    gen = TrackingGen("a", "b", "c")

    chunks = [chunk async for chunk in guarded_stream(request, gen)]

    assert chunks == ["a"]


@pytest.mark.asyncio
async def test_aclose_called_on_disconnect():
    """The upstream generator must be closed when the client disconnects."""
    request = make_request(disconnected_after=1)
    gen = TrackingGen("a", "b", "c")

    async for _ in guarded_stream(request, gen):
        pass

    assert gen.aclose_called


@pytest.mark.asyncio
async def test_aclose_called_on_normal_completion():
    """The upstream generator must be closed even when the stream finishes normally."""
    request = make_request(disconnected_after=999)
    gen = TrackingGen("a", "b")

    async for _ in guarded_stream(request, gen):
        pass

    assert gen.aclose_called


@pytest.mark.asyncio
async def test_empty_generator():
    request = make_request()
    gen = TrackingGen()

    chunks = [chunk async for chunk in guarded_stream(request, gen)]

    assert chunks == []
    assert gen.aclose_called


@pytest.mark.asyncio
async def test_disconnect_before_first_chunk():
    """If already disconnected before yielding anything, no chunks come through."""
    request = make_request(disconnected_after=0)
    gen = TrackingGen("a", "b", "c")

    chunks = [chunk async for chunk in guarded_stream(request, gen)]

    assert chunks == []
    assert gen.aclose_called
