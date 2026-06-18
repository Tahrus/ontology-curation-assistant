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
extraction_date: "2026-06-18T14:38:27.130036+00:00"
cleanup_version: "phase2-cleanup-v1"
extraction_quality: "usable"
metadata_title: "RELATE: Relation Extraction in Biomedical Abstracts with LLMs and Ontology Constraints"
detected_title: ""
title_similarity_score: null
metadata_match_status: "unknown"
document_role: "unknown"
requires_manual_review: false
exclude_from_automatic_llm_extraction: false
include_in_llm_extraction: false
raw_markdown_file: ""
clean_markdown_file: ""
llm_context_file: ""
metadata_report_file: ""
quality_version: ""
id: "zotero-DYAEYH3Y"
source: "zotero"
imported_at: "2026-06-18T14:38:27.130036+00:00"
---

# RELATE: Relation Extraction in Biomedical Abstracts with LLMs and Ontology Constraints

## Abstract

Biomedical knowledge graphs (KGs) are vital for drug discovery and clinical decision support but remain incomplete. Large language models (LLMs) excel at extracting biomedical relations, yet their outputs lack standardization and alignment with ontologies, limiting KG integration. We introduce RELATE, a three-stage pipeline that maps LLM-extracted relations to standardized ontology predicates using ChemProt and the Biolink Model. The pipeline includes: (1) ontology preprocessing with predicate embeddings, (2) similarity-based retrieval enhanced with SapBERT, and (3) LLM-based reranking with explicit negation handling. This approach transforms relation extraction from free-text outputs to structured, ontology-constrained representations. On the ChemProt benchmark, RELATE achieves 52% exact match and 94% accuracy@10, and in 2,400 HEAL Project abstracts, it effectively rejects irrelevant associations (0.4%) and identifies negated assertions. RELATE captures nuanced biomedical relationships while ensuring quality for KG augmentation. By combining vector search with contextual LLM reasoning, RELATE provides a scalable, semantically accurate framework for converting unstructured biomedical literature into standardized KGs.

## Notes



## Extracted ontology-relevant information
