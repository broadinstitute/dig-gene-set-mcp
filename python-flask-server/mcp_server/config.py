from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str
    host: str
    port: int
    log_level: str
    bearer_token: str
    remote_search_base_url: str
    db_path: Path
    rate_limit_per_minute: int
    query_timeout_seconds: int
    max_search_results: int
    max_gene_results: int


def load_settings(base_dir: Path) -> Settings:
    db_path = Path(os.getenv("MCP_DB_PATH", str(base_dir / "data" / "genseco_vOriginal.sqlite"))).expanduser()
    token = os.getenv("MCP_BEARER_TOKEN", "change-me")
    return Settings(
        app_name="genseco-mcp-server",
        host=os.getenv("MCP_HOST", "127.0.0.1"),
        port=int(os.getenv("MCP_PORT", "8000")),
        log_level=os.getenv("MCP_LOG_LEVEL", "INFO").upper(),
        bearer_token=token,
        remote_search_base_url=os.getenv(
            "MCP_REMOTE_SEARCH_BASE_URL",
            "http://ec2-3-210-5-42.compute-1.amazonaws.com",
        ).rstrip("/"),
        db_path=db_path,
        rate_limit_per_minute=max(1, int(os.getenv("MCP_RATE_LIMIT_PER_MINUTE", "60"))),
        query_timeout_seconds=max(1, int(os.getenv("MCP_QUERY_TIMEOUT_SECONDS", "20"))),
        max_search_results=max(1, int(os.getenv("MCP_MAX_SEARCH_RESULTS", "25"))),
        max_gene_results=max(1, int(os.getenv("MCP_MAX_GENE_RESULTS", "200"))),
    )
