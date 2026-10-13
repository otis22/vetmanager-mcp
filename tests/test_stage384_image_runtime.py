"""The production/test base image must resolve Uvicorn auto to its native paths."""

import httptools  # noqa: F401 - absence is a failing guard
import uvicorn
import uvloop


def test_uvicorn_auto_uses_uvloop_and_httptools_with_sansio_websocket():
    async def app(scope, receive, send):
        pass

    config = uvicorn.Config(app, loop="auto", http="auto", ws="websockets-sansio")
    config.load()
    loop = config.get_loop_factory()()
    try:
        assert isinstance(loop, uvloop.Loop)
    finally:
        loop.close()
    assert config.http_protocol_class.__name__ == "HttpToolsProtocol"
    assert "SansIO" in config.ws_protocol_class.__name__
