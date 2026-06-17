# Ontology Graph And Tree

The default ontology visualization is a focused top-down taxonomy tree, not a circular graph or force-directed graph.

## Files

- Tree endpoint and ontology parsing: `backend/app/ontology/local.py`
- API route: `GET /api/ontology/tree` in `backend/app/api/routes.py`
- Frontend renderer: `backend/app/static/app.js`
- Markup and controls: `backend/app/static/index.html`
- Styles: `backend/app/static/styles.css`
- Tests: `backend/tests/test_browser_api.py`

## Data Model

Hierarchy edges and semantic edges are separate:

```json
{"source": "parent_id", "target": "child_id", "relation": "is_a", "edgeType": "hierarchy"}
```

```json
{"source": "class_id_1", "target": "class_id_2", "relation": "part_of", "edgeType": "semantic"}
```

Only `edgeType: "hierarchy"` edges determine node positions. Semantic relation edges are drawn after layout as optional dashed side links and do not change parent/child placement.

## Browser Behavior

The Ontology page and Candidate Curation graph panel share the same tree renderer. Users can search by label, identifier, synonym, or relation endpoint; focus on a selected node; reset to top-level overview; expand/collapse branches; set depth; zoom/pan/fit/center; toggle node labels; toggle semantic relation labels; and toggle semantic relation visibility.

Selecting a node visibly highlights that node, dims unrelated visible nodes, and updates the details panel. Direct context nodes remain emphasized: the selected class, direct parents, direct subclasses, and directly connected semantic relation endpoints. The panel shows label, identifier/IRI, definition, synonyms, parent/superclass values, direct subclasses, semantic relations, source path, and status. Missing metadata is shown as `not available`.

The graph summary below the SVG displays the current mode, visible class count, total class count, source file path/status, and selected node label/ID. This makes it possible to verify that the active view is using the selected local/project ontology payload rather than demo data.

`Focus on selected class` switches the view to the selected node's local context and enables lateral relation display on the Ontology page so directly connected semantic relations can be inspected. `Reset overview` clears focus, selection, collapsed state, root/search filters, and viewport transform.

## Active Implementation

- Active page markup: `backend/app/static/index.html`
- Active renderer and click handling: `backend/app/static/app.js`
- Active styles: `backend/app/static/styles.css`
- Active endpoint: `GET /api/ontology/tree`
- Backend route: `ontology_tree()` in `backend/app/api/routes.py`
- Payload builder: `ontology_tree_payload()` in `backend/app/ontology/local.py`

Node selection and local context are frontend-only inspection state. They do not edit ontology relations, candidate review data, database schema, literature data, or ODK/ROBOT exports.

## Known Limitations

- The tree uses the currently indexed selected ontology file or project ontology source; malformed selected ontology files surface controlled errors instead of rendering partial data.
- The frontend has static regression coverage for the active graph controls and helpers, but there is not yet a dedicated JavaScript unit-test harness for clicking SVG nodes.
- Focus mode is intentionally local inspection, not a full ontology editor. Semantic relation endpoints are shown for context, but graphical relation editing is out of scope.
