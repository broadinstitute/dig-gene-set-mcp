# GenSeCo Flask MCP Server

## Test routes

All `/tools/...` routes require:

`Authorization: Bearer <token>`

Examples:

- `GET /healthz`
- `GET /mcp`
- `GET /tools/search_gene_sets?query=whole_blood&limit=3`
- `GET /tools/get_gene_set?gene_set_id=1&include_genes=true&max_genes=10`
- `GET /tools/get_gene_set?standard_name=AC10__whole_blood__pos`
- `GET /tools/get_provenance?gene_set_id=1`
- `GET /tools/find_gene_sets_by_gene?genes=CXCL8,ALB&limit=5`
- `GET /tools/find_gene_sets_by_gene?gene=CXCL8&gene=ALB&limit=5`
- `GET /tools/get_graph_neighborhood?node_type=gene&node_id=CXCL8&max_nodes=5`
- `GET /tools/get_graph_neighborhood?node_type=gene_set&node_id=1&include_genes=true`
