"""Stage 385.2a2: a bearer session must use the same upstream slot."""

from pathlib import Path
import re


def test_nginx_mcp_routes_use_authorization_consistent_hash():
    source = (Path(__file__).resolve().parents[1] / "scripts/init_server.sh").read_text()
    upstream = re.search(r"upstream mcp_session_backend \{(.*?)\n\}", source, re.S)
    assert upstream is not None
    assert r"hash \$http_authorization consistent;" in upstream.group(1)
    assert all(f"server 127.0.0.1:{port};" in upstream.group(1) for port in (8000, 8001, 8002))
    route = re.search(r"location /mcp \{(.*?)\n    \}", source, re.S)
    assert route is not None
    assert "proxy_pass http://mcp_session_backend;" in route.group(1)
    assert r"proxy_set_header Authorization \$http_authorization;" in route.group(1)
