---
paper_id: "zotero-DYAEYH3Y"
zotero_key: ""
title: "RELATE: Relation Extraction in Biomedical Abstracts with LLMs and Ontology Constraints"
authors:
  - "Olawumi Olasunkanmi"
  - "Mathew Satusky"
  - "Hong Yi"
  - "Chris Bizon"
  - "Harlin Lee"
  - "Stanley Ahalt"
year: 2025
journal: ""
doi: "10.48550/arxiv.2509.19057"
source_pdf: ""
raw_markdown: ""
source_collection: ""
extraction_method: "zotero"
extraction_date: "2026-06-19T07:26:21.454654+00:00"
cleanup_version: "phase2-cleanup-v1"
extraction_quality: "usable"
state: "imported"
zotero_item_key: ""
pdf_path: ""
pdf_sha256: ""
source_filename: ""
zotero_title: "RELATE: Relation Extraction in Biomedical Abstracts with LLMs and Ontology Constraints"
zotero_authors:
  - "Olawumi Olasunkanmi"
  - "Mathew Satusky"
  - "Hong Yi"
  - "Chris Bizon"
  - "Harlin Lee"
  - "Stanley Ahalt"
zotero_year: 2025
zotero_doi: "10.48550/arxiv.2509.19057"
metadata_title: "RELATE: Relation Extraction in Biomedical Abstracts with LLMs and Ontology Constraints"
detected_title: ""
detected_authors:
detected_doi: ""
title_similarity_score: null
doi_match_status: "unknown"
metadata_match_status: "unknown"
document_role: "unknown"
extraction_engine_used: "zotero"
extraction_engine_attempts:
page_count_pdf: 0
page_count_extracted: 0
word_count: 0
words_per_page: 0
pages_with_text: 0
section_count: 0
reference_count: 0
abstract_detected: false
references_detected: false
title_detected: false
repeated_header_footer_score: 0
table_equation_artifact_score: 0
requires_manual_review: false
exclude_from_llm_extraction: false
exclude_from_automatic_llm_extraction: false
include_in_llm_extraction: false
warnings:
created_at: "2026-06-19T07:26:21.454654+00:00"
updated_at: "2026-06-19T07:26:21.454654+00:00"
raw_markdown_file: ""
clean_markdown_file: ""
llm_context_file: ""
metadata_report_file: ""
quality_version: ""
id: "zotero-DYAEYH3Y"
source: "zotero"
imported_at: "2026-06-19T07:26:21.454654+00:00"
---

# RELATE: Relation Extraction in Biomedical Abstracts with LLMs and Ontology Constraints

## Abstract

Biomedical knowledge graphs (KGs) are vital for drug discovery and clinical decision support but remain incomplete. Large language models (LLMs) excel at extracting biomedical relations, yet their outputs lack standardization and alignment with ontologies, limiting KG integration. We introduce RELATE, a three-stage pipeline that maps LLM-extracted relations to standardized ontology predicates using ChemProt and the Biolink Model. The pipeline includes: (1) ontology preprocessing with predicate embeddings, (2) similarity-based retrieval enhanced with SapBERT, and (3) LLM-based reranking with explicit negation handling. This approach transforms relation extraction from free-text outputs to structured, ontology-constrained representations. On the ChemProt benchmark, RELATE achieves 52% exact match and 94% accuracy@10, and in 2,400 HEAL Project abstracts, it effectively rejects irrelevant associations (0.4%) and identifies negated assertions. RELATE captures nuanced biomedical relationships while ensuring quality for KG augmentation. By combining vector search with contextual LLM reasoning, RELATE provides a scalable, semantically accurate framework for converting unstructured biomedical literature into standardized KGs.

## Notes



## Extracted ontology-relevant information
