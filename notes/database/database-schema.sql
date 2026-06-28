--
-- File generated with SQLiteStudio v3.2.1 on Fri May 15 21:22:39 2026
--
-- Text encoding used: System
--
PRAGMA foreign_keys = off;
BEGIN TRANSACTION;

-- Table: author
CREATE TABLE author (
    author_id    INTEGER,
    display_name TEXT    NOT NULL,
    full_name    TEXT    NOT NULL,
    PRIMARY KEY (
        author_id
    )
);


-- Table: collection
CREATE TABLE collection (
    collection_id          INTEGER,
    collection_name        TEXT    UNIQUE
                                   NOT NULL,
    full_name              TEXT    NOT NULL,
    description            TEXT    NOT NULL,
    parent_collection_id   INTEGER,
    gparent_collection_id  INTEGER,
    ggparent_collection_id INTEGER,
    PRIMARY KEY (
        collection_id
    ),
    FOREIGN KEY (
        parent_collection_id
    )
    REFERENCES collection (collection_id),
    FOREIGN KEY (
        gparent_collection_id
    )
    REFERENCES collection (collection_id),
    FOREIGN KEY (
        ggparent_collection_id
    )
    REFERENCES collection (collection_id) 
);


-- Table: external_term
CREATE TABLE external_term (
    term          TEXT UNIQUE
                       NOT NULL,
    external_name TEXT NOT NULL,
    PRIMARY KEY (
        term
    )
);


-- Table: external_term_filtered_by_similarity
CREATE TABLE external_term_filtered_by_similarity (
    gene_set_id INTEGER NOT NULL,
    term        TEXT    NOT NULL,
    FOREIGN KEY (
        gene_set_id
    )
    REFERENCES gene_set (gene_set_id) ON DELETE CASCADE,
    PRIMARY KEY (
        gene_set_id,
        term
    ),
    FOREIGN KEY (
        term
    )
    REFERENCES external_term (term) 
);


-- Table: gene_set
CREATE TABLE gene_set (
    gene_set_id     INTEGER,
    standard_name   TEXT    NOT NULL
                            UNIQUE,
    collection_name TEXT    NOT NULL,
    tags            TEXT,
    license_code    TEXT    NOT NULL,
    PRIMARY KEY (
        gene_set_id
    ),
    FOREIGN KEY (
        license_code
    )
    REFERENCES gene_set_license (license_code),
    FOREIGN KEY (
        collection_name
    )
    REFERENCES collection (collection_name) 
);


-- Table: gene_set_details
CREATE TABLE gene_set_details (
    gene_set_id            INTEGER,
    added_in_genseco_db_id INTEGER,-- NOT NULL, -- can't populate this for now
    description_brief      TEXT,
    description_full       TEXT,
    systematic_name        TEXT    NOT NULL,
    exact_source           TEXT,
    external_details_URL   TEXT,
    source_species_code    TEXT    NOT NULL,
    primary_namespace_id   INTEGER NOT NULL,
    second_namespace_id    INTEGER,
    num_namespaces         INTEGER NOT NULL,
    publication_id         INTEGER,
    GEO_id                 TEXT,
    contributor            TEXT,
    contrib_organization   TEXT,
    changed_in_genseco_db_id INTEGER,
    changed_reason         TEXT,
    FOREIGN KEY (
        added_in_genseco_db_id
    )
    REFERENCES GenSeCoDB (genseco_db_id),
    FOREIGN KEY (
        gene_set_id
    )
    REFERENCES gene_set (gene_set_id) ON DELETE CASCADE,
    PRIMARY KEY (
        gene_set_id
    ),
    FOREIGN KEY (
        changed_in_genseco_db_id
    )
    REFERENCES GenSeCoDB (genseco_db_id),
    FOREIGN KEY (
        primary_namespace_id
    )
    REFERENCES namespace (namespace_id),
    FOREIGN KEY (
        source_species_code
    )
    REFERENCES species (species_code),
    FOREIGN KEY (
        second_namespace_id
    )
    REFERENCES namespace (namespace_id),
    FOREIGN KEY (
        publication_id
    )
    REFERENCES publication (publication_id) 
);


-- Table: provenance
CREATE TABLE provenance (
    gene_set_id       INTEGER,
    provenance_graph  TEXT    NOT NULL,
    geneset_metadata  TEXT    NOT NULL,
    run_summary       TEXT,
    PRIMARY KEY (
        gene_set_id
    ),
    FOREIGN KEY (
        gene_set_id
    )
    REFERENCES gene_set (gene_set_id) ON DELETE CASCADE
);


-- Table: provenance_node
CREATE TABLE provenance_node (
    provenance_node_id INTEGER,
    gene_set_id        INTEGER NOT NULL,
    node_type          TEXT    NOT NULL,
    name               TEXT,
    description        TEXT,
    dcc_url            TEXT,
    drc_url            TEXT,
    additional_properties TEXT NOT NULL,
    PRIMARY KEY (
        provenance_node_id
    ),
    FOREIGN KEY (
        gene_set_id
    )
    REFERENCES gene_set (gene_set_id) ON DELETE CASCADE
);


-- Table: provenance_edge
CREATE TABLE provenance_edge (
    provenance_edge_id INTEGER,
    gene_set_id        INTEGER NOT NULL,
    source_node_id     INTEGER NOT NULL,
    target_node_id     INTEGER NOT NULL,
    label              TEXT,
    description        TEXT,
    additional_properties TEXT,
    PRIMARY KEY (
        provenance_edge_id
    ),
    FOREIGN KEY (
        gene_set_id
    )
    REFERENCES gene_set (gene_set_id) ON DELETE CASCADE,
    FOREIGN KEY (
        source_node_id
    )
    REFERENCES provenance_node (provenance_node_id) ON DELETE CASCADE,
    FOREIGN KEY (
        target_node_id
    )
    REFERENCES provenance_node (provenance_node_id) ON DELETE CASCADE
);


-- Table: gene_set_gene_symbol
CREATE TABLE gene_set_gene_symbol (
    gene_set_id    INTEGER NOT NULL,
    gene_symbol_id INTEGER NOT NULL,
    FOREIGN KEY (
        gene_set_id
    )
    REFERENCES gene_set (gene_set_id) ON DELETE CASCADE,
    PRIMARY KEY (
        gene_set_id,
        gene_symbol_id
    ),
    FOREIGN KEY (
        gene_symbol_id
    )
    REFERENCES gene_symbol (gene_symbol_id) 
);


-- Table: gene_set_license
CREATE TABLE gene_set_license (
    gene_set_license_id INTEGER,
    license_code TEXT    UNIQUE
                         NOT NULL,
    license_name TEXT    NOT NULL,
    license_note TEXT,
    PRIMARY KEY (
        gene_set_license_id
    )
);


-- Table: gene_set_source_member
CREATE TABLE gene_set_source_member (
    gene_set_id      INTEGER NOT NULL,
    source_member_id INTEGER NOT NULL,
    FOREIGN KEY (
        gene_set_id
    )
    REFERENCES gene_set (gene_set_id) ON DELETE CASCADE,
    PRIMARY KEY (
        gene_set_id,
        source_member_id
    ),
    FOREIGN KEY (
        source_member_id
    )
    REFERENCES source_member (source_member_id) 
);


-- Table: gene_symbol
CREATE TABLE gene_symbol (
    gene_symbol_id INTEGER,
    symbol       TEXT    NOT NULL,
    NCBI_id      TEXT,
    namespace_id INTEGER NOT NULL,
    FOREIGN KEY (
        namespace_id
    )
    REFERENCES namespace (namespace_id),
    PRIMARY KEY (
        gene_symbol_id
    )
);


-- Table: GenSeCoDB
CREATE TABLE GenSeCoDB (
    genseco_db_id       INTEGER,
    version_name        TEXT    NOT NULL,
    version_date        TEXT    NOT NULL,
    genseco_db_base_URL TEXT,
    target_species_code TEXT    NOT NULL,
    gene_mapping_info   TEXT,
    FOREIGN KEY (
        target_species_code
    )
    REFERENCES species (species_code),
    PRIMARY KEY (
        genseco_db_id
    )
);


-- Table: namespace
CREATE TABLE namespace (
    namespace_id INTEGER,
    label        TEXT    UNIQUE
                         NOT NULL,
    species_code TEXT    NOT NULL,
    PRIMARY KEY (
        namespace_id
    ),
    FOREIGN KEY (
        species_code
    )
    REFERENCES species (species_code) 
);


-- Table: publication
CREATE TABLE publication (
    publication_id INTEGER,
    title TEXT,
    PMID  TEXT,
    DOI   TEXT,
    URL   TEXT,
    PRIMARY KEY (
        publication_id
    )
);


-- Table: publication_author
CREATE TABLE publication_author (
    author_id      INTEGER NOT NULL,
    publication_id INTEGER NOT NULL,
    author_order   INTEGER NOT NULL,
    FOREIGN KEY (
        publication_id
    )
    REFERENCES publication (publication_id) ON DELETE CASCADE,
    PRIMARY KEY (
        author_id,
        publication_id,
        author_order
    ),
    FOREIGN KEY (
        author_id
    )
    REFERENCES author (author_id) ON DELETE CASCADE
);


-- Table: source_member
CREATE TABLE source_member (
    source_member_id INTEGER,
    source_id      TEXT    NOT NULL,
    gene_symbol_id INTEGER,
    namespace_id   INTEGER NOT NULL,
    FOREIGN KEY (
        namespace_id
    )
    REFERENCES namespace (namespace_id),
    PRIMARY KEY (
        source_member_id
    ),
    FOREIGN KEY (
        gene_symbol_id
    )
    REFERENCES gene_symbol (gene_symbol_id) 
);


-- Table: species
CREATE TABLE species (
    species_id   INTEGER,
    species_code TEXT    UNIQUE
                         NOT NULL,
    species_name TEXT    NOT NULL,
    PRIMARY KEY (
        species_id
    )
);


-- Index: author_display_name
CREATE INDEX author_display_name ON author (
    display_name
);


-- Index: author_full_name
CREATE INDEX author_full_name ON author (
    full_name
);


-- Index: gene_set_index
CREATE INDEX gene_set_index ON gene_set_gene_symbol (
    gene_set_id
);


-- Index: gene_symbol_index
CREATE INDEX gene_symbol_index ON gene_set_gene_symbol (
    gene_symbol_id
);


-- Index: publication_id_index
CREATE INDEX publication_id_index ON publication_author (
    publication_id
);


-- Index: unique_gene_NCBI_id
CREATE UNIQUE INDEX unique_gene_NCBI_id ON gene_symbol (
    NCBI_id,
    namespace_id
);


-- Index: unique_gene_symbol
CREATE UNIQUE INDEX unique_gene_symbol ON gene_symbol (
    symbol,
    namespace_id
);


-- Index: unique_source_symbol
CREATE UNIQUE INDEX unique_source_symbol ON source_member (
    source_id,
    namespace_id
);


-- Index: unique_systematic_name
CREATE UNIQUE INDEX unique_systematic_name ON gene_set_details (
    systematic_name
);


-- Index: version_name_index
CREATE INDEX version_name_index ON GenSeCoDB (
    version_name
);


COMMIT TRANSACTION;
PRAGMA foreign_keys = on;
