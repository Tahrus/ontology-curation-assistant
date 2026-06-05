# Zotero Literature Markdown

`zotero_lit_md` exports Zotero Desktop PDF attachments into LLM/RAG-ready Markdown files.

## Zotero Local API

Enable the Zotero local API in Zotero Desktop:

1. Open Zotero.
2. Open Preferences.
3. Enable local API access from the Advanced/API settings.
4. Keep Zotero Desktop running while the exporter runs.

The tool reads Zotero parent-item and child-attachment metadata from:

```text
http://127.0.0.1:23119/api/
```

It does not use Zotero cloud credentials and does not call publisher websites. The local API is only a lookup/indexing layer. Stored PDF discovery and reading happen from the Zotero storage directory on disk:

```text
{Zotero data directory}/storage/{attachmentKey}/
```

API fields such as `path`, `filename`, `contentType`, and `title` are hints only. The local PDF file is the authority.

## Install

From this repository:

```powershell
python -m pip install -e ".[dev]"
```

## Run

```powershell
python -m zotero_lit_md extract-zotero --collection "Protein precipitation" --storage-path "C:\Users\<USER>\Zotero\storage" --output ./literature_md --verbose
python -m zotero_lit_md extract-zotero --collection-key COLLECTIONKEY --storage-path "C:\Users\<USER>\Zotero\storage" --output ./literature_md
python -m zotero_lit_md extract-zotero --item-keys ABCD1234 EFGH5678 --storage-path "C:\Users\<USER>\Zotero\storage" --output ./literature_md --json-sidecar
python -m zotero_lit_md extract-storage --storage-path "C:\Users\<USER>\Zotero\storage" --output ./literature_md --all-pdfs --verbose
python -m zotero_lit_md extract-storage --storage-path "C:\Users\<USER>\Zotero\storage" --output ./literature_md --query "protein precipitation lysozyme"
python -m zotero_lit_md pdf-to-md --pdf "C:\path\to\paper.pdf" --output ./literature_md --verbose
python -m zotero_lit_md folder-to-md --folder "C:\Users\<USER>\Zotero\storage" --output ./literature_md --recursive --verbose
python -m zotero_lit_md trace-item --item-key ABCD1234 --storage-path "C:\Users\<USER>\Zotero\storage" --output ./trace_out --verbose
python -m zotero_lit_md doctor --storage-path "C:\Users\<USER>\Zotero\storage" --verbose
python -m zotero_lit_md from-folder ./pdfs --output ./literature_md
```

Useful options:

- `--collection`: Zotero collection key or exact collection name.
- `--saved-search`: Zotero saved search key or exact saved search name, if exposed by the local API.
- `--item-keys`: one or more Zotero parent item keys.
- `--all-with-pdfs`: process every item with PDF attachments.
- `--storage-path`: Zotero `storage` directory, for example `C:\Users\<USER>\Zotero\storage`.
- `--output`: output directory.
- `--json-sidecar`: write structured metadata/chunk diagnostics next to each Markdown file.
- `--combined-corpus`: write `combined_corpus.md`.
- `--overwrite`: replace existing outputs.
- `--max-papers`: cap processed papers.
- `--verbose`: print per-paper progress.
- `--ocr`: placeholder OCR fallback flag; OCR is off by default.
- `--zotero-data-dir`: explicit Zotero data directory. If omitted, the exporter checks `ZOTERO_DATA_DIR`, then common `~/Zotero` locations.
- `--first-pdf-only`: process only the first detected child attachment.

Primary commands:

- `pdf-to-md`: convert one local PDF to the required LLM-ready Markdown structure without using Zotero.
- `folder-to-md`: recursively or non-recursively convert every PDF in a local folder without using Zotero.
- `extract-zotero`: use Zotero's local API to select parent items and child attachment keys, then read PDFs from `{storage_path}/{attachmentKey}/`.
- `extract-storage`: bypass the API, scan the storage folder recursively, and process either `--all-pdfs` or PDFs matching `--query`.
- `trace-item`: write `zotero_lit_md_trace.json` showing parent item, child attachment keys, storage folders, PDFs found, selected PDF, extraction status, and Markdown output.
- `doctor`: validate storage first, then API reachability and API attachment-key mapping.

Legacy compatibility commands still exist: top-level selection flags, `scan-storage`, `extract-one-storage-key`, `extract-storage-folder`, `extract-one`, and `from-folder`.

`pdf-to-md` and `folder-to-md` are the foundation path: they do not resolve collections, item keys, attachment keys, or Zotero metadata. They find local PDFs, open them from disk, extract page text with PyMuPDF, preserve exposed scientific text without summarizing, and write one Markdown file per PDF. If a folder has no PDFs, `folder-to-md` prints `No PDFs found in: ...` and exits non-zero.

## Output

Each paper gets one Markdown file named with:

```text
{year}_{lead_author}_{short_title}.md
```

The body contains metadata, extraction diagnostics, abstract, keywords, a concept-map scaffold, extracted body text, retrieval chunks, and claim units. Images are omitted, but captions and page references are retained when the PDF text layer exposes them.

With `--json-sidecar`, a same-basename `.json` file contains metadata, diagnostics, section blocks, retrieval chunks, and claim units.

With `--combined-corpus`, all Markdown files are appended to `combined_corpus.md`.

## PDF Limitations

PDF text extraction depends on the local PDF text layer. The tool uses PyMuPDF first and pypdf as fallback. It does not invent missing text. Scanned, encrypted, or incomplete PDFs are marked in diagnostics and the exporter continues with remaining papers.

Tables, equations, and figure captions are preserved when exposed as text by the PDF. Images themselves are never embedded.

## LLM/RAG Use

Use the main Markdown body for faithful full-text ingestion. Use the retrieval chunk appendix for page-aware retrieval. Use the JSON sidecar when a downstream indexer needs structured metadata, page ranges, diagnostics, chunks, or claim units.

## Extraction Does Not Work

Start with the doctor command:

```powershell
python -m zotero_lit_md doctor --storage-path "C:\Users\<USER>\Zotero\storage" --verbose
```

It checks the Zotero data directory first, then the local storage folder, scans storage for PDFs, tries extracting text from one local PDF, and only then checks the Zotero local API and whether API attachment keys map to real storage folders.

To prove local storage discovery without Zotero's API:

```powershell
python -m zotero_lit_md extract-storage --storage-path "C:\Users\<USER>\Zotero\storage" --output ./literature_md --all-pdfs --verbose
python -m zotero_lit_md trace-item --item-key <ITEMKEY> --storage-path "C:\Users\<USER>\Zotero\storage" --output ./trace_out --verbose
```

If Zotero path resolution is the problem, debug one paper:

```powershell
python -m zotero_lit_md extract-zotero --item-keys <ITEMKEY> --storage-path "C:\Users\<USER>\Zotero\storage" --output ./debug_out --verbose
```

Verbose output prints parent item key/title, child attachment keys, each child attachment key/title/API path hint, the storage folder, whether it exists, PDFs found in the folder, the selected PDF, file size, PyMuPDF status, page count, extracted character count, and output Markdown path.

If PDF extraction itself is suspect, bypass Zotero entirely:

```powershell
python -m zotero_lit_md from-folder <folder-with-pdfs> --output ./literature_md --verbose
```

Zotero stored attachments often expose hints like:

```text
storage:paper.pdf
```

The exporter does not trust that hint as a complete path. It uses the child attachment key and inspects:

```text
{Zotero data directory}/storage/{attachmentKey}/
```

The `{attachmentKey}` is the child attachment item key, not the parent paper key. If multiple PDFs are present, metadata filename/path/title are used only to sort relevance. Linked-file attachments may expose a normal absolute filesystem path; those are handled separately when the path exists. Use `--zotero-data-dir` or the `ZOTERO_DATA_DIR` environment variable when the default Zotero data directory autodetection is wrong.
