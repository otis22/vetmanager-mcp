from pathlib import Path


def test_post_deploy_mcp_tool_smoke_is_read_only_and_secret_safe() -> None:
    text = (Path(__file__).resolve().parent.parent / "scripts" / "post_deploy_mcp_tool_smoke.py").read_text()
    assert '"initialize"' in text and '"tools/list"' in text and '"tools/call"' in text
    assert "Mcp-Session-Id" in text
    assert '"notifications/initialized"' in text and '"Accept": "application/json, text/event-stream"' in text
    assert '"text/event-stream"' in text and 'line.startswith("data: ")' in text
    assert 'call.get("isError")' in text
    assert "range(1, 11)" in text and "time.sleep(3)" in text
    assert '"get_users"' in text and '"limit": 1' in text
    assert "PROD_SMOKE_BEARER_TOKEN" in text
    assert "print(token" not in text and "print(headers" not in text
    assert "print(response" not in text and "print(payload" not in text


def test_deploy_runs_mcp_tool_smoke_after_remote_deploy() -> None:
    text = (Path(__file__).resolve().parent.parent / ".github/workflows/deploy-prod.yml").read_text()
    assert "Verify public MCP read-only tool" in text
    assert "pip install --disable-pip-version-check httpx" in text
    assert text.index("./scripts/deploy_server.sh") < text.index("post_deploy_mcp_tool_smoke.py")
