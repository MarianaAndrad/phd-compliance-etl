# Compliance ETL 

An ETL pipeline that turns compliance documents (ISO/IEC and NIST standards and frameworks, as PDFs) into structured, queryable data.

Each document is converted to Markdown, parsed into a common data model (a **catalog** and its **controls**), checked by an LLM judge against the source text, stored in MongoDB, and indexed in Elasticsearch for keyword and semantic search.

```
 PDF ──► extract ──► transform ──► validate ──► load ──► index
          │           │             │            │         │
          ▼           ▼             ▼            ▼         ▼
       01-markdown  02-cdm-      03-validation  MongoDB  Elasticsearch
       (.md)        instances    (.json report)          (BM25 + vectors)
                    (.json)
```

## Supported frameworks

The transform step uses a per-framework parser (`G_FRAMEWORKS_SEQUENCE_STATE_CONDITIONS` in `src/components/transform_compoment.py`). Parsers exist for:

| Key              | Document                       |
|------------------|--------------------------------|
| `iso27001`       | ISO/IEC 27001                  |
| `iso27002`       | ISO/IEC 27002                  |
| `iso27005`       | ISO/IEC 27005                  |
| `nistcsf`        | NIST Cybersecurity Framework   |
| `nistsp800-53r5` | NIST SP 800-53 Rev. 5          |

[//]: # (To support a new framework, add an entry to that dictionary &#40;see [Adding a framework]&#40;#adding-a-framework&#41;&#41;.)

## Project structure

```
compliance-etl/
├── docker/                     # Infrastructure (MongoDB, Mongo Express, Elasticsearch, Kibana)
│   ├── docker-compose.yaml
│   ├── .env.example
│   ├── mongodb.js              # Creates the app user and collections on first start
│   └── kibana.yml
└── src/
    ├── main.py                 # Pipeline entry point
    ├── metadata.json           # Per-framework settings (not committed, see below)
    ├── core/config.py          # Settings loaded from .env
    ├── dependencies/
    │   ├── database.py         # MongoDB and Elasticsearch clients
    │   └── llm.py              # Ollama chat model used by the validator
    ├── components/
    │   ├── extract_compoment.py     # PDF → Markdown (PyMuPDF), with redaction
    │   ├── transform_compoment.py   # Markdown → catalog + controls (state machine parser)
    │   ├── validation_compoment.py  # LLM-as-judge validation of each control
    │   ├── load_compoment.py        # Upserts into MongoDB
    │   └── indexer.py               # Elasticsearch indexing and hybrid search
    ├── schemas/
    │   ├── catalog.py          # CatalogModel, MetadataModel
    │   ├── control.py          # ControlModel
    │   └── extraction_schema.json
    ├── data/                   # Input PDFs (not committed)
    └── data-output/
        ├── 01-markdown/
        ├── 02-cdm-instances/
        └── 03-validation/
```

## Requirements

- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- Docker and Docker Compose, for MongoDB and Elasticsearch
- An [Ollama](https://ollama.com/) server, for the validation step (default model `qwen3.5:4b`)

The index step downloads the `all-MiniLM-L6-v2` sentence-transformers model on first run.

## Setup

### 1. Start the infrastructure

```bash
cd docker
cp .env.example .env      # edit the passwords
docker compose up -d
```

This starts:

| Service        | URL                     | Notes                                               |
|----------------|-------------------------|-----------------------------------------------------|
| MongoDB        | `localhost:27017`       | `mongodb.js` creates the app user and collections   |
| Mongo Express  | http://localhost:8081   | Log in with `DB_MONGO_USERNAME` / `DB_MONGO_PASSWORD` |
| Elasticsearch  | http://localhost:9200   | Basic auth (`elastic` / `ES_PASSWORD`), no TLS      |
| Kibana         | http://localhost:5601   | Log in with `elastic` / `ES_PASSWORD`               |

### 2. Install the Python dependencies

```bash
cd src
uv sync
```

### 3. Configure the application

```bash
cp .env.example .env
```

| Variable                       | Default                   | Description                                   |
|--------------------------------|---------------------------|-----------------------------------------------|
| `LLM_BASE_URL`                 | `http://localhost:8000/`  | Ollama server URL                             |
| `LLM_MODEL`                    | `qwen3.5:4b`              | Model used as the validation judge            |
| `MONGO_HOST` / `MONGO_PORT`    | `localhost` / `27017`     | MongoDB location                              |
| `DB_MONGO_USERNAME` / `DB_MONGO_PASSWORD` | —              | App user created by `docker/mongodb.js`       |
| `DB_MONGO_NAME`                | `test`                    | Database name                                 |
| `DATABASE_URI`                 | built from the above      | Overrides the MongoDB connection string       |
| `DB_MONGO_CATALOG_COLLECTION`  | `catalogs`                | Collection for catalogs                       |
| `DB_MONGO_CONTROL_COLLECTION`  | `controls`                | Collection for controls                       |
| `ES_BASE_URL`                  | `http://localhost:9200`   | Elasticsearch URL                             |
| `ES_USERNAME` / `ES_PASSWORD`  | —                         | Elasticsearch credentials                     |

The MongoDB and Elasticsearch credentials must match `docker/.env`.

### 4. Create `metadata.json`

`src/metadata.json` tells the pipeline which framework each PDF belongs to and how to clean it. It is gitignored because redaction phrases can contain licence text. Each top-level key is a framework:

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

- **`details.name`** must match a parser key in `transform_compoment.py`.
- **`details.type`** is one of `standard`, `framework` or `directive`.
- **`file_props.keywords`**: a PDF matches this framework when its file name contains every keyword (case-insensitive).
- **`file_props.redact_phrases`**: text removed from every page before extraction, such as watermarks and copyright lines.
- **`file_props.redact_margins`**: page bands removed as fractions of the page size (`top_y_end_percent`, `bottom_y_start_percent`, `left_x_end_percent`, `right_x_start_percent`), used to strip headers and footers.

### 5. Add the documents

Put the PDFs in `src/data/`.

## Usage

Run from `src/`:

```bash
uv run main.py            # run every step
uv run main.py --extract  # run one step only
```

Available flags: `--all`, `--extract`, `--transform`, `--validate`, `--load`, `--index`.

Each step reads the previous step's output from `data-output/`, so you can re-run one step without repeating the earlier ones. PDFs that match no entry in `metadata.json` are skipped.

### Pipeline steps

1. **Extract** (`extract_compoment.py`): applies the redactions, then rebuilds the text with PyMuPDF. It uses font size and layout to detect headings and merge blocks split across pages or columns. The output is written to `01-markdown/<name>.md`, with the PDF metadata as a front-matter header.
2. **Transform** (`transform_compoment.py`): a deterministic, regex-driven state machine walks the Markdown between the framework's start and end markers. It detects control headings and sections (description, purpose, guidance, other information) and builds the parent/child hierarchy from reference codes. The output is written to `02-cdm-instances/<name>.json`.
3. **Validate** (`validation_compoment.py`): for each control, finds its source span in the Markdown and asks an LLM judge (via Ollama, structured output) whether the extracted control is faithful. The judge looks for hallucinated, missing or misplaced content. `slug` and `parent_slug` are checked deterministically instead. The output is `03-validation/<name>.json`, holding per-control verdicts (`pass` / `fail` / `error`) and a summary with the pass rate.
4. **Load** (`load_compoment.py`): upserts the catalog (keyed by `metadata.name`) and its controls (keyed by `slug`) into MongoDB, so re-runs do not create duplicates. The step is skipped if MongoDB is unreachable.
5. **Index** (`indexer.py`): indexes the controls in Elasticsearch, with an English analyzer on `title` and `description` and a 384-dimension `description_embedding` vector. It supports BM25, kNN and hybrid retrieval through reciprocal rank fusion.

## Data model

The pipeline outputs a common data model defined with Pydantic in `src/schemas/`.

**Catalog**: one per document.

| Field      | Description                                                                 |
|------------|-----------------------------------------------------------------------------|
| `uuid`     | Catalog identifier                                                          |
| `metadata` | `type`, `name`, `version`, `language`, `published`, `last-modified`, `publisher`, `description` |

**Control**: one per requirement or clause.

| Field                  | Description                                              |
|------------------------|----------------------------------------------------------|
| `catalog_uuid`         | Owning catalog                                           |
| `ref_code`             | Official code, e.g. `8.13`, `AC-2`, `GV.OC-01`           |
| `title`                | Control name                                             |
| `slug`                 | Unique identifier, e.g. `8.13-information-backup`        |
| `parent_slug`          | Parent control's slug (`null` for top-level controls)    |
| `category`             | Usually the title of the root parent                     |
| `description`, `purpose`, `guidance`, `other_information` | Text sections from the source |
| `means_of_verifiction` | Ways to audit the control (not extracted yet)            |
| `attributes`           | Tag-like key → values list                               |
| `references`, `citers` | Cross-references (not extracted yet)                     |

See `src/schemas/example.json` for a full example.

[//]: # ()
[//]: # (## Adding a framework)

[//]: # ()
[//]: # (1. Add an entry to `G_FRAMEWORKS_SEQUENCE_STATE_CONDITIONS` in `src/components/transform_compoment.py`. Each entry defines:)

[//]: # (   - `doc_start_controls` / `doc_end_controls`: line predicates marking the controls section.)

[//]: # (   - `new_control`: detects a control heading.)

[//]: # (   - `control_description`, `control_purpose`, `control_guidance`, `control_other_information`, `control_means_of_verification`, `control_attributes`: section-header predicates that return `{"val": ..., "skip_line": ...}`.)

[//]: # (   - `construct_control`: derives `ref_code`, `title` and `slug` from a heading line.)

[//]: # (   - `control_levels` &#40;optional&#41;: regexes for hierarchy levels, for when the number of `.` delimiters in the code is not enough.)

[//]: # (2. Add a matching entry to `metadata.json` with the file keywords and redaction settings.)

[//]: # (3. Run `--extract` and `--transform`, inspect the output, then run `--validate` to measure extraction quality.)
