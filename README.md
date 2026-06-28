# GenSeCo Flask MCP Server

This directory contains a read-only Flask-based MCP server backed by the SQLite database in `data/genseco_vOriginal.sqlite`.

## Features

- Streamable HTTP MCP endpoint at `/mcp`
- Bearer token authentication
- In-memory rate limiting
- Read-only SQLite access with query-only mode
- Bounded result payloads for all tools
- Request logging

## Tools

- `search_gene_sets(query, organism?, library?, limit?)`
- `get_gene_set(gene_set_id?, standard_name?, include_genes=true, max_genes=200)`
- `get_provenance(gene_set_id?, standard_name?)`
- `find_gene_sets_by_gene(genes, organism?, library?, limit?)`
- `get_graph_neighborhood(node_type, node_id, max_nodes=25, max_edges=40, include_genes=false)`

## Run

1. Create an environment and install dependencies:

```bash
cd python-flask-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Configure the server:

```bash
cp .env.example .env
```

3. Start it:

```bash
export $(grep -v '^#' .env | xargs)
python app.py
```

## MCP notes

- `POST /mcp` accepts JSON-RPC requests for `initialize`, `tools/list`, and `tools/call`.
- `GET /mcp` returns a simple server-sent event so MCP clients expecting streamable HTTP can attach to the endpoint.
- If the request includes `Accept: text/event-stream` or `?stream=1`, the `POST /mcp` response is returned as SSE.
