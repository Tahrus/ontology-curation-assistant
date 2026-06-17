# Curation Workflow

Candidate curation is human-in-the-loop. LLM output and graph-assisted proposals are review material, not direct ontology mutations.

## Files

- Candidate routes and payloads: `backend/app/api/routes.py`
- Candidate database model: `CandidateTermRecord` in `backend/app/models/db.py`
- Browser curation page: `backend/app/static/index.html`, `backend/app/static/app.js`
- Relation catalogue: `backend/app/ontology/relations.py`
- Export logic: `backend/app/review/`, `backend/app/odk/`

## Candidate Review

Candidates can be created manually, imported from deterministic extraction, or suggested by a configured LLM. Active candidates include draft, in-review, deferred, and needs-more-evidence records. Approved and rejected candidates leave the active queue; permanent rejections can be listed and restored.

The curation graph panel lets reviewers select ontology nodes and save graph-review context:

- proposed parent class
- relation source
- relation target
- duplicate target
- comparison note
- proposed semantic relations

These values are stored in `CandidateTermRecord.graph_review_json` and returned as `graph_review`. Proposed relations are previewed as dashed edges in the tree but are not written into the ontology until an approved export or downstream ODK workflow handles them.

## Manual Verification

1. Start the app and open `/curation`.
2. Select or create a candidate.
3. Select an ontology node in the graph panel.
4. Use graph action buttons to set parent/source/target or add a proposed relation.
5. Reload the page and confirm the graph-review fields persist.
6. Confirm approved/rejected candidates leave the active queue and exports include only approved content.

