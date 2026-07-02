from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from .config import Settings
from .database import Database, parse_json_blob, row_to_dict
from .web_utils import WebRequestError, get_json, post_json

REMOTE_GENE_SET_SEARCH_LIMIT_DEFAULT = 15
REMOTE_GENE_SET_SEARCH_PATH = "/interactive/gene-set/search"
PIGEAN_BASE_URL = "https://cfde-dev.hugeampkpnbi.org"
PIGEAN_GENE_SET_PATH = "/api/bio/query/pigean-gene-set"
PIGEAN_GENE_PATH = "/api/bio/query/pigean-gene"
PIGEAN_MODEL_DEFAULT = "cfde"
PIGEAN_BETA_UNCORRECTED_MINIMUM = 0.1
PIGEAN_COMBINED_MINIMUM = 5


class ToolError(Exception):
    pass


@dataclass
class ResolvedGeneSet:
    gene_set_id: int
    standard_name: str
    collection_name: str
    tags: str | None
    license_code: str


class ToolService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._settings = settings

    def search_gene_sets(
        self,
        query: str,
        organism: str | None = None,
        library: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        cleaned_query = query.strip()
        if not cleaned_query:
            raise ToolError("query is required")

        result_limit = self._bounded_limit(limit)
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT gene_set_id, standard_name, collection_name, tags, license_code
                FROM gene_set
                WHERE standard_name LIKE ?
                  AND (? IS NULL OR collection_name = ?)
                ORDER BY
                    CASE WHEN lower(standard_name) = lower(?) THEN 0 ELSE 1 END,
                    standard_name
                LIMIT ?
                """,
                (f"%{cleaned_query}%", library, library, cleaned_query, result_limit * 3),
            ).fetchall()

            items = []
            for row in rows:
                gene_set = self._attach_metadata_summary(connection, row_to_dict(row) or {})
                if organism and gene_set.get("organism") and gene_set["organism"].lower() != organism.lower():
                    continue
                items.append(gene_set)
                if len(items) >= result_limit:
                    break

        return {
            "query": cleaned_query,
            "organism": organism,
            "library": library,
            "count": len(items),
            "items": items,
        }

    def search_gene_sets_semantic(
        self,
        query: str,
        limit: int | None = None,
    ) -> dict[str, Any]:
        cleaned_query = query.strip()
        if not cleaned_query:
            raise ToolError("query is required")

        outbound_limit = REMOTE_GENE_SET_SEARCH_LIMIT_DEFAULT if limit is None else min(max(1, limit), 100)
        url = f"{self._settings.remote_search_base_url}{REMOTE_GENE_SET_SEARCH_PATH}"
        try:
            response = post_json(
                url=url,
                payload={"query": cleaned_query, "limit": outbound_limit},
                timeout_seconds=self._settings.query_timeout_seconds,
            )
        except WebRequestError as exc:
            raise ToolError(str(exc)) from exc

        items = response.get("items", []) if isinstance(response, dict) else []
        return {
            "query": response.get("query", cleaned_query) if isinstance(response, dict) else cleaned_query,
            "count": len(items),
            "items": [
                {
                    "label": item.get("label"),
                    "description": item.get("description"),
                    "score": item.get("score"),
                }
                for item in items
            ],
        }

    def get_gene_set(
        self,
        gene_set_id: int | None = None,
        standard_name: str | None = None,
        include_genes: bool = True,
        max_genes: int = 200,
    ) -> dict[str, Any]:
        resolved = self._resolve_gene_set(gene_set_id=gene_set_id, standard_name=standard_name)
        bounded_max_genes = min(max(1, max_genes), self._settings.max_gene_results)
        with self._database.connect() as connection:
            payload = self._attach_metadata_summary(connection, resolved.__dict__.copy(), include_details=True)
            if include_genes:
                gene_rows = connection.execute(
                    """
                    SELECT gs.symbol
                    FROM gene_set_gene_symbol gsgs
                    JOIN gene_symbol gs ON gs.gene_symbol_id = gsgs.gene_symbol_id
                    WHERE gsgs.gene_set_id = ?
                    ORDER BY gs.symbol
                    LIMIT ?
                    """,
                    (resolved.gene_set_id, bounded_max_genes),
                ).fetchall()
                total_gene_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM gene_set_gene_symbol WHERE gene_set_id = ?",
                    (resolved.gene_set_id,),
                ).fetchone()
                payload["genes"] = [row["symbol"] for row in gene_rows]
                payload["gene_count"] = total_gene_count["count"] if total_gene_count else len(payload["genes"])
                payload["genes_truncated"] = payload["gene_count"] > len(payload["genes"])
            return payload

    def get_pigean_gene_set(
        self,
        gene_set_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_gene_set_id = (gene_set_id or "").strip()
        if not normalized_gene_set_id:
            raise ToolError("gene_set_id is required")
        query_value = f"{normalized_gene_set_id},{PIGEAN_MODEL_DEFAULT}"
        url = f"{PIGEAN_BASE_URL}{PIGEAN_GENE_SET_PATH}?q={quote(query_value, safe=',')}"
        try:
            response = get_json(url=url, timeout_seconds=self._settings.query_timeout_seconds)
        except WebRequestError as exc:
            return {
                "gene_set_id": normalized_gene_set_id,
                "model": PIGEAN_MODEL_DEFAULT,
                "beta_uncorrected_minimum": PIGEAN_BETA_UNCORRECTED_MINIMUM,
                "count": 0,
                "items": [],
                "warning": str(exc),
            }

        data = response.get("data", []) if isinstance(response, dict) else []
        filtered_items = []
        for item in data:
            beta_uncorrected = item.get("beta_uncorrected")
            if not isinstance(beta_uncorrected, (int, float)) or beta_uncorrected < PIGEAN_BETA_UNCORRECTED_MINIMUM:
                continue
            filtered_items.append(
                {
                    "phenotype": item.get("phenotype"),
                    "beta": item.get("beta"),
                    "beta_uncorrected": beta_uncorrected,
                    "rs_score": item.get("rs_score"),
                }
            )

        return {
            "gene_set_id": normalized_gene_set_id,
            "model": PIGEAN_MODEL_DEFAULT,
            "beta_uncorrected_minimum": PIGEAN_BETA_UNCORRECTED_MINIMUM,
            "count": len(filtered_items),
            "items": filtered_items,
        }

    def get_pigean_gene(
        self,
        gene: str | None = None,
    ) -> dict[str, Any]:
        normalized_gene = (gene or "").strip()
        if not normalized_gene:
            raise ToolError("gene is required")
        query_value = f"{normalized_gene},{PIGEAN_MODEL_DEFAULT}"
        url = f"{PIGEAN_BASE_URL}{PIGEAN_GENE_PATH}?q={quote(query_value, safe=',')}"
        try:
            response = get_json(url=url, timeout_seconds=self._settings.query_timeout_seconds)
        except WebRequestError as exc:
            return {
                "gene": normalized_gene,
                "model": PIGEAN_MODEL_DEFAULT,
                "combined_minimum": PIGEAN_COMBINED_MINIMUM,
                "count": 0,
                "items": [],
                "warning": str(exc),
            }

        data = response.get("data", []) if isinstance(response, dict) else []
        filtered_items = []
        for item in data:
            combined = item.get("combined")
            if not isinstance(combined, (int, float)) or combined < PIGEAN_COMBINED_MINIMUM:
                continue
            filtered_items.append(
                {
                    "phenotype": item.get("phenotype"),
                    "combined": combined,
                    "huge_score": item.get("huge_score"),
                    "label": item.get("label"),
                }
            )

        return {
            "gene": normalized_gene,
            "model": PIGEAN_MODEL_DEFAULT,
            "combined_minimum": PIGEAN_COMBINED_MINIMUM,
            "count": len(filtered_items),
            "items": filtered_items,
        }

    def get_provenance(
        self,
        gene_set_id: int | None = None,
        standard_name: str | None = None,
    ) -> dict[str, Any]:
        resolved = self._resolve_gene_set(gene_set_id=gene_set_id, standard_name=standard_name)
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT provenance_graph, geneset_metadata FROM provenance WHERE gene_set_id = ?",
                (resolved.gene_set_id,),
            ).fetchone()
            if row is None:
                raise ToolError("No provenance found for the requested gene set")

            parsed_graph = parse_json_blob(row["provenance_graph"])
            parsed_metadata = parse_json_blob(row["geneset_metadata"])
            return {
                "gene_set_id": resolved.gene_set_id,
                "standard_name": resolved.standard_name,
                "provenance_graph": self._compact_provenance_graph(parsed_graph),
                "geneset_metadata": self._compact_geneset_metadata(parsed_metadata),
            }

    def find_gene_sets_by_gene(
        self,
        genes: list[str],
        organism: str | None = None,
        library: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        cleaned_genes = sorted({gene.strip().upper() for gene in genes if gene and gene.strip()})
        if not cleaned_genes:
            raise ToolError("genes must contain at least one symbol")

        result_limit = self._bounded_limit(limit)
        placeholders = ",".join("?" for _ in cleaned_genes)
        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    g.gene_set_id,
                    g.standard_name,
                    g.collection_name,
                    g.license_code,
                    COUNT(DISTINCT gs.symbol) AS overlap_count,
                    GROUP_CONCAT(DISTINCT gs.symbol) AS matched_symbols
                FROM gene_set g
                JOIN gene_set_gene_symbol gsgs ON gsgs.gene_set_id = g.gene_set_id
                JOIN gene_symbol gs ON gs.gene_symbol_id = gsgs.gene_symbol_id
                WHERE UPPER(gs.symbol) IN ({placeholders})
                  AND (? IS NULL OR g.collection_name = ?)
                GROUP BY g.gene_set_id, g.standard_name, g.collection_name, g.license_code
                ORDER BY overlap_count DESC, g.standard_name
                LIMIT ?
                """,
                (*cleaned_genes, library, library, result_limit * 3),
            ).fetchall()

            items = []
            for row in rows:
                item = self._attach_metadata_summary(connection, row_to_dict(row) or {})
                if organism and item.get("organism") and item["organism"].lower() != organism.lower():
                    continue
                matches = sorted((item.get("matched_symbols") or "").split(",")) if item.get("matched_symbols") else []
                item["matched_symbols"] = matches
                item["query_gene_count"] = len(cleaned_genes)
                item["overlap_fraction"] = round(item["overlap_count"] / len(cleaned_genes), 4)
                items.append(item)
                if len(items) >= result_limit:
                    break

        return {
            "genes": cleaned_genes,
            "organism": organism,
            "library": library,
            "count": len(items),
            "items": items,
        }

    def get_graph_neighborhood(
        self,
        node_type: str,
        node_id: str,
        max_nodes: int = 25,
        max_edges: int = 40,
        include_genes: bool = False,
    ) -> dict[str, Any]:
        normalized_type = node_type.strip().lower()
        bounded_nodes = min(max(1, max_nodes), 50)
        bounded_edges = min(max(1, max_edges), 100)
        if not node_id.strip():
            raise ToolError("node_id is required")

        if normalized_type in {"gene_set", "geneset", "provenance"}:
            gene_set_id = int(node_id) if node_id.isdigit() else None
            standard_name = None if gene_set_id is not None else node_id
            resolved = self._resolve_gene_set(gene_set_id=gene_set_id, standard_name=standard_name)
            return self._gene_set_neighborhood(
                resolved=resolved,
                max_nodes=bounded_nodes,
                max_edges=bounded_edges,
                include_genes=include_genes,
            )

        if normalized_type == "gene":
            return self._gene_neighborhood(node_id=node_id, limit=bounded_nodes)

        if normalized_type in {"dataset", "tissue", "contrast", "trait", "disease", "pipeline"}:
            return self._metadata_neighborhood(
                node_type=normalized_type,
                node_id=node_id,
                limit=bounded_nodes,
            )

        raise ToolError("Unsupported node_type")

    def _attach_metadata_summary(
        self,
        connection: sqlite3.Connection,
        payload: dict[str, Any],
        include_details: bool = False,
    ) -> dict[str, Any]:
        gene_set_id = payload["gene_set_id"]
        details = self._fetch_gene_set_details(connection, gene_set_id)
        if details:
            payload["organism"] = details.get("source_species_code")
            payload["systematic_name"] = details.get("systematic_name")
            payload["description_brief"] = details.get("description_brief")
            payload["external_details_url"] = details.get("external_details_URL")
            if include_details:
                payload["details"] = details
        else:
            metadata = self._fetch_provenance_metadata(connection, gene_set_id)
            gene_set_meta = metadata.get("gene_set", {}) if isinstance(metadata, dict) else {}
            payload["organism"] = gene_set_meta.get("organism")
            payload["description_brief"] = gene_set_meta.get("description")
            segments = payload.get("standard_name", "").split("__")
            if len(segments) >= 3:
                payload["contrast"] = segments[0]
                payload["tissue"] = segments[1]
                payload["direction"] = segments[2]
            payload["metadata_summary"] = self._compact_geneset_metadata(metadata)
        return payload

    def _fetch_gene_set_details(self, connection: sqlite3.Connection, gene_set_id: int) -> dict[str, Any]:
        if not self._database.table_exists(connection, "gene_set_details"):
            return {}
        row = connection.execute(
            "SELECT * FROM gene_set_details WHERE gene_set_id = ?",
            (gene_set_id,),
        ).fetchone()
        return row_to_dict(row) or {}

    def _fetch_provenance_metadata(self, connection: sqlite3.Connection, gene_set_id: int) -> dict[str, Any]:
        row = connection.execute(
            "SELECT geneset_metadata FROM provenance WHERE gene_set_id = ?",
            (gene_set_id,),
        ).fetchone()
        parsed = parse_json_blob(row["geneset_metadata"] if row else None)
        return parsed if isinstance(parsed, dict) else {}

    def _resolve_gene_set(
        self,
        gene_set_id: int | None = None,
        standard_name: str | None = None,
    ) -> ResolvedGeneSet:
        if gene_set_id is None and not standard_name:
            raise ToolError("Provide gene_set_id or standard_name")

        with self._database.connect() as connection:
            if gene_set_id is not None:
                row = connection.execute(
                    """
                    SELECT gene_set_id, standard_name, collection_name, tags, license_code
                    FROM gene_set
                    WHERE gene_set_id = ?
                    """,
                    (gene_set_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT gene_set_id, standard_name, collection_name, tags, license_code
                    FROM gene_set
                    WHERE lower(standard_name) = lower(?)
                    """,
                    (standard_name,),
                ).fetchone()

        if row is None:
            raise ToolError("Gene set not found")
        return ResolvedGeneSet(**row_to_dict(row))

    def _compact_provenance_graph(self, graph: Any) -> dict[str, Any]:
        if not isinstance(graph, dict) or not graph:
            return {"raw": graph}
        focus_key, focus_graph = next(iter(graph.items()))
        nodes = focus_graph.get("nodes", [])[:25] if isinstance(focus_graph, dict) else []
        edges = focus_graph.get("edges", [])[:40] if isinstance(focus_graph, dict) else []
        return {
            "focus_id": focus_key,
            "node_count": len(focus_graph.get("nodes", [])) if isinstance(focus_graph, dict) else 0,
            "edge_count": len(focus_graph.get("edges", [])) if isinstance(focus_graph, dict) else 0,
            "nodes": [self._trim_node(node) for node in nodes],
            "edges": [self._trim_edge(edge) for edge in edges],
            "truncated": (
                len(focus_graph.get("nodes", [])) > len(nodes)
                or len(focus_graph.get("edges", [])) > len(edges)
            ) if isinstance(focus_graph, dict) else False,
        }

    def _compact_geneset_metadata(self, metadata: Any) -> dict[str, Any]:
        if not isinstance(metadata, dict):
            return {"raw": metadata}
        gene_set_meta = metadata.get("gene_set", {})
        summary = metadata.get("summary", {})
        converter = metadata.get("converter", {})
        lineage = metadata.get("lineage", {})
        return {
            "standard_name": metadata.get("standard_name"),
            "created_at": metadata.get("created_at"),
            "gene_set": {
                "name": gene_set_meta.get("name"),
                "description": gene_set_meta.get("description"),
                "organism": gene_set_meta.get("organism"),
                "genome_build": gene_set_meta.get("genome_build"),
                "n_genes": gene_set_meta.get("n_genes"),
                "data_type": gene_set_meta.get("data_type"),
                "assay": gene_set_meta.get("assay"),
            },
            "summary": {
                "n_input_features": summary.get("n_input_features"),
                "n_genes": summary.get("n_genes"),
                "n_rows_filtered_by_thresholds": summary.get("n_rows_filtered_by_thresholds"),
                "warnings": summary.get("warnings", [])[:3],
            },
            "converter": {
                "name": converter.get("name"),
                "version": converter.get("version"),
                "repo_url": converter.get("code", {}).get("repo_url") if isinstance(converter.get("code"), dict) else None,
            },
            "lineage": {
                "node_count": len(lineage.get("nodes", [])) if isinstance(lineage, dict) else 0,
                "edge_count": len(lineage.get("edges", [])) if isinstance(lineage, dict) else 0,
            },
        }

    def _gene_set_neighborhood(
        self,
        resolved: ResolvedGeneSet,
        max_nodes: int,
        max_edges: int,
        include_genes: bool,
    ) -> dict[str, Any]:
        with self._database.connect() as connection:
            provenance_row = connection.execute(
                "SELECT provenance_graph, geneset_metadata FROM provenance WHERE gene_set_id = ?",
                (resolved.gene_set_id,),
            ).fetchone()
            graph = parse_json_blob(provenance_row["provenance_graph"] if provenance_row else None)
            metadata = parse_json_blob(provenance_row["geneset_metadata"] if provenance_row else None)
            compact_graph = self._compact_provenance_graph(graph)
            nodes = compact_graph.get("nodes", [])[:max_nodes]
            edges = compact_graph.get("edges", [])[:max_edges]
            if include_genes:
                gene_rows = connection.execute(
                    """
                    SELECT gs.symbol
                    FROM gene_set_gene_symbol gsgs
                    JOIN gene_symbol gs ON gs.gene_symbol_id = gsgs.gene_symbol_id
                    WHERE gsgs.gene_set_id = ?
                    ORDER BY gs.symbol
                    LIMIT ?
                    """,
                    (resolved.gene_set_id, min(max_nodes, self._settings.max_gene_results)),
                ).fetchall()
                gene_nodes = [{"id": f"gene:{row['symbol']}", "type": "Gene", "name": row["symbol"]} for row in gene_rows]
                gene_edges = [
                    {"source": resolved.standard_name, "target": row["symbol"], "label": "contains_gene"}
                    for row in gene_rows
                ]
                nodes.extend(gene_nodes[: max(0, max_nodes - len(nodes))])
                edges.extend(gene_edges[: max(0, max_edges - len(edges))])

        return {
            "node_type": "gene_set",
            "node_id": resolved.standard_name,
            "gene_set_id": resolved.gene_set_id,
            "metadata": self._compact_geneset_metadata(metadata),
            "nodes": nodes[:max_nodes],
            "edges": edges[:max_edges],
            "truncated": compact_graph.get("truncated", False),
        }

    def _gene_neighborhood(self, node_id: str, limit: int) -> dict[str, Any]:
        gene_symbol = node_id.strip().upper()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    g.gene_set_id,
                    g.standard_name,
                    g.collection_name,
                    g.license_code
                FROM gene_symbol gs
                JOIN gene_set_gene_symbol gsgs ON gsgs.gene_symbol_id = gs.gene_symbol_id
                JOIN gene_set g ON g.gene_set_id = gsgs.gene_set_id
                WHERE UPPER(gs.symbol) = ?
                ORDER BY g.standard_name
                LIMIT ?
                """,
                (gene_symbol, limit),
            ).fetchall()

            items = [self._attach_metadata_summary(connection, row_to_dict(row) or {}) for row in rows]

        return {
            "node_type": "gene",
            "node_id": gene_symbol,
            "nodes": [{"id": f"gene_set:{item['gene_set_id']}", "type": "GeneSet", "name": item["standard_name"]} for item in items],
            "edges": [{"source": gene_symbol, "target": item["standard_name"], "label": "member_of"} for item in items],
            "count": len(items),
            "items": items,
        }

    def _metadata_neighborhood(self, node_type: str, node_id: str, limit: int) -> dict[str, Any]:
        search_term = node_id.strip().lower()
        with self._database.connect() as connection:
            base_rows = connection.execute(
                "SELECT gene_set_id, standard_name, collection_name, tags, license_code FROM gene_set ORDER BY standard_name"
            ).fetchall()
            matches = []
            for row in base_rows:
                item = self._attach_metadata_summary(connection, row_to_dict(row) or {})
                tokens = {
                    "dataset": [
                        str(item.get("collection_name", "")),
                        str(item.get("metadata_summary", {}).get("converter", {}).get("repo_url", "")),
                    ],
                    "tissue": [
                        str(item.get("tissue", "")),
                        item.get("standard_name", "").split("__")[1]
                        if len(item.get("standard_name", "").split("__")) >= 2
                        else "",
                    ],
                    "contrast": [str(item.get("contrast", ""))],
                    "pipeline": [
                        str(item.get("metadata_summary", {}).get("converter", {}).get("name", "")),
                        str(item.get("metadata_summary", {}).get("converter", {}).get("repo_url", "")),
                    ],
                    "trait": [str(item.get("tags", "")), item.get("standard_name", "")],
                    "disease": [str(item.get("tags", "")), item.get("standard_name", "")],
                }
                haystack = " ".join(tokens.get(node_type, [])).lower()
                if search_term in haystack:
                    matches.append(item)
                if len(matches) >= limit:
                    break

        return {
            "node_type": node_type,
            "node_id": node_id,
            "count": len(matches),
            "nodes": [{"id": f"gene_set:{item['gene_set_id']}", "type": "GeneSet", "name": item["standard_name"]} for item in matches],
            "edges": [{"source": node_id, "target": item["standard_name"], "label": f"related_{node_type}"} for item in matches],
            "items": matches,
        }

    def _trim_node(self, node: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": node.get("id"),
            "type": node.get("type"),
            "name": node.get("name"),
            "description": node.get("description"),
            "dcc_url": node.get("dcc_url"),
            "drc_url": node.get("drc_url"),
        }

    def _trim_edge(self, edge: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": edge.get("id"),
            "source": edge.get("source"),
            "target": edge.get("target"),
            "label": edge.get("label"),
            "description": edge.get("description"),
        }

    def _bounded_limit(self, requested_limit: int | None) -> int:
        if requested_limit is None:
            return self._settings.max_search_results
        return min(max(1, requested_limit), self._settings.max_search_results)


TOOL_DEFINITIONS = [
    {
        "name": "search_gene_sets",
        "description": "Search gene sets by standard_name with optional organism and library filters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "organism": {"type": "string"},
                "library": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_gene_sets_semantic",
        "description": "Proxy semantic gene set search to the configured remote service and return label, description, and score.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_gene_set",
        "description": "Retrieve a gene set by gene_set_id or standard_name, optionally including genes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "gene_set_id": {"type": "integer"},
                "standard_name": {"type": "string"},
                "include_genes": {"type": "boolean"},
                "max_genes": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_pigean_gene_set",
        "description": "Fetch Pigean phenotype associations for a gene set id and return phenotype, beta, beta_uncorrected, and rs_score.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "gene_set_id": {"type": "string"},
            },
            "required": ["gene_set_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_pigean_gene",
        "description": "Fetch Pigean phenotype associations for a gene and return phenotype, combined, huge_score, and label.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "gene": {"type": "string"},
            },
            "required": ["gene"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_provenance",
        "description": "Return compacted provenance_graph and geneset_metadata for a gene set.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "gene_set_id": {"type": "integer"},
                "standard_name": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "find_gene_sets_by_gene",
        "description": "Find gene sets that overlap a provided list of gene symbols.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "genes": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "organism": {"type": "string"},
                "library": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
            },
            "required": ["genes"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_graph_neighborhood",
        "description": "Return a bounded neighborhood around a gene set, gene, dataset, tissue, contrast, trait, disease, provenance, or pipeline node.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_type": {"type": "string"},
                "node_id": {"type": "string"},
                "max_nodes": {"type": "integer", "minimum": 1, "maximum": 50},
                "max_edges": {"type": "integer", "minimum": 1, "maximum": 100},
                "include_genes": {"type": "boolean"},
            },
            "required": ["node_type", "node_id"],
            "additionalProperties": False,
        },
    },
]


def call_tool(service: ToolService, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    handlers = {
        "search_gene_sets": service.search_gene_sets,
        "search_gene_sets_semantic": service.search_gene_sets_semantic,
        "get_gene_set": service.get_gene_set,
        "get_pigean_gene_set": service.get_pigean_gene_set,
        "get_pigean_gene": service.get_pigean_gene,
        "get_provenance": service.get_provenance,
        "find_gene_sets_by_gene": service.find_gene_sets_by_gene,
        "get_graph_neighborhood": service.get_graph_neighborhood,
    }
    if name not in handlers:
        raise ToolError(f"Unknown tool: {name}")
    return handlers[name](**arguments)
