# GenSeCo Flask MCP Server

## Test routes

All `/tools/...` routes require:

`Authorization: Bearer <token>`

## Startup

```bash
cd python-flask-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
export $(grep -v '^#' .env | xargs)
python app.py
```

Important environment values:

- `MCP_BEARER_TOKEN`
- `MCP_DB_PATH`
- `MCP_HOST`
- `MCP_PORT`
- `MCP_LOG_LEVEL`
- `MCP_REMOTE_SEARCH_BASE_URL`
- `MCP_RATE_LIMIT_PER_MINUTE`
- `MCP_QUERY_TIMEOUT_SECONDS`
- `MCP_MAX_SEARCH_RESULTS`
- `MCP_MAX_GENE_RESULTS`

Examples:

- `GET /healthz`
- `GET /mcp`
- `GET /tools/list`
- `GET /tools/search_gene_sets?query=whole_blood&limit=3`
- `GET /tools/search_gene_sets_semantic?query=insulin%20secretion%20in%20beta%20cells`
- `GET /tools/get_gene_set?gene_set_id=1&include_genes=true&max_genes=10`
- `GET /tools/get_pigean_gene_set?gene_set_id=WP_LEPTIN_INSULIN_SIGNALING_OVERLAP`
- `GET /tools/get_pigean_gene?gene=PPARG`
- `GET /tools/get_gene_set?standard_name=AC10__whole_blood__pos`
- `GET /tools/get_provenance?gene_set_id=1`
- `GET /tools/find_gene_sets_by_gene?genes=CXCL8,ALB&limit=5`
- `GET /tools/find_gene_sets_by_gene?gene=CXCL8&gene=ALB&limit=5`
- `GET /tools/get_graph_neighborhood?node_type=gene&node_id=CXCL8&max_nodes=5`
- `GET /tools/get_graph_neighborhood?node_type=gene_set&node_id=1&include_genes=true`

Curl test for the Pigean wrapper:

```bash
curl \
  -H "Authorization: Bearer change-me" \
  "http://127.0.0.1:8000/tools/get_pigean_gene_set?gene_set_id=WP_LEPTIN_INSULIN_SIGNALING_OVERLAP"
```

Curl test for the Pigean gene wrapper:

```bash
curl \
  -H "Authorization: Bearer change-me" \
  "http://127.0.0.1:8000/tools/get_pigean_gene?gene=PPARG"
```
