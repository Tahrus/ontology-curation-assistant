---
paper_id: "zotero-6HG9BV2N"
zotero_key: ""
title: "Solving crystallization/precipitation population balance models in CADET, part I: Nucleation growth and growth rate dispersion in batch and continuous modes on nonuniform grids"
authors:
  - "Wendi Zhang"
  - "Todd Przybycien"
  - "Johannes Schmölder"
  - "Samuel Leweke"
  - "Eric von Lieres"
year: 2024
journal: ""
doi: "10.1016/j.compchemeng.2024.108612"
source_pdf: ""
raw_markdown: ""
source_collection: ""
extraction_method: "zotero"
extraction_date: "2026-06-18T14:38:27.009845+00:00"
cleanup_version: "phase2-cleanup-v1"
extraction_quality: "usable"
metadata_title: "Solving crystallization/precipitation population balance models in CADET, part I: Nucleation growth and growth rate dispersion in batch and continuous modes on nonuniform grids"
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
id: "zotero-6HG9BV2N"
source: "zotero"
imported_at: "2026-06-18T14:38:27.009845+00:00"
---

# Solving crystallization/precipitation population balance models in CADET, part I: Nucleation growth and growth rate dispersion in batch and continuous modes on nonuniform grids

## Abstract

We have developed, implemented and validated 1D and 2D population balance models (PBMs) in the open-source process simulator CADET. 1D PBMs incorporate the particle size as an internal coordinate and are associated with dynamic mass balances to describe particle-based processes in batch and continuous stirred tank reactors. 2D PBMs include the spatial position as an additional external coordinate to describe particulate systems in dispersive plug flow reactors. Along with particle nucleation and growth, growth rate dispersion is considered. Using the finite volume method, cell face fluxes are reconstructed by upwind, Koren and two weighted essentially non-oscillatory (WENO) schemes. Analytical Jacobians are derived to reduce runtime. The implementations utilize arbitrary grids in the internal coordinate. The implementations are validated and benchmarked using seven test cases. The L1 error norm, L1 error convergence rate, and moments up to sixth order are analyzed. Runtime and approximation errors are reported and discussed in detail.

## Notes

## Extracted ontology-relevant information
