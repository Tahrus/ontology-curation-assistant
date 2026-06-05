const state = {
  status: null,
  documents: [],
  entries: [],
  candidates: [],
  rejectedCandidates: [],
  ontologyFiles: [],
  ontologyTerms: [],
  savedConfigs: [],
  curationPrompt: null,
  temporaryRejectedIds: new Set(JSON.parse(sessionStorage.getItem("oca-temp-rejected") || "[]")),
  graphPreferences: JSON.parse(localStorage.getItem("oca-graph-preferences") || "{}"),
};

const APP_ROUTES = {
  "/": "dashboard",
  "/config": "config",
  "/zotero": "zotero",
  "/literature": "zotero",
  "/ontology": "ontology",
  "/curation-prompt": "curation-prompt",
  "/curation": "curation",
  "/export": "export",
};

const ACTIVE_CANDIDATE_STATUSES = new Set(["new", "in_review", "needs_more_evidence", "deferred"]);

function normalizeText(value) {
  return String(value ?? "").normalize("NFKC").toLowerCase();
}

function safeText(value, fallback = "") {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function searchableText(value) {
  try {
    return normalizeText(JSON.stringify(value));
  } catch {
    return normalizeText(value);
  }
}

function flattenSections(sections = []) {
  const flattened = [];
  (Array.isArray(sections) ? sections : []).forEach((section) => {
    flattened.push(section);
    flattened.push(...flattenSections(section?.subsections || []));
  });
  return flattened;
}

function sectionPreviewText(entry) {
  if (entry.literature_markdown) {
    return entry.literature_markdown.replace(/^---[\s\S]*?---\s*/m, "").slice(0, 700);
  }
  const content = entry.content || {};
  const pdfText = {};
  const sections = flattenSections(content.sections || pdfText.sections || []);
  if (sections.length) {
    return sections.map((section) => section.text || "").filter(Boolean).join("\n\n").slice(0, 700);
  }
  if (content.full_text) return safeText(content.full_text).slice(0, 700);
  if (pdfText.text) return safeText(pdfText.text).slice(0, 700);
  const pageText = (Array.isArray(pdfText.pages) ? pdfText.pages : [])
    .map((page) => page?.text || "")
    .filter(Boolean)
    .join("\n\n");
  return pageText ? pageText.slice(0, 700) : safeText(entry.abstract, "No extracted text available.");
}

function graphPreference(name) {
  return {
    showText: true,
    showNodeLabels: true,
    showEdgeLabels: true,
    showDescriptions: true,
    simplify: false,
    ...(state.graphPreferences[name] || {}),
  };
}

function setGraphPreference(name, key, value) {
  state.graphPreferences[name] = { ...graphPreference(name), [key]: value };
  localStorage.setItem("oca-graph-preferences", JSON.stringify(state.graphPreferences));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || response.statusText);
  }
  return response.json();
}

function formPayload(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function csv(value) {
  return Array.isArray(value) ? value.join("; ") : "";
}

function parseCsv(value) {
  return value.split(";").map((item) => item.trim()).filter(Boolean);
}

function currentPage() {
  return APP_ROUTES[window.location.pathname] || "dashboard";
}

function showCurrentPage() {
  const page = currentPage();
  document.querySelectorAll(".page-section").forEach((section) => {
    section.classList.toggle("is-active", section.dataset.page === page);
  });
  document.querySelectorAll("[data-nav]").forEach((link) => {
    link.classList.toggle("is-active", link.dataset.nav === page);
  });
}

async function refreshCurrentPageData() {
  const page = currentPage();
  if (page === "dashboard") {
    await loadStatus();
  } else if (page === "config") {
    await Promise.all([loadStatus(), loadSavedConfigs()]);
  } else if (page === "zotero") {
    await loadEntries();
  } else if (page === "ontology") {
    await loadOntologyStatus();
  } else if (page === "curation-prompt") {
    await Promise.all([loadStatus(), loadCurationPrompt()]);
  } else if (page === "curation") {
    await Promise.all([loadEntries(), loadCandidates()]);
  }
}

function navigateTo(path) {
  const page = APP_ROUTES[path] ? path : "/";
  if (window.location.pathname !== page) {
    window.history.pushState({}, "", page);
  }
  showCurrentPage();
  refreshCurrentPageData().catch((error) => {
    setAppStatus(`Could not load ${currentPage()} data: ${error.message}`, "error");
  });
  window.scrollTo({ top: 0, behavior: "auto" });
}

function applyTheme(theme) {
  const resolved = theme || localStorage.getItem("oca-theme") ||
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.dataset.theme = resolved;
  if (document.body) {
    document.body.dataset.theme = resolved;
  }
  document.documentElement.style.colorScheme = resolved;
  localStorage.setItem("oca-theme", resolved);
  document.querySelector("#theme-light").setAttribute("aria-pressed", String(resolved === "light"));
  document.querySelector("#theme-dark").setAttribute("aria-pressed", String(resolved === "dark"));
}

function setMessage(selector, message) {
  const node = document.querySelector(selector);
  if (!node) return;
  node.textContent = message;
  node.classList.remove("success", "error");
}

function setSuccess(selector, message) {
  const node = document.querySelector(selector);
  if (!node) return;
  node.textContent = message;
  node.classList.remove("error");
  node.classList.add("success");
}

function setError(selector, message) {
  const node = document.querySelector(selector);
  if (!node) return;
  node.textContent = message;
  node.classList.remove("success");
  node.classList.add("error");
}

function setAppStatus(message, kind = "") {
  const node = document.querySelector("#app-status");
  node.textContent = message;
  node.classList.remove("success", "error");
  if (kind) node.classList.add(kind);
}

let toastTimer = null;

function showActionToast(message, kind = "") {
  const toast = document.querySelector("#action-toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.remove("error");
  if (kind === "error") toast.classList.add("error");
  toast.classList.add("is-visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 2800);
}

function actionLabel(element) {
  const label = element?.getAttribute?.("aria-label") || element?.textContent || element?.value || "Action";
  return safeText(label).replace(/\s+/g, " ").trim().slice(0, 80) || "Action";
}

function acknowledgeAction(element, message = null) {
  if (!element || element.getAttribute?.("aria-disabled") === "true" || element.disabled) return;
  element.classList?.add("is-clicked");
  window.setTimeout(() => element.classList?.remove("is-clicked"), 260);
  showActionToast(message || `${actionLabel(element)} selected.`);
}

async function withButtonFeedback(button, busyText, action) {
  const originalText = button.textContent;
  button.disabled = true;
  button.classList.add("is-busy");
  button.setAttribute("aria-busy", "true");
  button.textContent = busyText;
  showActionToast(`${busyText}...`);
  try {
    const result = await action();
    showActionToast(`${originalText} complete.`);
    return result;
  } catch (error) {
    showActionToast(`Error: ${error.message}`, "error");
    throw error;
  } finally {
    button.textContent = originalText;
    button.classList.remove("is-busy");
    button.removeAttribute("aria-busy");
    button.disabled = false;
  }
}

async function loadStatus() {
  state.status = await api("/api/config/status");
  setAppStatus(
    `${state.status.backend.app_name} | Zotero ${state.status.zotero.configured ? "configured" : "not configured"} | LLM ${state.status.llm.configured ? "configured" : "mock only"}`
  );

  const grid = document.querySelector("#status-grid");
  grid.innerHTML = "";
  [
    ["Backend", state.status.backend.ok ? "Ready" : "Unavailable"],
    ["Database", state.status.database.ok ? "Ready" : "Unavailable"],
    ["Zotero", state.status.zotero.configured ? `Ready (${state.status.zotero.library_type})` : "Missing library settings"],
    ["LLM", state.status.llm.configured ? `Ready (${state.status.llm.provider})` : "Mock extraction available"],
    ["Zotero literature storage", state.status.literature.zotero_literature_storage_path_exists ? "Ready" : "Missing path"],
    ["Ontology", state.status.ontology.selected_file || state.status.ontology.path || "Not configured"],
  ].forEach(([label, value]) => {
    const card = document.createElement("div");
    card.className = "status-card";
    card.innerHTML = `<strong>${label}</strong><span>${value}</span>`;
    grid.append(card);
  });
  populateLiteratureConfigForm();
  await renderMetaGraph();
}

function populateLiteratureConfigForm() {
  const form = document.querySelector("#literature-config-form");
  if (!form || !state.status?.literature) return;
  const literature = state.status.literature;
  [
    ["zotero_literature_storage_path", literature.zotero_literature_storage_path],
  ].forEach(([name, value]) => {
    const input = form.querySelector(`[name="${name}"]`);
    if (input && value !== undefined && value !== null) input.value = value;
  });
}

async function loadDocuments() {
  state.documents = await api("/api/literature");
}

async function loadEntries() {
  state.entries = await api("/api/zotero/entries");
  renderEntries();
}

function renderEntries() {
  const list = document.querySelector("#zotero-entries");
  list.innerHTML = "";

  const query = normalizeText(document.querySelector("#zotero-filter")?.value);
  state.entries.filter((entry) => {
    if (!query) return true;
    return searchableText(entry).includes(query);
  }).forEach((entry) => {
    const authors = (Array.isArray(entry.creators) ? entry.creators : [])
      .map((creator) => [creator?.given, creator?.family].filter(Boolean).map(safeText).join(" "))
      .filter(Boolean)
      .join("; ");
    const record = document.createElement("article");
    record.className = "literature-record";

    const header = document.createElement("header");
    const text = document.createElement("div");
    const title = document.createElement("strong");
    title.className = "literature-title";
    title.textContent = safeText(entry.title, "Untitled Zotero record");
    const meta = document.createElement("p");
    meta.className = "literature-meta";
    meta.textContent = [
      authors,
      entry.year,
      entry.publication_venue || entry.journal || entry.item_type,
      entry.doi ? `DOI ${entry.doi}` : "",
      entry.provider_item_key ? `Zotero key ${entry.provider_item_key}` : "",
    ].filter(Boolean).map(safeText).join(" | ") || "No bibliographic metadata available.";
    const abstract = document.createElement("p");
    abstract.textContent = sectionPreviewText(entry);
    text.append(title, meta, abstract);

    const actions = document.createElement("div");
    actions.className = "button-row";

    const zoteroLink = document.createElement("a");
    zoteroLink.textContent = entry.zotero_select_uri ? "Open in Zotero" : "Zotero link unavailable";
    if (entry.zotero_select_uri) {
      zoteroLink.href = entry.zotero_select_uri;
    } else {
      zoteroLink.href = "#";
      zoteroLink.className = "is-disabled";
      zoteroLink.setAttribute("aria-disabled", "true");
      zoteroLink.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
      });
    }

    actions.append(zoteroLink);
    header.append(text, actions);

    const details = document.createElement("details");
    details.className = "markdown-details";
    const summary = document.createElement("summary");
    const content = entry.content || {};
    const pdfText = {};
    const sectionList = flattenSections(content.sections || pdfText.sections || []);
    const markdownText = entry.literature_markdown || sectionPreviewText(entry);
    summary.textContent = `Show Markdown record (${sectionList.length || entry.literature_status?.section_count || 0} extracted sections)`;
    const diagnostics = document.createElement("div");
    diagnostics.className = "json-diagnostics";
    diagnostics.innerHTML = "";
    [
      ["Markdown file", entry.literature_status?.markdown_source_file],
      ["Extraction status", content.extraction_status || pdfText.status],
      ["Canonical source", content.canonical_source || pdfText.source],
      ["Structure", "Markdown sections"],
      ["Diagnostics", content.diagnostics?.errors?.[0]?.message || pdfText.diagnostics?.error_code || pdfText.diagnostics?.message],
    ].filter(([, value]) => value).forEach(([label, value]) => {
      const line = document.createElement("p");
      line.textContent = `${label}: ${safeText(value)}`;
      diagnostics.append(line);
    });
    if (sectionList.length) {
      const headingList = document.createElement("ul");
      headingList.className = "section-heading-list";
      sectionList.slice(0, 20).forEach((section) => {
        const item = document.createElement("li");
        item.textContent = `${section.heading || "Untitled section"} (${section.page_start || "?"}-${section.page_end || "?"})`;
        headingList.append(item);
      });
      diagnostics.append(headingList);
    }
    const pre = document.createElement("pre");
    pre.className = "markdown-preview";
    pre.textContent = markdownText;
    details.append(summary, diagnostics, pre);

    record.append(header, details);
    list.append(record);
  });
  if (!list.children.length) {
    list.innerHTML = '<p class="message">No literature records found.</p>';
  }
}

async function loadCandidates() {
  state.candidates = await api("/api/candidates");
  state.rejectedCandidates = await api("/api/candidates/rejected");
  const list = document.querySelector("#candidate-list");
  const template = document.querySelector("#candidate-template");
  list.innerHTML = "";
  state.candidates.filter((candidate) =>
    ACTIVE_CANDIDATE_STATUSES.has(candidate.review_status) &&
    !state.temporaryRejectedIds.has(candidate.id)
  ).forEach((candidate) => {
    const node = template.content.firstElementChild.cloneNode(true);
    fillCandidate(node, candidate);
    list.append(node);
  });
  if (!list.children.length) {
    list.innerHTML = '<p class="message">No active candidates need curation.</p>';
  }
  renderRejectedCandidates();
}

async function loadCurationPrompt() {
  state.curationPrompt = await api("/api/curation/prompt");
  const form = document.querySelector("#curation-prompt-form");
  if (!form) return;
  form.querySelector('[name="prompt"]').value = state.curationPrompt.prompt || "";
  const literaturePath = state.status?.literature?.combined_output_file || "literature/combined_literature.md";
  const ontologyPath = state.status?.ontology?.selected_file || "No existing ontology OBO selected";
  setMessage(
    "#curation-prompt-message",
    `Inputs for curation: prompt template, ontology ${ontologyPath}, literature ${literaturePath}.`
  );
}

function fillCandidate(node, candidate) {
  node.dataset.id = candidate.id;
  node.querySelector(".label").value = candidate.label || "";
  node.querySelector(".status").value = candidate.review_status || "new";
  node.querySelector(".candidate-source").textContent = `Source document: ${candidate.document_id}`;
  node.querySelector(".definition").value = candidate.proposed_definition || "";
  node.querySelector(".rationale").value = candidate.curator_rationale || "";
  node.querySelector(".source-evidence").value =
    candidate.source_evidence ||
    (candidate.evidence?.[0]?.quoted_text ? candidate.evidence[0].quoted_text : "");
  node.querySelector(".mappings").value = csv(candidate.mappings || []);
  node.querySelector(".synonyms").value = csv(candidate.synonyms || []);
  node.querySelector(".parent").value = candidate.proposed_parent || "";
  node.querySelector(".decision").value = candidate.curator_decision || "needs_review";
  renderLocalMatches(node, candidate);
  renderOlsMatches(node, candidate);

  node.querySelector(".save").addEventListener("click", (event) =>
    withButtonFeedback(event.currentTarget, "Saving", () => saveCandidate(node))
  );
  node.querySelector(".approve").addEventListener("click", (event) =>
    withButtonFeedback(event.currentTarget, "Approving", () => reviewCandidate(node, "approved"))
  );
  node.querySelector(".reject").addEventListener("click", (event) =>
    withButtonFeedback(event.currentTarget, "Rejecting", () => reviewCandidate(node, "rejected"))
  );
  node.querySelector(".permanent-reject").addEventListener("click", (event) =>
    withButtonFeedback(event.currentTarget, "Rejecting", () => permanentlyRejectCandidate(node))
  );
  node.querySelector(".ols").addEventListener("click", (event) =>
    withButtonFeedback(event.currentTarget, "Checking", () => checkOls(node))
  );
  node.querySelector(".local-match").addEventListener("click", (event) =>
    withButtonFeedback(event.currentTarget, "Checking", () => checkLocal(node))
  );
  node.querySelector(".new-term").addEventListener("click", (event) =>
    withButtonFeedback(event.currentTarget, "Marking", () => markNewTerm(candidate.id))
  );
}

function payloadFromNode(node) {
  return {
    label: node.querySelector(".label").value,
    review_status: node.querySelector(".status").value,
    proposed_definition: node.querySelector(".definition").value,
    curator_rationale: node.querySelector(".rationale").value,
    source_evidence: node.querySelector(".source-evidence").value,
    mappings: parseCsv(node.querySelector(".mappings").value),
    synonyms: parseCsv(node.querySelector(".synonyms").value),
    proposed_parent: node.querySelector(".parent").value,
    curator_decision: node.querySelector(".decision").value,
  };
}

async function saveCandidate(node) {
  await api(`/api/candidates/${node.dataset.id}`, {
    method: "PATCH",
    body: JSON.stringify(payloadFromNode(node)),
  });
  await loadCandidates();
  setSuccess("#ols-message", "Candidate saved.");
}

async function reviewCandidate(node, status) {
  await api(`/api/candidates/${node.dataset.id}/review`, {
    method: "POST",
    body: JSON.stringify({ status, rationale: node.querySelector(".rationale").value }),
  });
  await loadCandidates();
  setSuccess("#ols-message", `Candidate marked ${status}.`);
}

async function permanentlyRejectCandidate(node) {
  const reason = window.prompt("Reason for permanent rejection?") || null;
  await api(`/api/candidates/${node.dataset.id}/permanent-reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
  await loadCandidates();
  setSuccess("#ols-message", "Candidate permanently rejected.");
}

async function restoreCandidate(candidateId) {
  try {
    await api(`/api/candidates/${candidateId}/restore`, { method: "POST", body: "{}" });
    state.temporaryRejectedIds.delete(candidateId);
    sessionStorage.setItem("oca-temp-rejected", JSON.stringify([...state.temporaryRejectedIds]));
    await loadCandidates();
    setSuccess("#ols-message", "Candidate restored to active review.");
  } catch (error) {
    setError("#ols-message", error.message);
    showActionToast(`Error: ${error.message}`, "error");
    throw error;
  }
}

function renderRejectedCandidates() {
  const list = document.querySelector("#rejected-candidate-list");
  list.innerHTML = "";
  state.rejectedCandidates.forEach((candidate) => {
    const row = document.createElement("div");
    row.className = "rejected-row";
    row.innerHTML = `<strong>${candidate.label}</strong>
      <p>Status: ${candidate.review_status} | Decision: ${candidate.curator_decision}</p>
      <p>Source document: ${candidate.document_id || "unknown"}</p>
      <p>Rejected: ${candidate.permanently_rejected_at || "unknown"}</p>
      <p>Reason: ${candidate.rejection_reason || "none"}</p>
      <div class="button-row">
        <button type="button" class="restore">Restore to active review</button>
        <a href="/curation">Curate</a>
      </div>`;
    row.querySelector(".restore").addEventListener("click", (event) =>
      withButtonFeedback(event.currentTarget, "Restoring", () => restoreCandidate(candidate.id))
    );
    list.append(row);
  });
  if (!state.rejectedCandidates.length) {
    list.innerHTML = '<p class="message">No permanently rejected candidates.</p>';
  }
}

async function checkOls(node) {
  await api(`/api/candidates/${node.dataset.id}/ols`, { method: "POST", body: "{}" });
  await loadCandidates();
  setSuccess("#ols-message", "OLS lookup complete.");
}

async function checkLocal(node) {
  await api(`/api/candidates/${node.dataset.id}/match-local-ontology`, { method: "POST", body: "{}" });
  await loadCandidates();
  setSuccess("#ols-message", "Local PPO lookup complete.");
}

async function selectOls(candidateId, match) {
  try {
    await api(`/api/candidates/${candidateId}/ols-selection`, {
      method: "POST",
      body: JSON.stringify({ match }),
    });
    await loadCandidates();
    setSuccess("#ols-message", match ? "OLS mapping selected." : "Candidate marked as a new proposed term.");
  } catch (error) {
    setError("#ols-message", error.message);
    showActionToast(`Error: ${error.message}`, "error");
  }
}

async function selectLocal(candidateId, match) {
  try {
    await api(`/api/candidates/${candidateId}/select-local-match`, {
      method: "POST",
      body: JSON.stringify({ match }),
    });
    await loadCandidates();
    setSuccess("#ols-message", match ? "Local PPO match selected." : "No local PPO match selected.");
  } catch (error) {
    setError("#ols-message", error.message);
    showActionToast(`Error: ${error.message}`, "error");
  }
}

async function markNewTerm(candidateId) {
  await api(`/api/candidates/${candidateId}/ols-selection`, {
    method: "POST",
    body: JSON.stringify({ match: null }),
  });
  await api(`/api/candidates/${candidateId}/select-local-match`, {
    method: "POST",
    body: JSON.stringify({ match: null }),
  });
  await api(`/api/candidates/${candidateId}/decision`, {
    method: "POST",
    body: JSON.stringify({ decision: "propose_new_term" }),
  });
  await loadCandidates();
  setSuccess("#ols-message", "Candidate marked as a new term proposal.");
}

function renderLocalMatches(node, candidate) {
  const container = node.querySelector(".local-matches");
  container.innerHTML = "";
  const empty = document.createElement("label");
  empty.className = "match-choice";
  empty.innerHTML = `<input type="radio" name="local-${candidate.id}" ${candidate.selected_local ? "" : "checked"} />
    <span><strong>Nothing selected</strong><p>No matching existing PPO term selected.</p></span>`;
  empty.querySelector("input").addEventListener("change", () => selectLocal(candidate.id, null));
  container.append(empty);

  if (candidate.local_lookup_status === "not_run") {
    const note = document.createElement("p");
    note.className = "message";
    note.textContent = "Local ontology lookup has not been run.";
    container.append(note);
  }

  (candidate.local_matches || []).forEach((match) => {
    const row = document.createElement("label");
    row.className = "match-choice";
    row.innerHTML = `<input type="radio" name="local-${candidate.id}" ${candidate.selected_local?.iri === match.iri ? "checked" : ""} />
      <span>
        <strong>${match.label}</strong>
        <p>${match.term_id || match.iri} | confidence ${Math.round(match.score * 100)}%</p>
        <p>${match.definition || ""}</p>
      </span>`;
    row.querySelector("input").addEventListener("change", () => selectLocal(candidate.id, match));
    container.append(row);
  });
}

function renderOlsMatches(node, candidate) {
  const container = node.querySelector(".ols-matches");
  container.innerHTML = "";
  const empty = document.createElement("label");
  empty.className = "match-choice";
  empty.innerHTML = `<input type="radio" name="ols-${candidate.id}" ${candidate.selected_ols ? "" : "checked"} />
    <span><strong>Nothing selected</strong><p>No matching existing OLS term selected.</p></span>`;
  empty.querySelector("input").addEventListener("change", () => selectOls(candidate.id, null));
  container.append(empty);

  if (candidate.ols_lookup_status === "not_run") {
    const note = document.createElement("p");
    note.className = "message";
    note.textContent = "OLS lookup has not been run.";
    container.append(note);
  }
  (candidate.ols_matches || []).forEach((match) => {
    const row = document.createElement("label");
    row.className = "match-choice";
    row.innerHTML = `<input type="radio" name="ols-${candidate.id}" ${candidate.selected_ols?.iri === match.iri ? "checked" : ""} />
      <span>
      <strong>${match.label}</strong> <span>${match.ontology_id}</span>
      <p>${match.term_id || match.iri} | confidence ${Math.round(match.score * 100)}%</p>
      <p>${match.description || ""}</p></span>`;
    row.querySelector("input").addEventListener("change", () => selectOls(candidate.id, match));
    container.append(row);
  });
}

document.querySelector("#zotero-config-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const payload = formPayload(event.currentTarget);
  try {
    await withButtonFeedback(button, "Saving", async () => {
      await api("/api/config/zotero", {
        method: "POST",
        body: JSON.stringify({
          library_type: payload.library_type,
          library_id: payload.library_id,
          api_key: payload.api_key || null,
          collection_key: payload.collection_key || null,
          base_url: payload.base_url || null,
        }),
      });
      event.currentTarget.querySelector('[name="api_key"]').value = "";
      await loadStatus();
      await loadSavedConfigs();
      setSuccess("#zotero-message", "Zotero configuration saved.");
    });
  } catch (error) {
    setError("#zotero-message", error.message);
  }
});

document.querySelector("#llm-config-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const payload = formPayload(event.currentTarget);
  try {
    await withButtonFeedback(button, "Saving", async () => {
      await api("/api/config/llm", {
        method: "POST",
        body: JSON.stringify({
          provider: payload.provider,
          api_key: payload.api_key || null,
          model: payload.model || null,
          base_url: payload.base_url || null,
        }),
      });
      event.currentTarget.querySelector('[name="api_key"]').value = "";
      await loadStatus();
      await loadSavedConfigs();
      setSuccess("#extract-message", "LLM configuration saved.");
    });
  } catch (error) {
    setError("#extract-message", error.message);
  }
});

document.querySelector("#literature-config-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const payload = formPayload(event.currentTarget);
  try {
    await withButtonFeedback(button, "Saving", async () => {
      await api("/api/config/literature", {
        method: "POST",
        body: JSON.stringify({
          zotero_literature_storage_path: payload.zotero_literature_storage_path || null,
        }),
      });
      await loadStatus();
      setSuccess("#literature-config-message", "Literature pipeline configuration saved.");
    });
  } catch (error) {
    setError("#literature-config-message", error.message);
  }
});

document.querySelector("#run-literature-pipeline").addEventListener("click", async (event) => {
  try {
    setMessage("#literature-import-message", "Importing Zotero PDFs and generating Markdown...");
    await withButtonFeedback(event.currentTarget, "Importing", async () => {
      const result = await api("/api/literature/pipeline/run", { method: "POST", body: "{}" });
      setSuccess(
        "#literature-import-message",
        `Import complete. Copied ${result.copied_pdf_count} PDF(s), generated ${result.converted_markdown_count} Markdown file(s), combined ${result.combined_markdown_count} literature record(s).`
      );
      await loadStatus();
      await loadEntries();
    });
  } catch (error) {
    setError("#literature-import-message", error.message);
  }
});

async function loadSavedConfigs() {
  state.savedConfigs = await api("/api/config/saved");
  const list = document.querySelector("#saved-configs");
  list.innerHTML = "";
  state.savedConfigs.forEach((config) => {
    const row = document.createElement("div");
    row.className = "saved-config-row";
    row.innerHTML = `<strong>${config.alias || config.kind}</strong>
      <p>${config.kind} ${config.active ? "| active" : ""}</p>
      <p>${[config.provider, config.library_type, config.library_id, config.base_url, config.model].filter(Boolean).map(safeText).join(" | ")}</p>
      <p>Secret: ${config.api_key || "not configured"} | Updated: ${config.updated_at || ""}</p>
      <div class="button-row">
        <button type="button" class="activate">Activate</button>
        <button type="button" class="delete danger">Delete</button>
      </div>`;
    row.querySelector(".activate").addEventListener("click", async () => {
      try {
        await withButtonFeedback(row.querySelector(".activate"), "Activating", async () => {
          await api(`/api/config/saved/${config.id}/activate`, { method: "POST", body: "{}" });
          await loadStatus();
          await loadSavedConfigs();
          setSuccess("#zotero-message", "Saved configuration activated.");
        });
      } catch (error) {
        setError("#zotero-message", error.message);
      }
    });
    row.querySelector(".delete").addEventListener("click", async () => {
      try {
        await withButtonFeedback(row.querySelector(".delete"), "Deleting", async () => {
          await api(`/api/config/saved/${config.id}`, { method: "DELETE" });
          await loadSavedConfigs();
          setSuccess("#zotero-message", "Saved configuration deleted.");
        });
      } catch (error) {
        setError("#zotero-message", error.message);
      }
    });
    list.append(row);
  });
  if (!state.savedConfigs.length) {
    list.innerHTML = '<p class="message">No saved configurations yet.</p>';
  }
}

document.querySelector("#test-zotero").addEventListener("click", async (event) => {
  try {
    await withButtonFeedback(event.currentTarget, "Testing", async () => {
      const result = await api("/api/config/test-zotero", { method: "POST", body: "{}" });
      setSuccess("#zotero-message", `Zotero connection ok. Items seen: ${result.items_seen}`);
    });
  } catch (error) {
    setError("#zotero-message", error.message);
  }
});

document.querySelector("#sync-zotero").addEventListener("click", async (event) => {
  try {
    await withButtonFeedback(event.currentTarget, "Syncing", async () => {
      const useLimit = document.querySelector("#zotero-use-limit").checked;
      const limit = useLimit ? Number(document.querySelector("#zotero-limit").value || 0) || null : null;
      const result = await api("/api/zotero/sync", {
        method: "POST",
        body: JSON.stringify({ limit }),
      });
      setSuccess("#zotero-message", `Fetched ${result.fetched}; inserted ${result.inserted}; updated ${result.updated}; skipped ${result.skipped}.`);
      await loadEntries();
    });
  } catch (error) {
    setError("#zotero-message", error.message);
  }
});

async function loadOntologyStatus() {
  try {
    const status = await api("/api/ontology/status");
    const input = document.querySelector('#ontology-path-form [name="path"]');
    input.value = status.path || "";
    renderOntologyFiles(status.scan?.files || [], status.selected_file);
    const statusError = status.error ? ` Selected file error: ${status.error}` : "";
    setMessage("#ontology-message", `${status.scan?.message || "Ontology status loaded."} Parsed terms: ${status.term_count}.${statusError}`);
    await loadOntologyTerms();
  } catch (error) {
    state.ontologyTerms = [];
    document.querySelector("#ontology-terms").innerHTML = '<p class="message">Ontology terms are unavailable.</p>';
    renderKnowledgeGraph("#ontology-graph", "#ontology-graph-details", { nodes: [], edges: [] });
    setError("#ontology-message", `Could not load ontology data: ${error.message}`);
    throw error;
  }
}

function renderOntologyFiles(files, selectedFile) {
  state.ontologyFiles = files;
  const list = document.querySelector("#ontology-files");
  list.innerHTML = "";
  files.forEach((file) => {
    const row = document.createElement("label");
    row.className = "file-row";
    row.innerHTML = `<span><input type="radio" name="ontology-file" ${file.path === selectedFile ? "checked" : ""} /> <strong>${file.name}</strong></span>
      <p>${file.suffix} | ${file.kind} | ${file.size_bytes} bytes</p>
      <p>${file.path}</p>`;
    row.querySelector("input").addEventListener("change", async () => {
      await api("/api/ontology/select-file", {
        method: "POST",
        body: JSON.stringify({ path: file.path }),
      });
      setSuccess("#ontology-message", `Selected ${file.name}.`);
      await loadOntologyStatus();
    });
    list.append(row);
  });
}

async function loadOntologyTerms() {
  const query = document.querySelector("#ontology-search").value || "";
  const terms = await api(query ? `/api/ontology/search?q=${encodeURIComponent(query)}` : "/api/ontology/terms");
  state.ontologyTerms = terms;
  const list = document.querySelector("#ontology-terms");
  list.innerHTML = "";
  terms.forEach((term) => {
    const row = document.createElement("div");
    row.className = "term-row";
    row.innerHTML = `<strong>${term.label}</strong>
      <p>${term.term_id || term.iri}</p>
      <p>${term.definition || ""}</p>
      <p>Synonyms: ${(term.synonyms || []).join("; ") || "none"}</p>
      <p>Parents: ${(term.parents || []).join("; ") || "none"}</p>`;
    list.append(row);
  });
  await renderOntologyGraph();
}

function layoutGraph(graph, width, height) {
  const nodes = (graph.nodes || []).map((node, index) => ({ ...node, index }));
  const edges = (graph.edges || []).filter((edge) => edge?.source && edge?.target);
  const radius = Math.max(90, Math.min(width, height) / 2 - 60);
  const cx = width / 2;
  const cy = height / 2;
  nodes.forEach((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(nodes.length, 1);
    node.x = cx + Math.cos(angle) * radius;
    node.y = cy + Math.sin(angle) * radius;
  });
  return { nodes, edges };
}

function renderGraphControls(name, render) {
  const container = document.querySelector(`[data-graph-controls="${name}"]`);
  if (!container) return graphPreference(name);
  const prefs = graphPreference(name);
  container.innerHTML = "";
  [
    ["showText", "Text labels"],
    ["showNodeLabels", "Node labels"],
    ["showEdgeLabels", "Edge labels"],
    ["showDescriptions", "Descriptions"],
    ["simplify", "Simplify"],
  ].forEach(([key, label]) => {
    const row = document.createElement("label");
    row.className = "inline graph-toggle";
    row.innerHTML = `<input type="checkbox" ${prefs[key] ? "checked" : ""} /> ${label}`;
    row.querySelector("input").addEventListener("change", (event) => {
      setGraphPreference(name, key, event.currentTarget.checked);
      render();
    });
    container.append(row);
  });
  return prefs;
}

function renderKnowledgeGraph(containerSelector, detailsSelector, graph, options = {}) {
  const container = document.querySelector(containerSelector);
  const details = document.querySelector(detailsSelector);
  const prefs = graphPreference(options.name || "graph");
  container.innerHTML = "";
  if (!graph?.nodes?.length) {
    container.innerHTML = '<p class="message">No graph data available.</p>';
    return;
  }
  const width = container.clientWidth || 900;
  const height = 360;
  const graphData = prefs.simplify
    ? { nodes: (graph.nodes || []).filter((node) => node.type !== "parent_placeholder"), edges: graph.edges || [] }
    : graph;
  const { nodes, edges } = layoutGraph(graphData, width, height);
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const viewport = document.createElementNS("http://www.w3.org/2000/svg", "g");
  svg.append(viewport);
  let scale = 1;
  let tx = 0;
  let ty = 0;
  let dragging = false;
  let last = null;
  const updateTransform = () => viewport.setAttribute("transform", `translate(${tx} ${ty}) scale(${scale})`);
  svg.addEventListener("wheel", (event) => {
    event.preventDefault();
    scale = Math.max(0.4, Math.min(3, scale + (event.deltaY > 0 ? -0.1 : 0.1)));
    updateTransform();
  });
  svg.addEventListener("pointerdown", (event) => {
    dragging = true;
    last = { x: event.clientX, y: event.clientY };
  });
  svg.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    tx += event.clientX - last.x;
    ty += event.clientY - last.y;
    last = { x: event.clientX, y: event.clientY };
    updateTransform();
  });
  svg.addEventListener("pointerup", () => { dragging = false; });
  edges.forEach((edge) => {
    const source = nodeById.get(edge.source);
    const target = nodeById.get(edge.target);
    if (!source || !target) return;
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", source.x);
    line.setAttribute("y1", source.y);
    line.setAttribute("x2", target.x);
    line.setAttribute("y2", target.y);
    line.setAttribute("class", "graph-edge");
    viewport.append(line);
    const hit = line.cloneNode();
    hit.setAttribute("class", "graph-hit");
    hit.addEventListener("click", (event) => {
      event.stopPropagation();
      details.textContent = `Relation: ${edge.label || "related"} | ${edge.source} -> ${edge.target}`;
    });
    viewport.append(hit);
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", (source.x + target.x) / 2);
    label.setAttribute("y", (source.y + target.y) / 2);
    label.setAttribute("class", "graph-edge-label");
    if (prefs.showText && prefs.showEdgeLabels) {
      label.textContent = edge.label || "";
      viewport.append(label);
    }
  });
  nodes.forEach((node) => {
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.setAttribute("class", `graph-node ${options.meta ? "meta" : ""}`);
    group.setAttribute("transform", `translate(${node.x} ${node.y})`);
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("r", "18");
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", "24");
    label.setAttribute("y", "4");
    label.textContent = node.label || node.id;
    group.append(circle);
    if (prefs.showText && prefs.showNodeLabels) {
      group.append(label);
    }
    group.addEventListener("click", (event) => {
      event.stopPropagation();
      const description = prefs.showDescriptions ? ` | ${node.definition || node.iri || node.type || ""}` : "";
      details.textContent = `Node: ${node.label || node.id}${description}`;
    });
    viewport.append(group);
  });
  container.append(svg);
}

async function renderOntologyGraph() {
  const graph = await api("/api/ontology/graph");
  renderGraphControls("ontology", () => renderKnowledgeGraph("#ontology-graph", "#ontology-graph-details", graph, { name: "ontology" }));
  renderKnowledgeGraph("#ontology-graph", "#ontology-graph-details", graph, { name: "ontology" });
}

async function renderMetaGraph() {
  const graph = await api("/api/meta-ontology/graph");
  renderGraphControls("meta", () => renderKnowledgeGraph("#meta-graph", "#meta-graph-details", graph, { meta: true, name: "meta" }));
  renderKnowledgeGraph("#meta-graph", "#meta-graph-details", graph, { meta: true, name: "meta" });
}

document.querySelector("#ontology-path-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const payload = formPayload(event.currentTarget);
  await withButtonFeedback(button, "Saving", async () => {
    await api("/api/config/ontology-path", {
      method: "POST",
      body: JSON.stringify({ path: payload.path }),
    });
    setSuccess("#ontology-message", "Ontology path saved.");
    await loadStatus();
    await loadOntologyStatus();
  });
});

document.querySelector("#scan-ontology").addEventListener("click", async (event) => {
  await withButtonFeedback(event.currentTarget, "Scanning", async () => {
    const result = await api("/api/ontology/scan", { method: "POST", body: "{}" });
    renderOntologyFiles(result.files || [], null);
    setSuccess("#ontology-message", result.message);
  });
});

document.querySelector("#index-ontology").addEventListener("click", async (event) => {
  await withButtonFeedback(event.currentTarget, "Indexing", async () => {
    const result = await api("/api/ontology/index", { method: "POST", body: "{}" });
    setSuccess("#ontology-message", `Indexed ${result.term_count} terms from ${result.selected_file}.`);
    await loadOntologyTerms();
  });
});

document.querySelector("#ontology-search").addEventListener("input", () => {
  loadOntologyTerms().catch((error) => setError("#ontology-message", error.message));
});

document.querySelector("#zotero-filter").addEventListener("input", renderEntries);

document.querySelector("#curation-prompt-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const payload = formPayload(event.currentTarget);
  try {
    await withButtonFeedback(button, "Saving", async () => {
      await api("/api/curation/prompt", {
        method: "POST",
        body: JSON.stringify({ prompt: payload.prompt }),
      });
      await loadCurationPrompt();
      setSuccess("#curation-prompt-message", "Curation prompt saved.");
    });
  } catch (error) {
    setError("#curation-prompt-message", error.message);
  }
});

document.querySelector("#reset-curation-prompt").addEventListener("click", async (event) => {
  try {
    await withButtonFeedback(event.currentTarget, "Resetting", async () => {
      await api("/api/curation/prompt", { method: "DELETE", body: "{}" });
      await loadCurationPrompt();
      setSuccess("#curation-prompt-message", "Curation prompt reset to the default.");
    });
  } catch (error) {
    setError("#curation-prompt-message", error.message);
  }
});

document.querySelector("#run-curation-suggestions").addEventListener("click", async (event) => {
  try {
    await withButtonFeedback(event.currentTarget, "Running curation", async () => {
      const result = await api("/api/curation/suggestions/run", { method: "POST", body: "{}" });
      setSuccess(
        "#curation-prompt-message",
        `Curation complete. Suggestions: ${result.suggestion_count}; warnings: ${result.warning_count}; chunks: ${result.chunk_count}.`
      );
      document.querySelector("#curation-suggestion-preview").textContent = JSON.stringify(
        {
          response_path: result.response_path,
          request_path: result.request_path,
          suggestions: result.suggestions,
          warnings: result.warnings,
        },
        null,
        2
      );
    });
  } catch (error) {
    setError("#curation-prompt-message", error.message);
  }
});

document.querySelector("#reset-literature-repository").addEventListener("click", async (event) => {
  const confirmed = window.confirm("Reset the local LLM-ready literature repository?");
  if (!confirmed) return;
  try {
    await withButtonFeedback(event.currentTarget, "Resetting", async () => {
      const result = await api("/api/literature/repository/reset", {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      });
      setSuccess("#literature-repository-message", result.message);
      await loadEntries();
    });
  } catch (error) {
    setError("#literature-repository-message", error.message);
  }
});

document.querySelector("#import-test-zotero").addEventListener("click", async (event) => {
  try {
    await withButtonFeedback(event.currentTarget, "Loading", async () => {
      const result = await api("/api/zotero/import-test", { method: "POST", body: "{}" });
      setSuccess("#zotero-message", `Test entries loaded. Inserted ${result.inserted}; updated ${result.updated}.`);
      await loadEntries();
    });
  } catch (error) {
    setError("#zotero-message", error.message);
  }
});

document.querySelector("#literature-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const payload = formPayload(event.currentTarget);
  try {
    await withButtonFeedback(button, "Ingesting", async () => {
      await api("/api/literature", {
        method: "POST",
        body: JSON.stringify({
          path: payload.path || null,
          filename: payload.filename || null,
          content: payload.content || null,
        }),
      });
      event.currentTarget.reset();
      setSuccess("#extract-message", "Document ingested.");
    });
  } catch (error) {
    setError("#extract-message", error.message);
  }
});

document.querySelector("#extract-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const payload = formPayload(event.currentTarget);
  try {
    await withButtonFeedback(button, "Extracting", async () => {
      const result = await api("/api/extraction/candidates", {
        method: "POST",
        body: JSON.stringify({
          guidance: payload.guidance || null,
          use_llm: Boolean(payload.use_llm),
        }),
      });
      const warning = result.literature_warnings?.length
        ? ` Skipped ${result.literature_warnings.length} malformed literature file(s).`
        : "";
      setSuccess("#extract-message", `${result.message} Inserted ${result.inserted}; skipped ${result.skipped}.${warning}`);
      await loadCandidates();
    });
  } catch (error) {
    setError("#extract-message", error.message);
  }
});

document.querySelector("#refine-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const payload = formPayload(event.currentTarget);
  await withButtonFeedback(button, "Generating", async () => {
    await api("/api/refine", {
      method: "POST",
      body: JSON.stringify({
        guidance: payload.guidance,
      }),
    });
    event.currentTarget.reset();
    await loadCandidates();
    setSuccess("#extract-message", "Candidate generated from nudge.");
  });
});

document.querySelector("#new-candidate").addEventListener("click", async (event) => {
  await withButtonFeedback(event.currentTarget, "Adding", async () => {
    await api("/api/candidates", {
      method: "POST",
      body: JSON.stringify({
        label: "New candidate",
        confidence_score: 0.5,
        evidence: [],
      }),
    });
    await loadCandidates();
    setSuccess("#ols-message", "New candidate added.");
  });
});

document.querySelector("#temp-reject-all").addEventListener("click", async (event) => {
  await withButtonFeedback(event.currentTarget, "Hiding", async () => {
    state.candidates.forEach((candidate) => state.temporaryRejectedIds.add(candidate.id));
    sessionStorage.setItem("oca-temp-rejected", JSON.stringify([...state.temporaryRejectedIds]));
    await loadCandidates();
    setSuccess("#ols-message", "Visible candidates temporarily removed from the active queue.");
  });
});

document.querySelector("#ols-all").addEventListener("click", async (event) => {
  await withButtonFeedback(event.currentTarget, "Checking", async () => {
    const result = await api("/api/candidates/ols", { method: "POST", body: "{}" });
    setSuccess("#ols-message", `OLS updated ${result.updated} draft candidates; ${result.failed} failed.`);
    await loadCandidates();
  });
});

document.addEventListener("click", (event) => {
  const feedbackTarget = event.target.closest("button, a, summary, label, .graph-node, .graph-hit");
  if (feedbackTarget) acknowledgeAction(feedbackTarget);

  const link = event.target.closest("a");
  if (!link) return;
  const url = new URL(link.href, window.location.origin);
  if (url.origin !== window.location.origin || !(url.pathname in APP_ROUTES)) return;
  event.preventDefault();
  navigateTo(url.pathname);
});

window.addEventListener("popstate", () => {
  showCurrentPage();
  refreshCurrentPageData().catch((error) => {
    setAppStatus(`Could not load ${currentPage()} data: ${error.message}`, "error");
  });
});

document.querySelector("#theme-light").addEventListener("click", () => {
  applyTheme("light");
  setAppStatus("Theme set to light.", "success");
});
document.querySelector("#theme-dark").addEventListener("click", () => {
  applyTheme("dark");
  setAppStatus("Theme set to dark.", "success");
});

applyTheme();
showCurrentPage();

async function initializeWorkspace() {
  try {
    await loadStatus();
  } catch (error) {
    setAppStatus(`Workspace status unavailable: ${error.message}`, "error");
  }

  try {
    await refreshCurrentPageData();
  } catch (error) {
    setAppStatus(`Could not load ${currentPage()} data: ${error.message}`, "error");
  }
}

initializeWorkspace();
