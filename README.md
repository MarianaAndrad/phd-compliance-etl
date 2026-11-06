# ETL 4 Security Compliance

**A deterministic ETL pipeline that turns cybersecurity standards and frameworks into structured, queryable control catalogs.**

Compliance ETL extracts the controls of normative documents (ISO/IEC and NIST standards and frameworks, distributed as PDF) together with their hierarchy, and maps them onto a common data model (CDM) inspired by the [NIST OSCAL](https://pages.nist.gov/OSCAL/) Catalog model. The resulting catalogs and controls are stored in MongoDB and can optionally be indexed in Elasticsearch for keyword, semantic, and hybrid search.

This repository accompanies the paper *A Deterministic ETL Pipeline for Normative CDM Extraction* (see [Citation](#citation)).

---

## Why deterministic?

Compliance decisions depend on the exact wording of each requirement, so an extraction step that omits, rewrites, or invents content is not acceptable. Compliance ETL therefore:

- **Produces data only through explicit rules.** The document structure is rebuilt from low-level PDF primitives (text blocks, font sizes, and coordinates) with [PyMuPDF](https://github.com/pymupdf/PyMuPDF), and a rule-based state machine maps it onto the CDM. Running the pipeline twice on the same document and configuration yields identical output.
- **Keeps every control traceable.** Each control has its official reference code, a unique slug, and a link to its parent, so the full hierarchy of the document is preserved.
- **Uses an LLM only to review, never to write.** An optional validation step asks a local LLM judge (through [Ollama](https://ollama.com/)) whether each extracted control is faithful to its source text. The judge flags potential issues for human review and never modifies the data.

## Pipeline

```
 PDF ──► extract ──► transform ──► validate ──► load ──► index
          │           │             │            │         │
          ▼           ▼             ▼            ▼         ▼
       01-markdown  02-cdm-      03-validation  MongoDB  Elasticsearch
       (.md)        instances    (.json report)          (BM25 + vectors)
                    (.json)
```

| Step | Module | What it does |
|------|--------|--------------|
| **Extract** | `extract_compoment.py` | Removes configured phrases and page margins (watermarks, headers, footers), then rebuilds the text block by block with PyMuPDF. Headings are detected from font size and layout, blocks split across pages or columns are merged, and tables are converted to Markdown. Writes `01-markdown/<name>.md` with the document metadata as front matter. |
| **Transform** | `transform_compoment.py` | A deterministic, regex-driven state machine walks the Markdown between the framework's start and end markers, detects control headings and sections (description, purpose, guidance, other information), and builds the parent/child hierarchy from the reference codes. Writes `02-cdm-instances/<name>.json`. |
| **Validate** *(optional)* | `validation_compoment.py` | Locates the source span of each control in the Markdown, checks `slug` and `parent_slug` deterministically, and asks the LLM judge (structured output, temperature 0) to look for hallucinated, missing, or misplaced content. Writes per-control verdicts (`pass` / `fail` / `error`) and a summary to `03-validation/<name>.json`. |
| **Load** | `load_compoment.py` | Upserts the catalog (keyed by `metadata.name`) and its controls (keyed by `slug`) into MongoDB, so re-runs update entries instead of duplicating them. Skipped if MongoDB is unreachable. |
| **Index** *(optional)* | `indexer.py` | Indexes the controls in Elasticsearch with an English analyzer on `title` and `description` and a 384-dimension `description_embedding` (`all-MiniLM-L6-v2`). Supports BM25, kNN, and hybrid retrieval through reciprocal rank fusion. |

Each step reads the previous step's output from `data-output/`, so any step can be re-run on its own.

## Supported documents

Parsers are defined per framework in `G_FRAMEWORKS_SEQUENCE_STATE_CONDITIONS` (`src/components/transform_compoment.py`).

| Key | Document | Controls extracted¹ |
|-----|----------|--------------------:|
| `iso27001` | ISO/IEC 27001:2022 | 41 |
| `iso27002` | ISO/IEC 27002:2022 | 97 |
| `iso27005` | ISO/IEC 27005:2022 | 56 |
| `nistcsf` | NIST Cybersecurity Framework 2.0 | 134 |
| `nistsp800-53r5` | NIST SP 800-53 Rev. 5 | 1209 |

¹ Counts reported in the paper. Grouping units (ISO/IEC 27002 themes, NIST CSF functions and categories, NIST SP 800-53 families) are represented as parent controls.

> **Licensed documents.** ISO/IEC standards are copyrighted and are **not** included in this repository. Obtain them from ISO or your national standards body and place them in `src/data/`. The Markdown, CDM, and validation files derived from licensed documents should not be redistributed either.

## Quick start

**Requirements:** Python 3.13 and [uv](https://docs.astral.sh/uv/), Docker with Docker Compose (for MongoDB and Elasticsearch), and an [Ollama](https://ollama.com/) server if you want to run the validation step.

```bash
# 1. Start MongoDB, Mongo Express, Elasticsearch and Kibana
cd docker
cp .env.example .env          # set your own passwords
docker compose up -d

# 2. Install the Python dependencies
cd ../src
uv sync

# 3. Configure the application
cp .env.example .env          # credentials must match docker/.env
#    then create metadata.json (see below) and put the PDFs in src/data/

# 4. Pull the judge model (only needed for --validate)
ollama pull qwen3.5:4b

# 5. Run the whole pipeline
uv run main.py
```

| Service | URL | Login |
|---------|-----|-------|
| MongoDB | `localhost:27017` | app user created by `docker/mongodb.js` |
| Mongo Express | http://localhost:8081 | `DB_MONGO_USERNAME` / `DB_MONGO_PASSWORD` |
| Elasticsearch | http://localhost:9200 | `elastic` / `ES_PASSWORD` (basic auth, no TLS) |
| Kibana | http://localhost:5601 | `elastic` / `ES_PASSWORD` |

## Usage

Run from `src/`:

```bash
uv run main.py              # run every step (same as --all)
uv run main.py --extract    # run a single step
```

Available flags: `--all`, `--extract`, `--transform`, `--validate`, `--load`, `--index`. PDFs that do not match any entry in `metadata.json` are skipped.

## Configuration

### Environment variables (`src/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_BASE_URL` | `http://localhost:8000/` | Ollama server URL (Ollama listens on `http://localhost:11434` by default) |
| `LLM_MODEL` | `qwen3.5:4b` | Model used as the validation judge |
| `MONGO_HOST` / `MONGO_PORT` | `localhost` / `27017` | MongoDB location |
| `DB_MONGO_USERNAME` / `DB_MONGO_PASSWORD` | — | App user created by `docker/mongodb.js` |
| `DB_MONGO_NAME` | `test` | Database name |
| `DATABASE_URI` | built from the values above | Overrides the MongoDB connection string |
| `DB_MONGO_CATALOG_COLLECTION` | `catalogs` | Collection for catalogs |
| `DB_MONGO_CONTROL_COLLECTION` | `controls` | Collection for controls |
| `ES_BASE_URL` | `http://localhost:9200` | Elasticsearch URL |
| `ES_USERNAME` / `ES_PASSWORD` | — | Elasticsearch credentials |

### Document metadata (`src/metadata.json`)

`metadata.json` tells the pipeline which framework each PDF belongs to and how to clean it. It is gitignored because redaction phrases may contain licence text. Each top-level key is a framework:

```json
{
  "iso27002": {
    "details": {
      "type": "standard",
      "name": "iso27002",
      "publisher": "ISO/IEC"
    },
    "file_props": {
      "keywords": ["iso", "iec", "27002"],
      "redact_phrases": ["© ISO/IEC 2022 – All rights reserved"],
      "redact_margins": {
        "top_y_end_percent": 0.05,
        "bottom_y_start_percent": 0.965
      }
    }
  }
}
```

| Field | Description |
|-------|-------------|
| `details.name` | Must match a parser key in `transform_compoment.py` |
| `details.type` | `standard`, `framework`, or `directive` |
| `file_props.keywords` | A PDF matches this entry when its file name contains every keyword (case-insensitive) |
| `file_props.redact_phrases` | Text removed from every page before extraction, such as watermarks and copyright lines |
| `file_props.redact_margins` | Page bands removed as fractions of the page size (`top_y_end_percent`, `bottom_y_start_percent`, `left_x_end_percent`, `right_x_start_percent`), used to strip headers and footers |

## Data model

The CDM is defined with Pydantic in `src/schemas/` and keeps the subset of the OSCAL Catalog model needed to represent normative documents. The transform step writes one catalog and a flat list of controls (`controls_list`); the hierarchy is given by `parent_slug`.

**Catalog** (one per document)

| Field | Description | Closest OSCAL construct |
|-------|-------------|-------------------------|
| `uuid` | Catalog identifier | `uuid` |
| `metadata` | `type`, `name`, `version`, `language`, `published`, `last-modified`, `publisher`, `description` | `metadata` |

**Control** (one per control, clause, or grouping unit)

| Field | Description | Closest OSCAL construct |
|-------|-------------|-------------------------|
| `catalog_uuid` | Owning catalog | implicit (containment) |
| `ref_code` | Official code, e.g. `8.13`, `AC-2`, `GV.OC-01` | `prop` (label) |
| `title` | Control name | `title` |
| `slug` | Unique identifier, e.g. `8.13-information-backup` | `id` |
| `parent_slug` | Parent control's slug (`null` at the top level) | implicit (nesting) |
| `category` | Usually the title of the root parent | `prop` or `group` |
| `description` | Normative statement | `part` (statement) |
| `purpose` | Purpose of the control | `part` (custom name) |
| `guidance` | Implementation guidance | `part` (guidance) |
| `other_information` | Supplementary information | `part` (custom name) |
| `means_of_verifiction` | Ways to audit the control *(not extracted yet)* | `part` (assessment-method) |
| `attributes` | Tag-like key → list of values | `props` |
| `references`, `citers` | Cross-references *(not extracted yet)* | `links` |

See [`src/schemas/example.json`](src/schemas/example.json) for an example.

## Project structure

```
compliance-etl/
├── docker/                          # MongoDB, Mongo Express, Elasticsearch, Kibana
│   ├── docker-compose.yaml
│   ├── .env.example
│   ├── mongodb.js                   # creates the app user and collections on first start
│   └── kibana.yml
└── src/
    ├── main.py                      # pipeline entry point
    ├── metadata.json                # per-framework settings (not committed)
    ├── core/config.py               # settings loaded from .env
    ├── dependencies/
    │   ├── database.py              # MongoDB and Elasticsearch clients
    │   └── llm.py                   # Ollama chat model used by the judge
    ├── components/
    │   ├── extract_compoment.py     # PDF → Markdown (PyMuPDF)
    │   ├── transform_compoment.py   # Markdown → catalog + controls (state machine)
    │   ├── validation_compoment.py  # LLM-as-a-judge validation
    │   ├── load_compoment.py        # upserts into MongoDB
    │   └── indexer.py               # Elasticsearch indexing and hybrid search
    ├── schemas/
    │   ├── catalog.py               # CatalogModel, MetadataModel
    │   ├── control.py               # ControlModel
    │   └── example.json
    ├── data/                        # input PDFs (not committed)
    └── data-output/
        ├── 01-markdown/
        ├── 02-cdm-instances/
        └── 03-validation/
```

## Citation

If you use this work, please cite:

```bibtex
...
```

## Acknowledgements

This work was developed at the Institute of Electronics and Informatics Engineering of Aveiro (IEETA), University of Aveiro. It was supported by the Foundation for Science and Technology (FCT) through contract [UID/00127/2025](https://doi.org/10.54499/UID/00127/2025) and grant 2025.05427.BDANA, and by the CIBERRAIA project, co-funded by the European Union through the Interreg Spain-Portugal Programme (POCTEP) 2021-2027.

## License

*To be defined.* Note that PyMuPDF is distributed under the AGPL-3.0 (or a commercial licence), which should be taken into account when choosing the licence of this project.
