# Componentes do pipeline `compliance-etl`

Este documento explica, em detalhe, cada um dos ficheiros da pasta `src/components/`. Estes componentes formam um pipeline **ETL** (*Extract → Transform → Load*), complementado com **validação** e **indexação**, que transforma documentos de normas e frameworks de conformidade (ISO 27001, ISO 27002, ISO 27005, ISO 9001, NIST CSF, NIST SP 800-53, NIST SP 800-171) num modelo de dados comum, o **CDM** (*Common Data Model*), composto por um `CatalogModel` e por uma lista de `ControlModel`.

---

## Índice

1. [Visão geral do pipeline](#1-visão-geral-do-pipeline)
2. [Modelo de dados (CDM)](#2-modelo-de-dados-cdm)
3. [`extract_compoment.py`: extração (versão usada no pipeline)](#3-extract_compomentpy--extração-versão-usada-no-pipeline)
4. [`extract_compoment_v2.py`: extração com `pymupdf4llm`](#4-extract_compoment_v2py--extração-com-pymupdf4llm)
5. [`transform_compoment.py`: transformação (v1, por framework)](#5-transform_compomentpy--transformação-v1-por-framework)
6. [`transform_compoment_v2.py`: transformação (v2, por tipo de documento, a versão usada)](#6-transform_compoment_v2py--transformação-v2-por-tipo-de-documento-usada)
7. [`transformer_compoment.py`: extração experimental com LLM](#7-transformer_compomentpy--extração-experimental-com-llm)
8. [`validation_compoment.py`: validação com LLM-as-a-judge](#8-validation_compomentpy--validação-com-llm-as-a-judge)
9. [`load_compoment.py`: persistência em MongoDB](#9-load_compomentpy--persistência-em-mongodb)
10. [`indexer.py`: indexação e pesquisa em Elasticsearch](#10-indexerpy--indexação-e-pesquisa-em-elasticsearch)
11. [`data-annotation.py` e `__init__.py`](#11-data-annotationpy-e-__init__py)
12. [Observações, limitações e possíveis bugs](#12-observações-limitações-e-possíveis-bugs)

---

## 1. Visão geral do pipeline

O ponto de entrada é o `src/main.py`, que percorre todos os PDFs da pasta `./data/` e, para cada um:

1. **Identifica o framework**: procura no `metadata.json` a entrada cujas `file_props.keywords` aparecem **todas** no nome do ficheiro (por exemplo, `["iso", "iec", "27002"]`). Essa entrada fornece:
   - `details`: `type`, `name`, `publisher`, `doc_start_controls`, `doc_end_controls` (regex de início e fim da secção de controlos);
   - `file_props`: frases e margens a ocultar (*redact*) no PDF.
2. Executa os componentes pedidos com o argumento `--all | --extract | --transform | --validate | --load | --index` (por omissão, `all`):

```
 data/*.pdf
     │
     ▼  extract_compoment.convert_to_markdown + extract_metadata + write_to_file
 data-output/01-markdown/<nome>.md
     │
     ▼  transform_compoment_v2.parse_md + dump_cdm_instances
 data-output/02-cdm-instances/<nome>.json      (catalog + controls_list)
     │
     ├──▶ validation_compoment.validate_cdm_instances + dump_validation_report   (só com --validate)
     │        data-output/03-validation/<nome>.json
     │
     ├──▶ load_compoment.load_cdm_instances + persist_data  ──▶ MongoDB
     │
     └──▶ indexer.index_data  ──▶ Elasticsearch (índice "compliance-etl")
```

> **Nota:** a validação **não** faz parte do modo `all`, porque chama um LLM por cada controlo e é lenta. Só corre com `--validate`.

Componentes efetivamente importados pelo `main.py`:

| Etapa     | Ficheiro usado               | Alternativas/experimentais na pasta                     |
|-----------|------------------------------|---------------------------------------------------------|
| Extract   | `extract_compoment.py`       | `extract_compoment_v2.py`                               |
| Transform | `transform_compoment_v2.py`  | `transform_compoment.py` (v1), `transformer_compoment.py` (LLM) |
| Validate  | `validation_compoment.py`    | (nenhuma)                                               |
| Load      | `load_compoment.py`          | (nenhuma)                                               |
| Index     | `indexer.py`                 | (nenhuma)                                               |

---

## 2. Modelo de dados (CDM)

Os componentes de transformação, validação, carregamento e indexação trabalham sobre os modelos Pydantic definidos em `src/schemas/`.

### `CatalogModel` (`schemas/catalog.py`)

Representa **um documento** (uma norma ou framework).

| Campo      | Descrição |
|------------|-----------|
| `uuid`     | Identificador único gerado com `uuid4()`. |
| `metadata` | `MetadataModel` com `type` (`standard` / `framework` / `directive`), `name`, `version`, `language` (normalizado para minúsculas), `published`, `last_modified`, `publisher` e `description`. |

### `ControlModel` (`schemas/control.py`)

Representa **um controlo, requisito ou cláusula** do documento. Tem `validate_assignment=True`, ou seja, o Pydantic valida os campos também quando são alterados depois de criado o objeto (o parser altera `description`, `purpose`, etc. linha a linha).

| Campo                  | Descrição |
|------------------------|-----------|
| `catalog_uuid`         | UUID do catálogo a que pertence. |
| `ref_code`             | Código oficial (ex.: `5.15`, `AC-2`, `GV.OC-01`). |
| `title`                | Título curto do controlo. |
| `slug`                 | Identificador legível e único (ex.: `5.15-access-control`, `ac-2-account-management`). |
| `parent_slug`          | `slug` do controlo pai (`None` nos controlos de topo). |
| `category`             | Título do antepassado de nível 1 (para um controlo de topo, o próprio título). |
| `description`          | Texto do controlo propriamente dito. |
| `purpose`              | Propósito (secção *Purpose* da ISO 27002). |
| `guidance`             | Orientações de implementação (secção *Guidance*). |
| `other_information`    | Informação adicional (secção *Other information*). |
| `means_of_verifiction` | Meios de verificação. Atenção: o nome do campo tem um erro ortográfico (*verifiction*). |
| `attributes`           | Lista de dicionários `{chave: [valores]}`, vinda da tabela de atributos da ISO 27002 (ex.: `{"control_type": ["preventive"]}`). |
| `references`, `citers` | Referências externas e documentos que citam o controlo (ainda não preenchidos pelo parser). |

O ficheiro JSON intermédio (`02-cdm-instances/*.json`) tem a forma:

```json
{
  "catalog": { "uuid": "...", "metadata": { ... } },
  "controls_list": [ { "ref_code": "5.1", "title": "...", "slug": "...", ... }, ... ]
}
```

---

## 3. `extract_compoment.py`: extração (versão usada no pipeline)

**Objetivo:** converter um PDF num ficheiro Markdown "limpo", com um cabeçalho de metadados (*front-matter*), adequado ao parser determinístico da etapa seguinte.

**Bibliotecas:** `pymupdf` (fitz) para manipular o PDF e analisar o layout; `pypdf` para ler os metadados. Há código comentado que mostra tentativas anteriores com `docling` e `tika`.

### 3.1 `redact_doc(source_document, file_props)`

Remove do PDF conteúdo indesejado **antes** de extrair o texto:

1. **Frases a ocultar** (`file_props["redact_phrases"]`): para cada página, procura cada frase com `page.search_for(phrase)`, que devolve os retângulos onde a frase aparece. Cada retângulo é **encolhido** (1 pt na horizontal, 0,5 pt na vertical) antes de criar a anotação de redação, para não apagar por acidente texto das linhas vizinhas. Exemplos: avisos de copyright e "Printed / viewed by...".
2. **Margens** (`file_props["redact_margins"]`): define percentagens da página a apagar:
   - `top_y_end_percent`: tudo acima de `altura × valor` (cabeçalho);
   - `bottom_y_start_percent`: tudo abaixo de `altura × valor` (rodapé, números de página);
   - `left_x_end_percent` / `right_x_start_percent`: margens laterais.
   No `metadata.json`, as ISO usam `0.05` e `0.965` (5% de cima e 3,5% de baixo).
3. Aplica as redações com `page.apply_redactions(images=PDF_REDACT_IMAGE_NONE)`. O texto é **removido de facto** do PDF e as imagens não são tocadas.
4. Grava o PDF numa subpasta `redacted/` ao lado do original (ex.: `data/redacted/NIST.SP.800-53r5.pdf`), com `garbage=3, deflate=True` para compactar. **O original nunca é alterado.**
5. Devolve o caminho do PDF redigido.

### 3.2 `convert_to_markdown(source_document, file_props)`

É a função principal. Começa por chamar `redact_doc` e depois faz uma **reconstrução heurística do texto** a partir dos blocos que o PyMuPDF devolve (`page.get_text("dict")`). A ideia é decidir, bloco a bloco, se deve haver quebra de linha ou não, para que títulos partidos em várias linhas fiquem juntos e parágrafos fiquem separados.

Constantes globais:
- `G_MAX_TITLE_WORD_COUNT = 18` e `G_MAX_TITLE_CHAR_COUNT = 150`: limites para um texto ser considerado candidato a título.

Funções internas (definidas dentro de `convert_to_markdown`):

| Função | O que faz |
|--------|-----------|
| `_is_title_candidate(strg)` | Um texto é candidato a título se não for demasiado longo (≤150 caracteres e ≤18 palavras), **não terminar em ponto final** e só tiver caracteres "simples" (`a-zA-Z0-9:|.,()/-` e espaços). |
| `_get_block_font_size(block)` | Devolve o tamanho de letra do bloco. Se houver spans com tamanhos que diferem mais de 3 pt, devolve `None` (bloco misto). |
| `_is_text_continuation(prev, block)` | Dois blocos são continuação um do outro se os tamanhos de letra diferirem menos de 5 pt. |
| `_non_ascii_to_html` / `_normalize_non_ascii` | Converte caracteres não-ASCII em entidades HTML (`&#x...;`) e depois substitui as mais comuns por equivalentes ASCII: travessões (`–`, `—`) passam a ` - `, aspas curvas a `"` / `'`, reticências a `...`, *bullet* a `-`, espaço não separável a espaço, e o espaço de largura zero é removido. Os restantes caracteres não-ASCII **ficam como entidades HTML**, e mais tarde o parser descarta as linhas que ainda os contenham. |
| `_prev_block_has_avail_width(prev, block)` | Heurística de **fim de parágrafo**: mede a largura da primeira palavra do bloco atual e verifica se essa palavra *caberia* no fim da última linha do bloco anterior. Se coubesse e mesmo assim foi para a linha seguinte, o bloco anterior terminou de propósito (fim de parágrafo ou título) e é inserido um `\n` extra. Usa as margens da página calculadas antes. |
| `_should_merge_title()` | Decide se dois blocos consecutivos são **o mesmo título partido em duas linhas**. Exige ao mesmo tempo: sobreposição vertical, alinhamento à esquerda, tamanho de letra semelhante, ambos candidatos a título, a mesma "caixa" (ambos em maiúsculas ou ambos não), soma de palavras ≤18 e o bloco anterior **sem** espaço livre no fim. |
| `_is_inside_bbox(outer, inner)` | Verifica se algum canto de `inner` está dentro de `outer`. |
| `_find_table_intersect(tables, bbox)` | Devolve a tabela que contém o span dado (ou `None`). |
| `_generate_table_markdown(table_data)` | Converte a matriz de células numa tabela Markdown (`|a|b|` + `|---|---|`). É usado em vez de `table.to_markdown()` porque esse método por vezes inclui texto à volta da tabela. |
| `_get_pending_table()` | Insere a tabela em Markdown **apenas na primeira vez** que é encontrada (fica guardada em `intersected_tables_list`). |
| `_filter_out_false_positive_tables(tables)` | O `find_tables()` deteta muitas "tabelas" falsas (por exemplo, caixas de texto). Uma tabela é **rejeitada** se: ≥50% das células estiverem vazias; a média de caracteres por célula for ≥60; a média de palavras por célula for ≥8; ou o cabeçalho (excluindo a 1.ª coluna) tiver células vazias. |

**Algoritmo principal (por página):**

1. Deteta tabelas e filtra os falsos positivos.
2. Calcula as **margens efetivas** da página juntando as *bounding boxes* de todos os blocos (`content_rect`).
3. Percorre os blocos de texto (`type == 0`) e, dentro deles, linhas e spans:
   - se a distância vertical entre spans for >25 pt, insere `\n`;
   - se o span estiver dentro de uma tabela, **não é adicionado como texto**; a tabela fica marcada como pendente e será emitida inteira em Markdown;
   - caso contrário, concatena o texto do span.
4. Normaliza os caracteres não-ASCII do bloco.
5. Escreve o bloco **anterior** e a tabela pendente, se houver. Junta `\n` a menos que `_should_merge_title()` diga para unir, e junta outro `\n` se `_prev_block_has_avail_width` indicar fim de parágrafo.
6. No fim da página, escreve o último bloco e a tabela pendente.

O resultado é uma string com o documento inteiro. O código depois do primeiro `return doc_content` (extração via XHTML e um bloco docling comentado) é **código morto** e nunca é executado.

### 3.3 `extract_metadata(source_document)`

Lê os metadados embutidos no PDF com `pypdf.PdfReader`: `document_name` (nome do ficheiro), `title`, `author`, `subject`, `creation_date` e `modification_date`. Se o PDF não tiver metadados, os campos ficam vazios.

### 3.4 `write_to_file(file_path, metadata, content)`

Escreve o Markdown final com um cabeçalho ao estilo YAML:

```
---
document_name: NIST.SP.800-53r5.pdf
title: ...
author: ...
---

<conteúdo>
```

---

## 4. `extract_compoment_v2.py`: extração com `pymupdf4llm`

Versão **alternativa e mais simples** da extração, que **não é usada pelo `main.py`** (pode ser executada isoladamente com `python extract_compoment_v2.py`). Em vez de heurísticas próprias, delega a conversão na biblioteca `pymupdf4llm`, pensada para gerar Markdown para LLMs. O código está mais "limpo": tem *type hints*, `logging`, `pathlib`, `try/finally` para fechar documentos e validação de existência do ficheiro.

| Função | Descrição |
|--------|-----------|
| `redact_doc(source_document, file_props, output_dir="redacted")` | Semelhante à v1, mas: (1) não encolhe os retângulos das frases; (2) preenche a redação a **branco** (`fill=(1,1,1)`); (3) as margens são dadas em **pontos absolutos** com as chaves `top`, `bottom`, `left`, `right` (e não em percentagens como na v1 e no `metadata.json`). Lança `FileNotFoundError` se o PDF não existir. |
| `convert_to_markdown(redacted_document)` | Chama `pymupdf4llm.to_markdown` com `header=False`, `footer=False` (ignora cabeçalhos e rodapés detetados), `ignore_images=True` e `table_strategy="lines_strict"` (só reconhece tabelas desenhadas com linhas, o que reduz os falsos positivos). Recebe um PDF **já redigido**. |
| `clean_text(text)` | Substitui os caracteres tipográficos do dicionário `_NON_ASCII_REPLACEMENTS` (travessões, aspas curvas, reticências, *bullets*, espaços especiais) por ASCII, remove espaços no fim das linhas e reduz 3 ou mais quebras de linha seguidas a uma linha em branco. |
| `extract_metadata(source_document, metadata_file)` | Combina metadados de um ficheiro JSON (`name`, `publisher`, `type`, `version`, `language`) com os do PDF (`subject`, datas). |
| `write_to_file(...)` | Igual à v1, mas cria a pasta de destino se não existir e regista no log. |
| `process_pdf(...)` | Orquestra: redigir → converter → metadados → limpar → escrever. |

O bloco `__main__` processa todos os `*.pdf` de `../data` com `FILE_PROPS` fixos (`top: 50`, `bottom: 40` pontos e a frase "This page intentionally left blank").

---

## 5. `transform_compoment.py`: transformação (v1, por framework)

**Objetivo:** ler o Markdown produzido pela extração e construir as instâncias do CDM (`CatalogModel` + lista de `ControlModel`) através de uma **máquina de estados** linha a linha. Esta é a primeira versão, em que as regras estão definidas **por framework concreto** (`iso27001`, `iso27002`, `iso27005`, `nistcsf`, `nistsp800-53r5`). **Não é usada pelo `main.py`**, que usa a v2.

### 5.1 Funções utilitárias (`UTIL_*`)

| Função | Descrição |
|--------|-----------|
| `UTIL_is_phrase_continuity(prev, next)` | Trata um caso específico do NIST: se a string anterior termina com `"` e a seguinte começa por uma palavra capitalizada (que não está toda em maiúsculas), não é continuação. Exemplo: `...can be "none."` seguido de `Related Controls: ...`. |
| `UTIL_is_list_item_start(strg)` | Deteta inícios de itens de lista: `(a) `, `(1) `, `a. `, `1) `, etc. |
| `UTIL_update_text_state(strg)` | Atualiza a flag global `G_IN_ITEM_LIST` (entra numa lista ao encontrar um item e sai ao encontrar uma frase terminada em `.`). Atualmente esta flag não é usada para nenhuma decisão. |
| `UTIL_string_append(dest, source)` | **Função central de reconstrução de parágrafos.** Junta `source` a `dest` com **espaço** (mesma frase) ou com **`\n`** (nova linha ou parágrafo). Junta com espaço quando: a nova linha começa em minúscula **ou** `dest` não termina em pontuação final (`!.:;?`); e a "caixa" das duas é igual (ambas em maiúsculas ou ambas não); e a nova linha não é um item de lista; e não é um `- ` depois de `; and`; e há continuidade de frase; e a nova linha não é uma linha de tabela (`|...|`). Ignora os marcadores `<!-- PAGE_BREAK -->`. |
| `UTIL_get_control_lvl(control, control_levels)` | Calcula o **nível hierárquico** de um controlo. Se o framework definir `control_levels` (dicionário `nível → regex`), usa-os. Caso contrário, conta os delimitadores `.` e `-` no `ref_code`: o primeiro controlo analisado define a contagem base (`G_BASE_CONTROL_DELIMITER_COUNT`) e o nível é `delimitadores + 1 − base`. Ex.: na ISO 27002, `5` → 1, `5.1` → 2. |
| `UTIL_regex_str_match(regex, str)` | Devolve o texto do primeiro *match* ou `''`. |

### 5.2 `ControlStates` (Enum)

Estados da máquina: `NONE`, `START`, `DESCRIPTION`, `PURPOSE`, `GUIDANCE`, `OTHER_INFORMATION`, `MEANS_OF_VERIFICATION`, `ATTRIBUTES`. O estado atual indica **em que campo** do controlo a linha lida deve ser acumulada.

### 5.3 `G_FRAMEWORKS_SEQUENCE_STATE_CONDITIONS`

Dicionário de **regras por framework**. Cada entrada define funções (lambdas) que recebem uma linha e decidem:

| Chave | Significado |
|-------|-------------|
| `doc_start_controls` | Linha onde começa a secção de controlos (ex.: ISO 27002: `5 Organizational controls`; NIST CSF: `GOVERN (GV):`). Serve para ignorar o índice, o prefácio, etc. |
| `doc_end_controls` | Linha onde termina (ex.: `Annex A`, `REFERENCES`, `Appendix B. CSF Tiers`). |
| `new_control` | Regex que identifica o cabeçalho de um novo controlo. |
| `control_description`, `control_purpose`, `control_guidance`, `control_other_information`, `control_means_of_verification`, `control_attributes` | Devolvem `{"val": <match ou bool>, "skip_line": bool}`. `val` indica se a linha muda o estado; `skip_line` indica se a própria linha deve ser descartada (por exemplo, o título "Purpose") ou aproveitada (por exemplo, "Control: texto..." no NIST). |
| `construct_control` | Lambda que, a partir da linha de cabeçalho, devolve o tuplo `(ref_code, title, slug)`. |
| `control_levels` (opcional) | Regex por nível, quando a contagem de delimitadores não chega. |

Particularidades por framework:

- **ISO 27001 / ISO 27005**: o controlo é um cabeçalho numerado (`6.1.2 Information security risk assessment`). Não há secções Purpose/Guidance, por isso todo o texto vai para `description`.
- **ISO 27002**: cada controlo tem as secções `Control`, `Purpose`, `Guidance` e `Other information`, e uma **tabela de atributos** (*Control type*, *Information security properties*, *Cybersecurity concepts*, ...). A regra de atributos dispara num cabeçalho numerado (o próprio título do controlo vem antes da tabela).
- **NIST CSF 2.0**: as Funções/Categorias têm o formato `Govern (GV)` / `Organizational Context (GV.OC)` e as subcategorias `GV.OC-01`. O `construct_control` tem dois ramos: se a linha tiver `Título (CÓDIGO)`, separa o título do código; caso contrário, usa o próprio código como título.
- **NIST SP 800-53 r5**: os controlos têm a forma `AC-2 ACCOUNT MANAGEMENT` (em maiúsculas) e os *enhancements* `(1) AUTOMATED SYSTEM ACCOUNT MANAGEMENT`. O texto após `Control:` vai para `description`. Os `control_levels` definem: nível 1 = `3.1` (família), nível 2 = `AC-2`, nível 3 = `(1)`.

### 5.4 `parse_md(md_path, framework_details)`

Algoritmo da máquina de estados:

1. Escolhe as regras com `framework_details["name"]`.
2. Cria um `CatalogModel` novo (UUID aleatório) com `type`, `name` e `publisher`.
3. Lê o ficheiro linha a linha (com `strip()`):
   1. Se a linha casar `doc_start_controls`, ativa `b_control_start`.
   2. Dentro da secção de controlos:
      - **fim da secção** → guarda o controlo atual e desativa;
      - **novo controlo** → guarda o controlo anterior (`_add_cur_control`), constrói `ref_code`, `title` e `slug` e cria um `ControlModel`. A `category` é o título do controlo de nível 1 guardado em `parent_controls[1]`, ou o próprio título se o controlo for de topo.
   3. Avalia, por esta ordem, se a linha muda o estado para ATTRIBUTES, DESCRIPTION, PURPOSE, GUIDANCE ou OTHER_INFORMATION. Se mudar e `skip_line` for verdadeiro, salta a linha. Se o resultado for um `re.Match`, corta a linha a partir do fim do *match* (e retira o `:` inicial).
   4. **Limpeza da linha**: espaço não separável passa a espaço normal; **descarta linhas com caracteres não-ASCII**; `&#x2014;` passa a `-`; remove os espaços em `( x` e `x )`; remove os caracteres de *backspace* (`\x08`); normaliza espaços múltiplos.
   5. **Acumula** a linha no campo correspondente ao estado, com `UTIL_string_append`. No estado ATTRIBUTES, a primeira linha da tabela define as **chaves** (`control_type`, `information_security_properties`, ...) e as seguintes acrescentam os **valores**, separados por `#` (ex.: `#Preventive #Detective` → `["preventive", "detective"]`).
4. `_add_cur_control()`: remove o espaço ou `\n` final de cada campo; se o nível for >1, define `parent_slug` como o `slug` do último controlo do nível acima; regista o controlo em `parent_controls[nível]` e adiciona-o a `controls_list`.
5. Devolve `{"catalog": catalog, "controls_list": controls_list}`.

### 5.5 `dump_cdm_instances(file_path, cdm_instances)`

Serializa o catálogo e os controlos (via `model_dump()`) para JSON com indentação.

---

## 6. `transform_compoment_v2.py`: transformação (v2, por tipo de documento, usada)

É a **versão usada pelo `main.py`**. As funções `UTIL_*`, `ControlStates`, `_add_cur_control` e `dump_cdm_instances` são **iguais** às da v1. As diferenças estão na forma como as regras são escolhidas e configuradas:

### 6.1 Regras genéricas por **tipo** de documento

Em vez de uma entrada por norma, `G_FRAMEWORKS_SEQUENCE_STATE_CONDITIONS` tem:

| Chave | Aplica-se a | Notas |
|-------|-------------|-------|
| `"standard"` | Todas as normas ISO (27001, 27002, 27005, 9001) | O cabeçalho numerado (`5.1 Policies for...`) abre o controlo. As secções são detetadas **sem distinção entre maiúsculas e minúsculas** e aceitando cabeçalhos Markdown (`^#*\s*purpose\s*$`). Os atributos são qualquer linha com `|...|` (tabela Markdown) e **não** saltam a linha. |
| `"framework"` | Frameworks em geral (NIST SP 800-53, NIST SP 800-171, ...) | Regras do NIST SP 800-53 (`AC-2 ...`, `(1) ...`, `Control:`), com `control_levels`. |
| `"framework-nistcsf"` | NIST CSF especificamente | Regras do CSF (`Govern (GV)`, `GV.OC-01`). |

A escolha é feita assim:

```python
seq_key = f'{framework_details["type"]}-{framework_details["name"]}'   # ex.: "framework-nistcsf"
regras = TABELA[seq_key] if seq_key in TABELA else TABELA[framework_details["type"]]
```

Ou seja, primeiro procura uma regra específica `tipo-nome` e, se não existir, usa a regra genérica do tipo. Isto permite acrescentar novas normas ISO sem escrever código: basta adicioná-las ao `metadata.json`.

### 6.2 Início e fim configurados no `metadata.json`

`doc_start_controls` e `doc_end_controls` deixam de ser lambdas no código e passam a ser **regex em texto** em `framework_details` (vindas do `metadata.json`), aplicadas com `re.match(..., re.IGNORECASE)`.

### 6.3 Atributos só dentro de um controlo

```python
if control_state in (DESCRIPTION, ATTRIBUTES) and control_attributes(line)["val"]:
```

Uma linha de tabela só é tratada como atributos se o parser já estiver dentro da descrição ou dos atributos de um controlo. Assim, tabelas de outras secções não são confundidas com atributos.

### 6.4 Categoria

A condição para herdar a categoria do pai passa a ser `nível > 1` (na v1 era `nível > G_BASE_CONTROL_DELIMITER_COUNT`, o que era menos claro).

---

## 7. `transformer_compoment.py`: extração experimental com LLM

Alternativa **experimental** ao parser determinístico: em vez de regras, usa um **LLM** (via `langchain_ollama.ChatOllama`, configurado em `dependencies/llm.py` com `temperature=0` e `num_ctx=16384`) para extrair controlos em formato estruturado. **Não é usada no `main.py`**.

| Função | Descrição |
|--------|-----------|
| `load_document(path)` | Lê o Markdown inteiro. |
| `splitter_text()` | Cria um `RecursiveCharacterTextSplitter` (LangChain) com blocos de **1500 caracteres** e **100 de sobreposição**, para caber no contexto do modelo e não cortar frases nas fronteiras. |
| `extract_entities(document_text, schema)` | 1) Cria dinamicamente com `create_model` um modelo `ExtractionResult` com `items: List[schema]`; 2) associa esse esquema ao LLM via `with_structured_output` (*tool calling*); 3) para cada bloco, envia uma `SystemMessage` com o JSON Schema e uma `HumanMessage` com o texto; 4) se um bloco falhar, regista um aviso e continua; 5) **remove duplicados** comparando o JSON de cada item, porque a sobreposição entre blocos pode extrair o mesmo controlo duas vezes. |
| `save_result(file_path, result)` | Grava um modelo em JSON. |
| `persist_test_results(db, catalog_uuid, results)` | Faz *upsert* numa coleção **de teste** (`transformer_test_controls`) no MongoDB (via `motor`), com chave `(catalog_uuid, slug)`. |
| `main_test()` | Define um esquema reduzido `ExtractedControl` (`ref_code`, `title`, `slug`, `description`), pega numa **janela de 20 000 caracteres** a meio do NIST SP 800-53 r5, extrai, persiste e grava `NIST.SP.800-53r52.v2.json`. |

Há um marcador `# Validation gates ... TODO IMPLEMENTED`; essa validação foi depois implementada como componente próprio em `validation_compoment.py`.

---

## 8. `validation_compoment.py`: validação com LLM-as-a-judge

**Objetivo:** avaliar automaticamente a **qualidade da transformação**. Para cada controlo extraído, um LLM atua como **juiz** e compara o controlo estruturado (JSON) com o **texto original** do Markdown de onde veio, decidindo `pass` ou `fail`.

### 8.1 Prompt e modelos de saída

- `G_MAX_SOURCE_CHARS = 12000`: limite de caracteres do texto fonte enviado por controlo, para não ultrapassar o contexto do modelo.
- `G_JUDGE_SYSTEM_PROMPT`: pede ao modelo que atue como auditor imparcial e procure:
  - **conteúdo alucinado** (está no JSON e não está na fonte);
  - **conteúdo em falta** (está na fonte e não está no JSON);
  - **conteúdo mal colocado** (por exemplo, guidance guardado em description, ou texto de outro controlo);
  - `ref_code`, `title` ou `slug` incoerentes.

  Indica também o que **ignorar**: espaços, hifenização, marcadores de página, formatação de tabelas e os cabeçalhos das secções. Explica ainda que `slug`, `parent_slug` e `category` são **derivados** da hierarquia e só devem ser verificados quanto à coerência, não quanto à presença no texto. Por fim, pede **primeiro a justificação e só depois o veredito**, uma técnica de *chain-of-thought* para decisões mais fundamentadas.
- `JudgeVerdict` (Enum): `pass` / `fail`.
- `ControlJudgement`: saída estruturada do LLM. Os campos estão por ordem `justification` → `issues` → `verdict`, para que o modelo **escreva o raciocínio antes** de decidir.
- `ControlValidationResult`: resultado final por controlo (`catalog_uuid`, `ref_code`, `slug`, `source_line`, `verdict`, `issues`, `justification`).

### 8.2 Localizar o texto fonte de cada controlo

Antes de chamar o juiz é preciso saber **que excerto do Markdown** corresponde a cada controlo:

| Função | Descrição |
|--------|-----------|
| `UTIL_norm_line(strg)` | Normaliza a linha: decodifica entidades HTML, remove comentários `<!-- -->`, passa a minúsculas e guarda só as sequências `[a-z0-9]+` separadas por espaço. Assim, `5.15 Access control` fica `5 15 access control`. |
| `UTIL_is_heading_candidate(line)` | Exclui linhas vazias, **linhas de tabela** (`|...`) e **entradas do índice** (linhas com 5 ou mais pontos seguidos, ex.: `5.5 Contact......14`). |
| `UTIL_is_control_heading(norm_line, control)` | Uma linha é o cabeçalho do controlo se começar pelo `ref_code` normalizado e contiver o título, **ou** se começar por `título + ref_code` (formato do NIST CSF, `Govern (GV)`). Ignora um *bullet* de um carácter no início (ex.: `o GV.OC-01`). |
| `locate_control_spans(source_lines, controls_list, start_regex, end_regex)` | Procura os cabeçalhos **sequencialmente** com um cursor que só avança: cada controlo é procurado a partir da posição do anterior, o que evita confundir referências cruzadas ("see 5.24") com o cabeçalho real. O cursor começa no primeiro *match* de `start_regex` que não esteja no índice. Cada intervalo `[início, fim)` termina onde começa o próximo controlo localizado; o último termina no `end_regex` ou no fim do ficheiro. Controlos não encontrados ficam `None`. |

### 8.3 Execução do juiz

| Função | Descrição |
|--------|-----------|
| `build_judge_llm()` | LLM com saída estruturada `ControlJudgement`. |
| `validate_control(judge_llm, control, source_context)` | Monta a mensagem: prompt de sistema + JSON Schema do `ControlModel`; mensagem humana com o **SOURCE TEXT** entre `"""` e o **controlo em JSON** (sem `catalog_uuid` e `citers`, que não são relevantes). Se o LLM falhar ou devolver algo que não se consegue interpretar, devolve um `fail` com uma explicação, para que um erro não passe despercebido como `pass`. |
| `validate_cdm_instances(md_path, cdm_instances, framework_details, judge_llm)` | Lê o Markdown, localiza os intervalos e, para cada controlo: se não foi encontrado, dá `fail` ("Control heading not found"); caso contrário, junta as linhas não vazias do intervalo, trunca a 12 000 caracteres se necessário (com aviso) e chama o juiz. Mostra o progresso com `tqdm`. `source_line` é guardado com base 1. |
| `summarize_validation(results)` | Resumo: `total_controls`, `passed`, `failed`, `not_found_in_source` e `pass_rate` (4 casas decimais). |
| `dump_validation_report(file_path, results)` | Grava `{"summary": ..., "results": [...]}` em `data-output/03-validation/<nome>.json` e devolve o resumo. |

---

## 9. `load_compoment.py`: persistência em MongoDB

**Objetivo:** carregar o JSON do CDM e gravá-lo no MongoDB de forma **idempotente**, ou seja, correr o pipeline várias vezes não cria duplicados. Usa o cliente **assíncrono** `pymongo.AsyncMongoClient`.

| Função | Descrição |
|--------|-----------|
| `load_cdm_instances(cdm_path)` | Lê `02-cdm-instances/<nome>.json` e reconstrói os objetos Pydantic (`CatalogModel(**...)`, `ControlModel(**...)`), validando os dados. É também usada pelas etapas de validação e de indexação. |
| `persist_catalog(client, db, catalog)` | `update_one` com `upsert=True` na coleção `settings.DB_MONGO_CATALOG_COLLECTION`, usando como chave `metadata.name`. Se o catálogo já existir, é **substituído** (`$set`) pelos dados novos, incluindo o novo `uuid`. Devolve `catalog.uuid`. O bloco comentado mostra a versão anterior, que procurava primeiro o catálogo. |
| `persist_controls(client, db, catalog_uuid, controls_list)` | Para cada controlo, preenche `catalog_uuid` se estiver vazio e faz *upsert* na coleção `settings.DB_MONGO_CONTROL_COLLECTION` usando como chave **apenas o `slug`** (a chave composta `(catalog_uuid, slug)` está comentada). |
| `persist_data(client, framework_name, cdm_instances)` | Orquestra: grava o catálogo e depois os controlos, na base `settings.DB_MONGO_NAME`. |

---

## 10. `indexer.py`: indexação e pesquisa em Elasticsearch

**Objetivo:** tornar os controlos **pesquisáveis** com recuperação **híbrida**: lexical (BM25) e semântica (embeddings), combinadas com **Reciprocal Rank Fusion (RRF)**. É a base para um sistema de *Information Retrieval* / RAG sobre conformidade.

### 10.1 Embeddings

```python
model = SentenceTransformer("all-MiniLM-L6-v2")
```

Modelo de *sentence embeddings* com **384 dimensões**, carregado quando o módulo é importado.

### 10.2 Criação do índice: `create_index`

Cria o índice `compliance-etl` com:

- **Analisador personalizado `my_english_analyzer`**: tokenizador `standard` (já remove pontuação) → `lowercase` → `english_stop` (remove *stopwords* inglesas como "the" e "and") → `porter_stem` (reduz palavras à raiz: "running" passa a "run").
- **Mapeamentos:**
  - `title` e `description`: `text` com o analisador acima (pesquisa lexical/BM25);
  - `description_embedding`: `dense_vector` com 384 dimensões, indexado, com semelhança de **cosseno** (pesquisa kNN).
  - Os restantes campos do controlo são mapeados dinamicamente pelo Elasticsearch.

### 10.3 Gestão do índice e dos documentos

| Função | Descrição |
|--------|-----------|
| `index_exists`, `refresh_index`, `get_index_mapping`, `empty_index`, `delete_index` | Operações administrativas. `refresh_index` torna visíveis para pesquisa os documentos acabados de inserir. `empty_index` apaga todos os documentos (`delete_by_query` com `match_all`). |
| `insert_document(es, control, catalog)` | Calcula o embedding de `description`, acrescenta `catalog_uuid` e `catalog_name` (para saber de que documento vem o controlo) e indexa com `id = slug` (reindexar substitui o documento). |
| `update_document(es, control)` | Atualização parcial: só altera os campos enviados (ao contrário de `index`, que substitui o documento inteiro). |
| `get_document(es, control)` | Obtém um documento pelo `slug`. |

### 10.4 Pesquisa

| Função | Tipo |
|--------|------|
| `search_index` | `match_all` (todos os documentos). |
| `search_document_by_description` | Lexical (BM25) só em `description`. |
| `search_document_by_all_fields` | Lexical `multi_match` em `title` + `description`. |
| `test_knn_search_by_description` | Semântica: calcula o embedding da pergunta e faz kNN (`k=5`, `num_candidates=10`) sobre `description_embedding`. |
| `pretty_response(response)` | Imprime os resultados de forma legível (id, posição, score, título, categoria, descrição, ...). |

### 10.5 `reciprocal_rank_fusion(*listas, K=60)`

Combina rankings de vários sistemas. Cada argumento é um tuplo `(lista_ordenada_de_ids, peso)`. Para cada documento:

$$\text{RRF}(d) = \sum_{s} \frac{w_s}{\text{rank}_s(d) + K}$$

Com `K=60` (o valor clássico da literatura), a diferença entre posições do topo é suavizada. Um documento que aparece bem classificado em **ambos** os sistemas sobe no ranking final. Devolve `(lista [(id, score)] ordenada, lista de ids)`.

### 10.6 `index_data(es, cdm_instances)`

Função chamada pelo `main.py`:

1. Faz *refresh* e cria o índice se ainda não existir.
2. Insere todos os controlos do documento.
3. Faz *refresh* de novo.
4. **Executa um teste de pesquisa fixo**: a pergunta *"How can I be compliant with backup requirements in my organization?"* é feita em modo lexical e em modo kNN, os resultados são combinados com RRF (peso **0,5** para o lexical e **1,0** para o denso, o que favorece a pesquisa semântica) e são impressos os 5 melhores.

---

## 11. `data-annotation.py` e `__init__.py`

- **`__init__.py`**: vazio; serve apenas para o Python tratar `components` como um *package* (`from components.x import y`).
- **`data-annotation.py`**: **vazio**, é um *placeholder*. Pelo nome, destina-se a uma futura etapa de **anotação manual de dados** (por exemplo, criar um *ground truth* para avaliar a extração ou a pesquisa). Atenção: o hífen no nome impede que seja importado com `import` normal; se vier a ser um módulo, o ideal é renomeá-lo para `data_annotation.py`.

---

## 12. Observações, limitações e possíveis bugs

Pontos encontrados durante a análise que pode valer a pena rever:

1. **Estado global entre ficheiros (transform v1 e v2):** `G_BASE_CONTROL_DELIMITER_COUNT` é global e só é definido **uma vez**, no primeiro controlo analisado. Como o `main.py` processa vários PDFs no mesmo processo, a contagem base do **primeiro** documento é reutilizada nos seguintes, o que pode dar níveis, `parent_slug` e `category` errados nos documentos seguintes quando não há `control_levels`. Solução: reiniciar a variável no início de `parse_md`.
2. **Colisões de `slug` entre catálogos:** o MongoDB (`persist_controls`) e o Elasticsearch (`insert_document`, `id=slug`) usam **só** o `slug` como chave. Normas com numeração semelhante (ex.: ISO 27001 e ISO 9001 têm ambas a cláusula `4.1 Understanding the organization and its context`) produzem o mesmo slug e **sobrescrevem-se** umas às outras. Isto já acontece nos JSON atuais: `4.1-understanding-the-organization-and-its-context` aparece tanto na ISO 27001 como na ISO 9001. A chave composta `(catalog_uuid, slug)` está comentada no código.
3. **`catalog_uuid` muda a cada transformação:** o `parse_md` gera um `uuid4()` novo de cada vez e o `persist_catalog` substitui o catálogo existente pelo novo UUID, por isso os controlos antigos que não sejam sobrescritos ficam a apontar para um UUID que já não existe.
4. **`index_data` corre sempre uma pesquisa de teste** e imprime resultados completos (código de depuração que convém retirar ou pôr atrás de uma flag).
5. **Blocos `__main__` desatualizados:** em `extract_compoment.py`, `convert_to_markdown(file)` é chamado sem `file_props`; em `transform_compoment*.py`, `parse_md(document_path)` é chamado sem `framework_details`. Executar estes ficheiros diretamente dá `TypeError`.
6. **Código morto em `extract_compoment.py`:** tudo o que está depois do primeiro `return doc_content` em `convert_to_markdown` nunca é executado.
7. **Regex `(:?\.\d+)*`:** aparece várias vezes e provavelmente devia ser `(?:\.\d+)*` (grupo sem captura). Como está, é um grupo de captura com um `:` opcional. Funciona na prática, mas aceita `5:1`.
8. **Linhas com caracteres não-ASCII são descartadas** no parser. Isto remove ruído, mas pode também apagar conteúdo legítimo (por exemplo, `©`, símbolos matemáticos ou palavras acentuadas, caso venham a ser processados documentos em português).
9. **Incompatibilidade entre o `extract_compoment_v2.py` e o `metadata.json`:** a v2 espera margens em pontos (`top`, `bottom`, ...) e metadados planos (`name`, `publisher`), mas o `metadata.json` usa percentagens (`top_y_end_percent`, ...) e está organizado por framework (`details`). Se a v2 passar a ser usada no `main.py`, é preciso adaptar uma das partes.
10. **`G_IN_ITEM_LIST`** é atualizado mas nunca lido.
11. **Erro ortográfico** no campo `means_of_verifiction` (CDM e indexer); corrigi-lo implica migrar os dados já guardados.
12. **`transformer_compoment.py` não pode ser importado:** importa `get_database` de `dependencies.database`, mas essa função já não existe (o módulo só tem `get_mongo_client` e `get_elasticsearch_client`). Também usa `motor`, enquanto o resto do projeto usa `pymongo.AsyncMongoClient`.
