const state = {
  status: null,
  documents: [],
  entries: [],
  candidates: [],
  rejectedCandidates: [],
  projects: [],
  activeProject: null,
  selectedProjectRef: null,
  curationRuns: [],
  suggestions: [],
  ontologyFiles: [],
  ontologyTerms: [],
  ontologyTree: null,
  collapsedOntologyNodes: new Set(),
  selectedOntologyNodeId: null,
  ontologyFocusNodeId: null,
  ontologyViewport: { scale: 1, tx: 0, ty: 0 },
  ontologyCenterOnSelected: false,
  relationTypes: [],
  activeCandidateId: null,
  savedConfigs: [],
  projectTags: [],
  activeProjectTagFilters: new Set(),
  activeLiteratureTab: "curated",
  llmProviders: [],
  curationPrompt: null,
  projectWizardStep: 0,
  projectBaseIriEdited: false,
  temporaryRejectedIds: new Set(JSON.parse(sessionStorage.getItem("oca-temp-rejected") || "[]")),
  graphPreferences: JSON.parse(localStorage.getItem("oca-graph-preferences") || "{}"),
};

const APP_ROUTES = {
  "/": "dashboard",
  "/projects": "projects",
  "/config": "config",
  "/zotero": "zotero",
  "/literature": "zotero",
  "/ontology": "ontology",
  "/curation-prompt": "curation-prompt",
  "/curation": "curation",
  "/suggestions": "suggestions",
  "/evaluation": "evaluation",
  "/export": "export",
};

const ACTIVE_CANDIDATE_STATUSES = new Set(["new", "in_review", "needs_more_evidence", "deferred"]);
const LITERATURE_DOCUMENT_ROLES = [
  "domain_article",
  "methodology_article",
  "review_article",
  "supplementary_information",
  "unknown",
];
const LITERATURE_RETRY_ENGINES = ["grobid", "docling", "marker", "pymupdf4llm", "pymupdf", "ocr"];

function normalizeText(value) {
  return String(value ?? "").normalize("NFKC").toLowerCase();
}

function safeText(value, fallback = "") {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function escapeHtml(value, fallback = "") {
  return safeText(value, fallback)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
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
    const detail = payload.detail;
    const message = (detail && typeof detail === "object" ? detail.message : detail) || response.statusText;
    const error = new Error(message);
    error.status = response.status;
    error.detail = payload.detail || response.statusText;
    error.path = path;
    throw error;
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

function parseListField(value) {
  return safeText(value)
    .split(/[\n;]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function listText(value) {
  return Array.isArray(value) ? value.join("\n") : "";
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
    await Promise.all([loadStatus(), loadProjects()]);
  } else if (page === "projects") {
    await loadProjects();
  } else if (page === "config") {
    await loadStatus();
    await Promise.all([loadSavedConfigs(), loadLlmProviders()]);
  } else if (page === "zotero") {
    await loadProjects();
    await Promise.all([loadProjectTags(), loadEntries()]);
  } else if (page === "ontology") {
    await loadProjects();
    await loadOntologyStatus();
  } else if (page === "curation-prompt") {
    await Promise.all([loadStatus(), loadCurationPrompt()]);
  } else if (page === "curation") {
    await loadProjects();
    await Promise.all([loadEntries(), loadRelationTypes(), loadCandidates(), loadOntologyStatus()]);
  } else if (page === "suggestions") {
    await Promise.all([loadProjects(), loadCurationRuns(), loadSuggestions()]);
  } else if (page === "evaluation") {
    await Promise.all([loadProjects(), loadCurationRuns()]);
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

function onDomReady(callback) {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", callback, { once: true });
  } else {
    callback();
  }
}

function reportMissingZoteroElement(selector, message = "Zotero configuration panel could not be found. Please reload the page.") {
  console.error(`Missing Zotero sync form element: ${selector}`);
  setError("#zotero-message", message);
  setAppStatus(message, "error");
}

function requiredZoteroElement(selector, message) {
  const element = document.querySelector(selector);
  if (!element) {
    reportMissingZoteroElement(selector, message);
  }
  return element;
}

function zoteroInputValue(selector, { required = false, label = selector } = {}) {
  const input = document.querySelector(selector);
  if (!input) {
    const message = required
      ? "Zotero configuration panel could not be found. Please reload the page."
      : `Optional Zotero field ${selector} is not present; continuing without ${label}.`;
    console.error(`Missing Zotero sync form element: ${selector}`);
    if (required) {
      setError("#zotero-message", message);
      throw new Error(message);
    }
    return "";
  }
  return input.value || "";
}

function projectErrorMessage(operation, error, nextAction = "Review the project fields and try again.") {
  const detail = error?.detail || error?.message || "The project operation did not complete.";
  let likelyCause = "A project setting could not be saved or loaded.";
  if (/already exists|duplicate/i.test(detail)) {
    likelyCause = "The ontology ID or project identifier is already used by another project.";
  } else if (/base iri|iri|url/i.test(detail)) {
    likelyCause = "One of the URL or IRI fields does not look valid.";
  } else if (/parent|circular|self/i.test(detail)) {
    likelyCause = "The selected parent project would make an invalid project hierarchy.";
  } else if (/not found/i.test(detail)) {
    likelyCause = "The selected project or path could not be found.";
  } else if (/llm|api key|provider/i.test(detail)) {
    likelyCause = "The configured LLM settings could not complete the request.";
  }
  const technical = error?.status ? `Backend returned ${error.status}${error.path ? ` from ${error.path}` : ""}.` : "No HTTP status was available.";
  return `${operation} failed. Details: ${detail} Likely cause: ${likelyCause} Next action: ${nextAction} Technical detail: ${technical}`;
}

function setProjectError(operation, error, nextAction) {
  console.error(operation, error);
  setError("#project-message", projectErrorMessage(operation, error, nextAction));
}

function setAppStatus(message, kind = "") {
  const node = document.querySelector("#app-status");
  if (!node) return;
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
  renderStatusGrid();
  populateLiteratureConfigForm();
  await loadLiteratureImportDiagnostics().catch((error) => setError("#publisher-config-message", error.message));
}

async function loadLiteratureImportDiagnostics() {
  const output = document.querySelector("#literature-import-diagnostics");
  if (!output) return;
  const diagnostics = await api("/api/literature/import-diagnostics");
  output.textContent = JSON.stringify(diagnostics, null, 2);
}

function statusLabel(item) {
  if (!item?.configured) return "Not configured";
  return item.exists ? `Ready: ${item.path}` : `Missing: ${item.path}`;
}

function projectHierarchyLabel(project) {
  if (!project) return "No active project";
  const chain = [...(project.parent_chain || []), project].map((item) => item.name || item.ontology_id);
  return chain.join(" -> ");
}

function renderStatusGrid() {
  if (!state.status) return;
  const active = state.activeProject;
  const projectLabel = state.activeProject ? ` | Project ${state.activeProject.slug}` : "";
  setAppStatus(
    `${state.status.backend.app_name}${projectLabel} | Zotero ${state.status.zotero.configured ? "configured" : "not configured"} | LLM ${state.status.llm.configured ? "configured" : "mock only"}`
  );
  renderActiveProjectBanner();
  renderProjectDependencyBlocks();
  const pill = document.querySelector("#active-project-pill");
  if (pill) {
    pill.textContent = active
      ? `Active project: ${active.name} (${active.ontology_id})`
      : "Active project: none";
  }

  const grid = document.querySelector("#status-grid");
  if (!grid) return;
  grid.innerHTML = "";
  const cards = [
    ["Backend", state.status.backend.ok ? "Ready" : "Unavailable"],
    ["Database", state.status.database.ok ? "Ready" : "Unavailable"],
    ["Zotero", state.status.zotero.configured ? `Ready (${state.status.zotero.library_type})` : "Missing library settings"],
    ["LLM", state.status.llm.configured ? `Ready (${state.status.llm.provider})` : "Mock extraction available"],
    ["Zotero literature storage", state.status.literature.zotero_literature_storage_path_exists ? "Ready" : "Missing path"],
    ["Ontology", state.status.ontology.selected_file || state.status.ontology.path || "Not configured"],
    ["Active project", active ? active.name : "No active project"],
    ["Project type", active?.project_type || "Not configured"],
    ["Ontology ID / prefix", active ? `${active.ontology_id}${active.ontology_namespace ? ` / ${active.ontology_namespace}` : ""}` : "Not configured"],
    ["Project hierarchy", projectHierarchyLabel(active)],
    ["Child projects", active?.children?.length ? active.children.map((child) => child.name).join("; ") : "No child projects"],
    ["Workspace", statusLabel(active?.path_statuses?.workspace_path)],
    ["ODK repository", statusLabel(active?.path_statuses?.odk_repo_path)],
    ["Git repository", statusLabel(active?.path_statuses?.local_git_repository_path)],
    ["GitHub", active?.github_url || "Not configured"],
    ["Editable ontology", statusLabel(active?.path_statuses?.editable_ontology_path)],
    ["Built ontology", statusLabel(active?.path_statuses?.built_ontology_path)],
    ["Literature repository", statusLabel(active?.path_statuses?.literature_repository_path)],
    ["Tagged literature", active ? `${active.literature_project_tag_count || 0} entr${active.literature_project_tag_count === 1 ? "y" : "ies"}` : "Not available"],
  ];
  cards.forEach(([label, value]) => {
    const card = document.createElement("div");
    card.className = "status-card";
    card.innerHTML = `<strong>${escapeHtml(label)}</strong><span>${escapeHtml(value)}</span>`;
    grid.append(card);
  });
}

function renderActiveProjectBanner() {
  const banner = document.querySelector("#active-project-banner");
  if (!banner) return;
  const active = state.activeProject;
  if (!active) {
    banner.classList.add("needs-project");
    banner.innerHTML = `<div>
        <strong>No active project selected.</strong>
        <span>Create or select a project to use ontology, literature, curation, and export workflows.</span>
      </div>
      <div class="button-row compact-actions">
        <a href="/projects" data-route>Select or create project</a>
      </div>`;
    return;
  }
  banner.classList.remove("needs-project");
  banner.innerHTML = `<div>
      <strong>Active project: ${escapeHtml(active.name)}</strong>
      <span>${escapeHtml(active.ontology_id)} | ${escapeHtml(active.project_type)} | ${escapeHtml(projectHierarchyLabel(active))}</span>
    </div>
    <div class="button-row compact-actions">
      <a href="/projects" data-route data-project-details="${escapeHtml(active.slug)}">View project details</a>
      <a href="/projects" data-route>Switch project</a>
    </div>`;
}

function renderProjectDependencyBlocks() {
  const active = state.activeProject;
  const message = active
    ? `Using active project ${active.name} (${active.ontology_id}).`
    : "No active project selected. Create or select a project before using this workflow.";
  [
    "#literature-project-blocker",
    "#ontology-project-blocker",
    "#curation-project-blocker",
    "#export-project-blocker",
  ].forEach((selector) => {
    const node = document.querySelector(selector);
    if (!node) return;
    node.classList.toggle("hidden", Boolean(active));
    node.innerHTML = active
      ? ""
      : `${escapeHtml(message)} <a href="/projects" data-route>Select or create a project</a>.`;
  });
}

async function loadProjects() {
  try {
    const payload = await api("/api/projects");
    state.projects = payload.projects || [];
    state.activeProject = payload.active_project || null;
    if (!state.selectedProjectRef && state.activeProject) {
      state.selectedProjectRef = state.activeProject.slug;
    }
    renderProjects();
    renderDashboardProjectHierarchy();
    renderActiveProjectBanner();
    renderProjectDependencyBlocks();
    renderStatusGrid();
  } catch (error) {
    console.error("Load project list failed", error);
    const dashboardMessage = document.querySelector("#dashboard-project-message");
    if (dashboardMessage) {
      dashboardMessage.classList.add("error");
      dashboardMessage.textContent = projectErrorMessage(
        "Project hierarchy could not be loaded",
        error,
        "Refresh the dashboard or open Project Management."
      );
    }
    setProjectError("Load project list", error, "Refresh the page or create a project from the Projects page.");
    throw error;
  }
}

function renderProjects() {
  populateProjectParentSelect();
  const summary = document.querySelector("#active-project-summary");
  if (summary) {
    summary.innerHTML = "";
    const project = state.activeProject;
    [
      ["Active project", project ? project.name : "No active project"],
      ["Project type", project?.project_type || "Not configured"],
      ["Ontology ID / prefix", project ? `${project.ontology_id}${project.ontology_namespace ? ` / ${project.ontology_namespace}` : ""}` : "Not configured"],
      ["Parent project", project?.parent_project?.name || "No parent project"],
      ["Child projects", project?.children?.length ? project.children.map((child) => child.name).join("; ") : "No child projects"],
      ["Workspace", statusLabel(project?.path_statuses?.workspace_path)],
      ["ODK repository", statusLabel(project?.path_statuses?.odk_repo_path)],
      ["Git repository", statusLabel(project?.path_statuses?.local_git_repository_path)],
      ["GitHub", project?.github_url || "Not configured"],
      ["Editable ontology", statusLabel(project?.path_statuses?.editable_ontology_path)],
      ["Built ontology", statusLabel(project?.path_statuses?.built_ontology_path)],
      ["Literature repository", statusLabel(project?.path_statuses?.literature_repository_path)],
      ["Tagged literature", project ? `${project.literature_project_tag_count || 0}` : "0"],
    ].forEach(([label, value]) => {
      const card = document.createElement("div");
      card.className = "status-card";
      card.innerHTML = `<strong>${escapeHtml(label)}</strong><span>${escapeHtml(value)}</span>`;
      summary.append(card);
    });
  }
  const selectedProject = projectByRef(state.selectedProjectRef) || state.activeProject || state.projects[0] || null;
  state.selectedProjectRef = selectedProject?.slug || null;
  renderProjectDetail(selectedProject);
  const list = document.querySelector("#project-list");
  if (!list) return;
  list.innerHTML = "";
  const projectsByParent = new Map();
  state.projects.forEach((project) => {
    const key = project.parent_project_id || "root";
    projectsByParent.set(key, [...(projectsByParent.get(key) || []), project]);
  });
  const ordered = [];
  function appendProjects(parentId = "root", depth = 0) {
    (projectsByParent.get(parentId) || []).forEach((project) => {
      ordered.push({ project, depth });
      appendProjects(project.id, depth + 1);
    });
  }
  appendProjects();
  ordered.forEach(({ project, depth }) => {
    const row = document.createElement("article");
    row.className = `project-card${project.active ? " is-active-project" : ""}`;
    row.style.marginLeft = `${Math.min(depth * 18, 72)}px`;
    row.innerHTML = `<header class="project-card-header">
        <div>
          <strong>${project.active ? "Active: " : ""}${escapeHtml(project.name)}</strong>
          <p>${escapeHtml(project.project_type)} | ontology ID ${escapeHtml(project.ontology_id)} | ${escapeHtml(project.ontology_namespace || "namespace not configured")}</p>
        </div>
        <span class="project-state">${project.active ? "Active" : "Inactive"}</span>
      </header>
      <div class="project-card-grid">
        <span><strong>Parent</strong>${escapeHtml(project.parent_project?.name || "None")}</span>
        <span><strong>Children</strong>${escapeHtml(String(project.child_count ?? project.children?.length ?? 0))}</span>
        <span><strong>Workspace</strong>${escapeHtml(statusLabel(project.path_statuses?.workspace_path))}</span>
        <span><strong>Literature</strong>${escapeHtml(statusLabel(project.path_statuses?.literature_repository_path))}</span>
        <span><strong>Ontology</strong>${escapeHtml(projectOntologyStatus(project))}</span>
        <span><strong>Last modified</strong>${escapeHtml(project.updated_at || project.created_at || "Not available")}</span>
      </div>
      <div class="button-row">
        <button type="button" data-project-view="${project.slug}">View project details</button>
        <button type="button" class="secondary" data-project-edit="${project.slug}">Edit project metadata</button>
        <button type="button" data-project-select="${project.slug}">${project.active ? "Project is active" : "Set this project as active"}</button>
        <button type="button" class="secondary" data-project-child="${project.slug}">Create child project</button>
        <button type="button" class="secondary" disabled>Open workspace path (not supported in browser)</button>
        <a href="/api/projects/${encodeURIComponent(project.slug)}/exports/accepted.robot.tsv">Accepted TSV</a>
      </div>`;
    row.querySelector("[data-project-view]").addEventListener("click", () => {
      state.selectedProjectRef = project.slug;
      renderProjectDetail(project);
      document.querySelector("#project-detail")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    row.querySelector("[data-project-select]").addEventListener("click", async (event) => {
      await selectProjectFromUi(project, event.currentTarget);
    });
    row.querySelectorAll("[data-project-edit]").forEach((button) => button.addEventListener("click", () => {
      fillProjectForm(project);
      setSuccess("#project-message", `Editing ${project.name}. Current values are loaded in the form above.`);
    }));
    row.querySelector("[data-project-child]").addEventListener("click", () => startChildProject(project));
    list.append(row);
  });
  if (!list.children.length) {
    list.innerHTML = '<p class="message">No projects created yet. Use the wizard above to create your first ontology-development project.</p>';
  }
}

function projectsByParentMap() {
  const map = new Map();
  state.projects.forEach((project) => {
    const key = project.parent_project_id || "root";
    map.set(key, [...(map.get(key) || []), project]);
  });
  return map;
}

function projectStatusBadge(project) {
  const workspace = project?.path_statuses?.workspace_path;
  if (!workspace?.configured) return "Workspace not configured";
  return workspace.exists ? "Workspace ready" : "Workspace missing";
}

function renderDashboardProjectHierarchy() {
  const tree = document.querySelector("#dashboard-project-tree");
  const preview = document.querySelector("#dashboard-project-preview");
  const message = document.querySelector("#dashboard-project-message");
  if (!tree || !preview) return;
  tree.innerHTML = "";
  preview.innerHTML = "";
  if (message) message.textContent = "";

  if (!state.projects.length) {
    tree.innerHTML = `<div class="empty-state">
      <strong>No projects exist yet.</strong>
      <p>No projects exist yet. Create a project to start ontology curation.</p>
      <a href="/projects" data-route>Create first project</a>
    </div>`;
    return;
  }

  if (!state.activeProject && message) {
    message.textContent = "No active project selected. Click a project tile to work on it.";
  }

  const selected = state.activeProject || projectByRef(state.selectedProjectRef) || state.projects[0];
  renderDashboardProjectPreview(selected);
  const byParent = projectsByParentMap();
  const roots = byParent.get("root") || state.projects.filter((project) => !project.parent_project_id);
  const list = document.createElement("div");
  list.className = "project-tree-list";
  roots.forEach((project) => list.append(renderDashboardProjectNode(project, byParent, 0)));
  tree.append(list);
}

function renderDashboardProjectNode(project, byParent, depth) {
  const wrapper = document.createElement("div");
  wrapper.className = `project-tree-node depth-${Math.min(depth, 6)}`;
  const tile = document.createElement("article");
  tile.className = `dashboard-project-tile${project.active ? " is-active-project" : ""}`;
  tile.tabIndex = 0;
  tile.setAttribute("role", "button");
  tile.setAttribute("aria-label", `Work on project ${project.name}`);
  tile.innerHTML = `<header class="project-card-header">
      <div>
        <strong>${escapeHtml(project.name)}</strong>
        <p>${escapeHtml(project.ontology_id)} | ${escapeHtml(project.project_type)}</p>
      </div>
      <span class="project-state">${project.active ? "Active" : "Inactive"}</span>
    </header>
    <div class="project-card-grid compact-project-grid">
      <span><strong>Parent</strong>${escapeHtml(project.parent_project?.name || "Root project")}</span>
      <span><strong>Children</strong>${escapeHtml(String(project.child_count ?? project.children?.length ?? 0))}</span>
      <span><strong>Status</strong>${escapeHtml(projectStatusBadge(project))}</span>
      <span><strong>Ontology</strong>${escapeHtml(projectOntologyStatus(project))}</span>
    </div>
    <div class="button-row">
      <button type="button" data-dashboard-select="${project.slug}">${project.active ? "Work on this active project" : "Work on this project"}</button>
      <button type="button" class="secondary" data-dashboard-view="${project.slug}">View details</button>
      <button type="button" class="secondary" data-dashboard-edit="${project.slug}">Edit metadata</button>
      <button type="button" class="secondary" data-dashboard-child="${project.slug}">Create child project</button>
    </div>`;

  const activate = async (event) => {
    event?.preventDefault?.();
    await selectProjectFromUi(project, tile, "#dashboard-project-message");
  };
  tile.addEventListener("click", async (event) => {
    if (event.target.closest("button, a")) return;
    await activate(event);
  });
  tile.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    await activate(event);
  });
  tile.querySelector("[data-dashboard-select]")?.addEventListener("click", async (event) => {
    await selectProjectFromUi(project, event.currentTarget, "#dashboard-project-message");
  });
  tile.querySelector("[data-dashboard-view]")?.addEventListener("click", () => {
    state.selectedProjectRef = project.slug;
    navigateTo("/projects");
  });
  tile.querySelector("[data-dashboard-edit]")?.addEventListener("click", () => {
    state.selectedProjectRef = project.slug;
    fillProjectForm(project);
    navigateTo("/projects");
  });
  tile.querySelector("[data-dashboard-child]")?.addEventListener("click", () => {
    startChildProject(project);
    navigateTo("/projects");
  });

  wrapper.append(tile);
  const children = byParent.get(project.id) || [];
  if (children.length) {
    const childList = document.createElement("div");
    childList.className = "project-tree-children";
    children.forEach((child) => childList.append(renderDashboardProjectNode(child, byParent, depth + 1)));
    wrapper.append(childList);
  }
  return wrapper;
}

function renderDashboardProjectPreview(project) {
  const preview = document.querySelector("#dashboard-project-preview");
  if (!preview || !project) return;
  preview.innerHTML = `<div class="section-title">
      <div>
        <h3>Selected project preview</h3>
        <p class="description">This is a project hierarchy overview, not an ontology class hierarchy or import/dependency graph.</p>
      </div>
      <span class="project-state">${project.active ? "Active project" : "Selected project"}</span>
    </div>
    <div class="status-grid">
      <div class="status-card"><strong>Project</strong><span>${escapeHtml(project.name)}</span></div>
      <div class="status-card"><strong>Ontology ID</strong><span>${escapeHtml(project.ontology_id)}</span></div>
      <div class="status-card"><strong>Project type</strong><span>${escapeHtml(project.project_type)}</span></div>
      <div class="status-card"><strong>Parent</strong><span>${escapeHtml(project.parent_project?.name || "Root project")}</span></div>
      <div class="status-card"><strong>Children</strong><span>${escapeHtml((project.children || []).map((child) => child.name).join("; ") || "None")}</span></div>
      <div class="status-card"><strong>Workspace</strong><span>${escapeHtml(statusLabel(project.path_statuses?.workspace_path))}</span></div>
      <div class="status-card"><strong>Ontology file status</strong><span>${escapeHtml(projectOntologyStatus(project))}</span></div>
      <div class="status-card"><strong>Literature repository</strong><span>${escapeHtml(statusLabel(project.path_statuses?.literature_repository_path))}</span></div>
    </div>
    <div class="button-row">
      <a href="/projects" data-route>Project details</a>
      <button type="button" class="secondary" data-dashboard-preview-edit="${project.slug}">Edit metadata</button>
      ${project.active ? '<a href="/ontology" data-route>Ontology section</a>' : '<button type="button" class="secondary" disabled>Ontology section after activation</button>'}
      <a href="/zotero" data-route>Literature section</a>
    </div>`;
  preview.querySelector("[data-dashboard-preview-edit]")?.addEventListener("click", () => {
    state.selectedProjectRef = project.slug;
    fillProjectForm(project);
    navigateTo("/projects");
  });
}

function projectByRef(projectRef) {
  return state.projects.find((project) => [project.slug, project.project_id, String(project.id)].includes(String(projectRef)));
}

function projectOntologyStatus(project) {
  const built = statusLabel(project?.path_statuses?.built_ontology_path);
  const editable = statusLabel(project?.path_statuses?.editable_ontology_path);
  if (project?.path_statuses?.built_ontology_path?.configured) return `Built: ${built}`;
  if (project?.path_statuses?.editable_ontology_path?.configured) return `Editable: ${editable}`;
  return "No ontology file configured";
}

function pathUseDescription(key) {
  return {
    workspace_path: "Project files and local scaffold metadata.",
    odk_repo_path: "ODK-managed ontology repository when one is connected.",
    editable_ontology_path: "Human-editable ontology source used for ontology browsing when no built file exists.",
    built_ontology_path: "Built or released ontology file preferred by the ontology browser.",
    literature_repository_path: "Project literature workspace and later project-specific evidence context.",
    local_git_repository_path: "Local Git checkout metadata only; the app does not create repositories.",
    github_url: "Remote repository reference metadata only; the app does not create GitHub repositories.",
  }[key] || "Project metadata path.";
}

function renderPathStatusCard(label, status, rawValue, key) {
  const configured = status?.configured || Boolean(rawValue);
  const stateText = configured ? (status?.exists ? "Exists" : "Missing") : "Not configured";
  const value = status?.path || rawValue || "Not configured";
  const warning = configured && !status?.exists ? " warning" : "";
  return `<div class="status-card${warning}">
    <strong>${escapeHtml(label)}: ${escapeHtml(stateText)}</strong>
    <span>${escapeHtml(value)}</span>
    <p>${escapeHtml(pathUseDescription(key))}</p>
  </div>`;
}

function projectNextSteps(project) {
  const upper = project?.project_type === "upper_bioprocess_ontology";
  if (upper) {
    return [
      "Review and edit project metadata.",
      "Configure ontology paths or connect an ODK repository later.",
      "Add child/domain projects, for example Protein Precipitation Ontology.",
      "Import or tag relevant literature.",
      "Later: generate ontology candidates with the LLM.",
      "Later: review candidates and export accepted changes.",
    ];
  }
  return [
    "Confirm the parent project.",
    "Configure ontology source or workspace paths.",
    "Tag literature relevant to this project.",
    "Later: generate and review candidates in the context of this project.",
  ];
}

function renderProjectDetail(project) {
  const detail = document.querySelector("#project-detail");
  if (!detail) return;
  if (!project) {
    detail.innerHTML = `<h3>Project details</h3>
      <p class="message">No project selected. Create a project with the wizard or select an existing project to inspect it.</p>`;
    return;
  }
  const paths = project.path_statuses || {};
  detail.innerHTML = `<div class="section-title">
      <div>
        <h3>Project details: ${escapeHtml(project.name)}</h3>
        <p class="description">Inspect identity, hierarchy, configured paths, missing pieces, and next actions for this project.</p>
      </div>
      <span class="project-state">${project.active ? "Active project" : "Inactive project"}</span>
    </div>
    <div class="status-grid">
      <div class="status-card"><strong>Project name</strong><span>${escapeHtml(project.name)}</span></div>
      <div class="status-card"><strong>Ontology ID / namespace</strong><span>${escapeHtml(project.ontology_id)} / ${escapeHtml(project.ontology_namespace || "not configured")}</span></div>
      <div class="status-card"><strong>Project type</strong><span>${escapeHtml(project.project_type)}</span></div>
      <div class="status-card"><strong>Base IRI</strong><span>${escapeHtml(project.base_iri || "Not configured")}</span></div>
      <div class="status-card"><strong>Parent project</strong><span>${escapeHtml(project.parent_project?.name || "None")}</span></div>
      <div class="status-card"><strong>Child projects</strong><span>${escapeHtml((project.children || []).map((child) => child.name).join("; ") || "None")}</span></div>
      <div class="status-card"><strong>Last modified</strong><span>${escapeHtml(project.updated_at || project.created_at || "Not available")}</span></div>
    </div>
    <div class="project-detail-text">
      <h4>Description</h4>
      <p>${escapeHtml(project.description || "No short description yet.")}</p>
      <h4>Scope notes</h4>
      <p>${escapeHtml(project.minimal_scope_notes || "No scope notes yet.")}</p>
    </div>
    <h4>Paths and status</h4>
    <div class="status-grid">
      ${renderPathStatusCard("Workspace path", paths.workspace_path, project.local_path, "workspace_path")}
      ${renderPathStatusCard("ODK repository path", paths.odk_repo_path, project.odk_repo_path, "odk_repo_path")}
      ${renderPathStatusCard("Editable ontology file", paths.editable_ontology_path, project.editable_ontology_path, "editable_ontology_path")}
      ${renderPathStatusCard("Built ontology file", paths.built_ontology_path, project.built_ontology_path, "built_ontology_path")}
      ${renderPathStatusCard("Literature repository", paths.literature_repository_path, project.literature_repository_path, "literature_repository_path")}
      ${renderPathStatusCard("Local Git repository", paths.local_git_repository_path, project.local_git_repository_path, "local_git_repository_path")}
      ${renderPathStatusCard("GitHub URL/path", { configured: Boolean(project.github_url), exists: Boolean(project.github_url), path: project.github_url }, project.github_url, "github_url")}
    </div>
    <h4>What can I do next?</h4>
    <ol>${projectNextSteps(project).map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ol>
    <div class="button-row">
      <button type="button" data-detail-edit="${project.slug}">Edit project metadata</button>
      <button type="button" class="secondary" data-detail-child="${project.slug}">Create child project</button>
      <button type="button" data-detail-select="${project.slug}">${project.active ? "Project is active" : "Set as active project"}</button>
      <a href="/zotero" data-route>Open literature section</a>
      ${project.active ? '<a href="/ontology" data-route>Open ontology browser for active project</a>' : '<button type="button" class="secondary" disabled>Open ontology browser after setting active</button>'}
      <button type="button" class="secondary" disabled>Configure ontology paths in metadata form</button>
    </div>`;
  detail.querySelector("[data-detail-edit]")?.addEventListener("click", () => {
    fillProjectForm(project);
    setSuccess("#project-message", `Editing ${project.name}. Update fields above, then save project metadata.`);
  });
  detail.querySelector("[data-detail-child]")?.addEventListener("click", () => startChildProject(project));
  detail.querySelector("[data-detail-select]")?.addEventListener("click", async (event) => {
    await selectProjectFromUi(project, event.currentTarget);
  });
}

async function selectProjectFromUi(project, button, messageSelector = "#project-message") {
  try {
    const action = async () => {
      await api(`/api/projects/${encodeURIComponent(project.slug)}/select`, { method: "POST", body: "{}" });
      state.selectedProjectRef = project.slug;
      await loadProjects();
      if (["ontology", "curation"].includes(currentPage())) {
        await loadOntologyStatus();
      }
      setSuccess(messageSelector, `Active project set to ${project.name}.`);
      if (messageSelector !== "#project-message") {
        setSuccess("#project-message", `Active project set to ${project.name}. Next: review details, configure paths, or open literature/ontology sections.`);
      }
    };
    if (button?.matches?.("button")) {
      await withButtonFeedback(button, "Setting active project", action);
    } else {
      showActionToast(`Setting active project ${project.name}...`);
      await action();
      showActionToast(`Active project set to ${project.name}.`);
    }
  } catch (error) {
    if (messageSelector === "#project-message") {
      setProjectError("Set active project", error, "Select a different project or refresh the project list.");
    } else {
      console.error("Set active project", error);
      setError(
        messageSelector,
        projectErrorMessage("Project hierarchy could not be loaded", error, "Refresh the dashboard or open Project Management.")
      );
    }
  }
}

function startChildProject(parentProject) {
  resetProjectForm();
  const form = document.querySelector("#project-create-form");
  if (!form) return;
  form.parent_project_id.value = String(parentProject.id);
  form.project_type.value = "domain_ontology";
  setProjectWizardStep(0);
  updateProjectWizardReview();
  form.name.focus();
  setSuccess("#project-message", `Creating child project under ${parentProject.name}. Fill identity fields, then create the project.`);
}

function descendantProjectIds(projectId) {
  const ids = new Set();
  function visit(parentId) {
    state.projects
      .filter((project) => project.parent_project_id === parentId)
      .forEach((child) => {
        ids.add(child.id);
        visit(child.id);
      });
  }
  visit(projectId);
  return ids;
}

function populateProjectParentSelect(excludedProjectId = null) {
  const select = document.querySelector("#project-parent-select");
  if (!select) return;
  const current = select.value;
  select.innerHTML = '<option value="">No parent project</option>';
  const blockedIds = excludedProjectId ? new Set([Number(excludedProjectId), ...descendantProjectIds(Number(excludedProjectId))]) : new Set();
  state.projects.forEach((project) => {
    if (blockedIds.has(project.id)) return;
    const option = document.createElement("option");
    option.value = String(project.id);
    option.textContent = `${project.name} (${project.ontology_id})`;
    select.append(option);
  });
  if ([...select.options].some((option) => option.value === current)) {
    select.value = current;
  }
}

function fillProjectForm(project) {
  const form = document.querySelector("#project-create-form");
  if (!form) return;
  populateProjectParentSelect(project.id);
  form.project_ref.value = project.slug || "";
  form.name.value = project.name || "";
  form.ontology_id.value = project.ontology_id || "";
  form.project_type.value = project.project_type || "domain_ontology";
  form.parent_project_id.value = project.parent_project_id || "";
  form.ontology_title.value = project.ontology_title || "";
  form.ontology_namespace.value = project.ontology_namespace || "";
  form.base_iri.value = project.base_iri || "";
  state.projectBaseIriEdited = Boolean(project.base_iri && project.base_iri !== project.suggested_base_iri);
  form.local_workspace_path.value = project.local_path || "";
  form.github_url.value = project.github_url || "";
  form.local_git_repository_path.value = project.local_git_repository_path || "";
  form.zotero_literature_source_path.value = "";
  form.odk_repo_path.value = project.odk_repo_path || "";
  form.editable_ontology_path.value = project.editable_ontology_path || "";
  form.built_ontology_path.value = project.built_ontology_path || "";
  form.literature_repository_path.value = project.literature_repository_path || "";
  form.description.value = project.description || "";
  form.minimal_scope_notes.value = project.minimal_scope_notes || listText(project.ontology_scope);
  document.querySelector("#project-submit-button").textContent = "Save Project Metadata";
  document.querySelector("#project-cancel-edit")?.classList.remove("hidden");
  setProjectWizardStep(0);
  updateProjectWizardReview();
}

function resetProjectForm() {
  const form = document.querySelector("#project-create-form");
  if (!form) return;
  populateProjectParentSelect();
  form.reset();
  form.project_ref.value = "";
  form.project_type.value = "domain_ontology";
  state.projectBaseIriEdited = false;
  document.querySelector("#project-submit-button").textContent = "Create Project";
  document.querySelector("#project-cancel-edit")?.classList.add("hidden");
  setProjectWizardStep(0);
  updateProjectWizardReview();
}

function suggestedBaseIriFor(ontologyId) {
  const normalized = safeText(ontologyId).trim().toLowerCase().replace(/[^a-z0-9_]+/g, "");
  return normalized ? `http://purl.obolibrary.org/obo/${normalized}.owl` : "";
}

function setProjectWizardStep(step) {
  const steps = [...document.querySelectorAll(".project-wizard-step")];
  if (!steps.length) return;
  state.projectWizardStep = Math.max(0, Math.min(step, steps.length - 1));
  steps.forEach((section, index) => {
    section.classList.toggle("hidden", index !== state.projectWizardStep);
  });
  document.querySelectorAll("[data-project-step]").forEach((button) => {
    button.setAttribute("aria-pressed", String(Number(button.dataset.projectStep) === state.projectWizardStep));
  });
  const prev = document.querySelector("#project-wizard-prev");
  const next = document.querySelector("#project-wizard-next");
  if (prev) prev.disabled = state.projectWizardStep === 0;
  if (next) next.classList.toggle("hidden", state.projectWizardStep === steps.length - 1);
  updateProjectWizardReview();
}

function projectFormData() {
  const form = document.querySelector("#project-create-form");
  return form ? formPayload(form) : {};
}

function updateProjectWizardReview() {
  const review = document.querySelector("#project-wizard-review");
  const warnings = document.querySelector("#project-wizard-warnings");
  if (!review) return;
  const payload = projectFormData();
  const optionalPaths = [
    ["Workspace", payload.local_workspace_path],
    ["ODK repository", payload.odk_repo_path],
    ["Editable ontology", payload.editable_ontology_path],
    ["Built ontology", payload.built_ontology_path],
    ["Literature repository", payload.literature_repository_path],
    ["Local Git repository", payload.local_git_repository_path],
  ];
  review.innerHTML = "";
  [
    ["Project", payload.name || "Missing project name"],
    ["Ontology ID", payload.ontology_id || "Missing ontology ID"],
    ["Project type", payload.project_type || "domain_ontology"],
    ["Parent", document.querySelector("#project-parent-select")?.selectedOptions?.[0]?.textContent || "No parent project"],
    ["Base IRI", payload.base_iri || "Not configured"],
    ["GitHub", payload.github_url || "Not configured"],
  ].forEach(([label, value]) => {
    const card = document.createElement("div");
    card.className = "status-card";
    card.innerHTML = `<strong>${escapeHtml(label)}</strong><span>${escapeHtml(value)}</span>`;
    review.append(card);
  });
  if (warnings) {
    const missing = optionalPaths
      .filter(([, value]) => !safeText(value).trim())
      .map(([label]) => label);
    const invalidBase = payload.base_iri && !/^[a-z][a-z0-9+.-]*:/i.test(payload.base_iri);
    warnings.textContent = [
      invalidBase ? "Base IRI does not look like an IRI/URL." : "",
      missing.length ? `Optional paths not configured yet: ${missing.join(", ")}.` : "All optional path fields have values.",
    ].filter(Boolean).join(" ");
  }
}

async function loadCurationRuns() {
  try {
    state.curationRuns = await api("/api/curation/runs");
  } catch {
    state.curationRuns = [];
  }
  renderCurationRuns();
}

function renderCurationRuns() {
  const list = document.querySelector("#curation-run-list");
  if (!list) return;
  list.innerHTML = "";
  state.curationRuns.forEach((run) => {
    const row = document.createElement("article");
    row.className = "entry-row";
    row.innerHTML = `<strong>${safeText(run.id)}: ${safeText(run.name)}</strong>
      <p>${safeText(run.prompt_strategy)} | ${safeText(run.status)} | ${safeText(run.created_at || "")}</p>`;
    list.append(row);
  });
  if (!list.children.length) {
    list.innerHTML = '<p class="message">No curation runs for the active project.</p>';
  }
}

async function loadSuggestions() {
  try {
    state.suggestions = await api("/api/suggestions");
  } catch {
    state.suggestions = [];
  }
  renderSuggestions();
}

function renderSuggestions() {
  const list = document.querySelector("#suggestion-list");
  if (!list) return;
  list.innerHTML = "";
  state.suggestions.forEach((suggestion) => {
    const row = document.createElement("article");
    row.className = "candidate";
    row.innerHTML = `<div class="candidate-head">
        <strong>${safeText(suggestion.label)}</strong>
        <span>${safeText(suggestion.review_status)}</span>
      </div>
      <p class="candidate-source">Run ${safeText(suggestion.curation_run_id)} | ${safeText(suggestion.suggestion_type)} | confidence ${safeText(suggestion.confidence || "")}</p>
      <div class="candidate-grid">
        <label>Definition<textarea class="suggestion-definition" rows="3">${safeText(suggestion.definition || "")}</textarea></label>
        <label>Evidence<textarea rows="3" readonly>${safeText(suggestion.evidence_text || "")}</textarea></label>
        <label>Raw LLM output<textarea rows="3" readonly>${safeText(suggestion.raw_llm_output || "")}</textarea></label>
        <label>Status
          <select class="suggestion-status">
            <option value="accepted">accepted</option>
            <option value="edited">edited</option>
            <option value="rejected">rejected</option>
            <option value="duplicate">duplicate</option>
            <option value="unsupported">unsupported</option>
            <option value="further_review">further_review</option>
          </select>
        </label>
        <label>Reviewer<input class="suggestion-reviewer" /></label>
        <label>Review time seconds<input class="suggestion-time" type="number" min="0" /></label>
      </div>
      <label>Comment<textarea class="suggestion-comment" rows="2"></textarea></label>
      <div class="candidate-actions">
        <button type="button" class="save-review">Save Review</button>
      </div>`;
    row.querySelector(".suggestion-status").value =
      suggestion.review_status === "unreviewed" ? "accepted" : suggestion.review_status;
    row.querySelector(".save-review").addEventListener("click", async (event) => {
      await withButtonFeedback(event.currentTarget, "Saving review", async () => {
        const status = row.querySelector(".suggestion-status").value;
        await api(`/api/suggestions/${suggestion.id}/review`, {
          method: "POST",
          body: JSON.stringify({
            status,
            reviewer: row.querySelector(".suggestion-reviewer").value || null,
            edited_definition: status === "edited" ? row.querySelector(".suggestion-definition").value : null,
            comment: row.querySelector(".suggestion-comment").value || null,
            review_time_seconds: Number(row.querySelector(".suggestion-time").value || 0) || null,
          }),
        });
        await loadSuggestions();
        setSuccess("#suggestions-message", "Review saved.");
      });
    });
    list.append(row);
  });
  if (!list.children.length) {
    list.innerHTML = '<p class="message">No structured suggestions for the active project.</p>';
  }
}

function populateLiteratureConfigForm() {
  const form = document.querySelector("#literature-config-form");
  const literature = state.status?.literature ?? {};
  if (form) {
    [
      ["zotero_literature_storage_path", literature.zotero_literature_storage_path],
    ].forEach(([name, value]) => {
      const input = form.querySelector(`[name="${name}"]`);
      if (input && value !== undefined && value !== null) input.value = value;
    });
  }
  const publisher = state.status?.publisher ?? {};
  const publisherForm = document.querySelector("#publisher-config-form");
  if (publisherForm) {
    const keyInput = publisherForm.querySelector('[name="elsevier_api_key"]');
    const tokenInput = publisherForm.querySelector('[name="elsevier_inst_token"]');
    const baseUrlInput = publisherForm.querySelector('[name="elsevier_api_base_url"]');
    const enabledInput = publisherForm.querySelector('[name="publisher_api_enrichment_enabled"]');
    const extractionModeInput = publisherForm.querySelector('[name="literature_extraction_mode"]');
    if (keyInput) keyInput.value = publisher.elsevier_api_key ?? "";
    if (tokenInput) tokenInput.value = publisher.elsevier_inst_token ?? "";
    if (baseUrlInput) baseUrlInput.value = publisher.elsevier_api_base_url ?? publisher.base_url ?? "https://api.elsevier.com";
    if (enabledInput) enabledInput.checked = Boolean(publisher.enable_publisher_api_enrichment ?? publisher.enabled ?? false);
    if (extractionModeInput) extractionModeInput.value = publisher.literature_extraction_mode ?? "publisher_api_required";
    const providers = publisher.providers || {};
    [
      ["springer_api_key", providers.springer?.api_key === "configured" ? "" : ""],
      ["wiley_tdm_token", providers.wiley?.tdm_token === "configured" ? "" : ""],
      ["crossref_contact_email", providers.crossref?.contact_email || ""],
      ["ncbi_contact_email", providers.ncbi?.contact_email || ""],
      ["ncbi_api_key", providers.ncbi?.api_key === "configured" ? "" : ""],
      ["openalex_email", providers.openalex?.contact_email || ""],
    ].forEach(([name, value]) => {
      const input = publisherForm.querySelector(`[name="${name}"]`);
      if (input) input.value = value;
    });
  }
}

async function loadDocuments() {
  state.documents = await api("/api/literature");
}

async function loadEntries() {
  const params = [...state.activeProjectTagFilters].map((tag) => encodeURIComponent(tag)).join(",");
  const repository = await api(`/api/literature/canonical${params ? `?tags=${params}` : ""}`);
  state.stagedLiteratureEntries = repository.staged_entries || [];
  state.curatedLiteratureEntries = repository.curated_entries || [];
  renderTwoStageLiterature();
}

async function loadProjectTags() {
  const result = await api("/api/project-tags");
  state.projectTags = result.tags || [];
  renderProjectTagFilters();
}

function projectTagOptions() {
  const byKey = new Map();
  (state.projectTags || []).forEach((tag) => byKey.set(tag.key || normalizeText(tag.label), tag.label));
  (state.projects || []).forEach((project) => {
    if (project.slug) byKey.set(normalizeText(project.slug), project.slug);
    if (project.ontology_id) byKey.set(normalizeText(project.ontology_id), project.ontology_id);
  });
  return [...byKey.entries()].map(([key, label]) => ({ key, label })).sort((a, b) => a.label.localeCompare(b.label));
}

function renderProjectTagButtons(container, selectedTags, onToggle) {
  container.innerHTML = "";
  const selected = new Set((selectedTags || []).map((tag) => normalizeText(tag)));
  projectTagOptions().forEach((tag) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `project-tag${selected.has(tag.key) ? " active" : ""}`;
    button.textContent = tag.label;
    button.setAttribute("aria-pressed", selected.has(tag.key) ? "true" : "false");
    button.addEventListener("click", () => onToggle(tag.label, button));
    container.append(button);
  });
  if (!container.children.length) {
    const empty = document.createElement("span");
    empty.className = "message";
    empty.textContent = "No project tags available yet.";
    container.append(empty);
  }
}

function renderProjectTagFilters() {
  const container = document.querySelector("#literature-tag-filters");
  if (!container) return;
  renderProjectTagButtons(container, [...state.activeProjectTagFilters], (label) => {
    const key = normalizeText(label);
    if (state.activeProjectTagFilters.has(key)) state.activeProjectTagFilters.delete(key);
    else state.activeProjectTagFilters.add(key);
    renderProjectTagFilters();
    loadEntries().catch((error) => setError("#literature-repository-message", error.message));
  });
}

function literatureEditor(entry, stage) {
  const record = document.createElement("article");
  record.className = "literature-record";
  const selectedTagLabels = new Set(entry.project_tags || []);
  const status = literatureWorkflowStatus(entry, stage);
  record.innerHTML = `<details open class="markdown-details">
    <summary>${escapeHtml(entry.title || "Untitled literature entry")} | ${escapeHtml(stage === "curated" ? "Curated Literature" : "New / Uncurated Literature")} | ${escapeHtml(status)}</summary>
    <div class="stack literature-entry-editor">
      <label>Title<input data-field="title" value="${escapeHtml(entry.title || "")}" /></label>
      <label>Authors<input data-field="authors" value="${escapeHtml(Array.isArray(entry.authors) ? entry.authors.join("; ") : entry.authors || "")}" /></label>
      <label>Year<input data-field="year" value="${escapeHtml(entry.year || "")}" /></label>
      <label>Journal<input data-field="journal" value="${escapeHtml(entry.journal || "")}" /></label>
      <label>DOI<input data-field="doi" value="${escapeHtml(entry.doi || "")}" /></label>
      <label>PII<input data-field="pii" value="${escapeHtml(entry.pii || "")}" /></label>
      <label>Reviewed Markdown<textarea data-field="markdown" rows="18"></textarea></label>
      <div><span class="helper">Project tags</span><div data-field="project_tags" class="project-tag-row"></div></div>
      <p class="description"><strong>Curation status:</strong> ${escapeHtml(status)} | <strong>Repository:</strong> ${escapeHtml(entry.repository_stage || stage)}</p>
      <p class="description"><strong>Content source:</strong> ${escapeHtml(literatureSourceLabel(entry.content_source, "content"))} | <strong>Metadata source:</strong> ${escapeHtml(literatureSourceLabel(entry.metadata_source, "metadata"))}</p>
      <p class="description"><strong>Extraction mode:</strong> ${escapeHtml(entry.extraction_mode || "publisher_api_required")} | <strong>PDF used:</strong> ${entry.pdf_used ? "Yes" : "No"} | <strong>Fallback used:</strong> ${entry.fallback_used ? "Yes" : "No"}</p>
      <p class="description"><strong>Literature type:</strong> ${escapeHtml(entry.literature_type || "journal_article")} | <strong>Metadata quality:</strong> ${entry.metadata_quality?.ok === false ? "Needs attention" : "OK"} | <strong>Markdown quality:</strong> ${entry.markdown_quality?.ok === false ? "Needs manual review" : "OK"}</p>
      <p class="description"><strong>DOI used:</strong> ${escapeHtml(entry.doi_used || entry.lookup_doi || "-")} | <strong>PII used:</strong> ${escapeHtml(entry.pii_used || entry.lookup_pii || "-")} | <strong>XML retrieved:</strong> ${entry.xml_retrieved ? "Yes" : "No"}</p>
      <p class="description"><strong>Full text:</strong> ${escapeHtml(entry.fulltext_status || "unknown")} | <strong>Markdown:</strong> ${escapeHtml(entry.markdown_status || (entry.markdown_available ? "available" : "manual_markdown_required"))} | <strong>Source quality:</strong> ${escapeHtml(entry.source_quality || "unknown")}</p>
      ${entry.blocked_reason ? `<p class="warning"><strong>Blocked:</strong> ${escapeHtml(entry.blocked_reason)}</p>` : ""}
      <p class="description"><strong>API identifier used:</strong> ${escapeHtml(entry.api_identifier_used_kind ? `${entry.api_identifier_used_kind.toUpperCase()}: ${entry.api_identifier_used_value || ""}` : "-")} | <strong>Identifier attempts:</strong> ${escapeHtml((entry.api_identifier_attempts || []).map((attempt) => `${attempt.kind}:${attempt.status}`).join(", ") || "-")}</p>
      ${(entry.validation_errors || []).length ? `<div class="warning"><strong>Validation errors</strong><ul>${entry.validation_errors.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}</ul></div>` : ""}
      ${(entry.metadata_quality?.warnings || []).length ? `<div class="warning"><strong>Metadata warnings</strong><ul>${entry.metadata_quality.warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}</ul></div>` : ""}
      ${(entry.markdown_quality?.errors || []).length ? `<div class="warning"><strong>Markdown quality errors</strong><ul>${entry.markdown_quality.errors.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}</ul></div>` : ""}
      ${entry.fallback_authorized_by ? `<p class="warning"><strong>Fallback authorization:</strong> ${escapeHtml(entry.fallback_authorized_by)}</p>` : ""}
      ${(entry.extraction_warnings || []).length ? `<div class="warning"><strong>Extraction warnings</strong><ul>${entry.extraction_warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}</ul></div>` : ""}
      <p class="description">Import provider: ${escapeHtml(entry.source_type || "unknown")} | API retrieval: ${escapeHtml(entry.api_retrieval_status || "not attempted")} | Imported: ${escapeHtml(entry.import_status || "unknown")} | Pipeline: ${escapeHtml(entry.literature_metadata?.pipeline_version || entry.pipeline_version || "unknown")}</p>
      <div class="button-row"></div>
    </div>
  </details>`;
  record.querySelector('[data-field="markdown"]').value = entry.literature_markdown || "";
  const tagContainer = record.querySelector('[data-field="project_tags"]');
  const rerenderTags = () => renderProjectTagButtons(tagContainer, [...selectedTagLabels], (label) => {
    const existing = [...selectedTagLabels].find((tag) => normalizeText(tag) === normalizeText(label));
    if (existing) selectedTagLabels.delete(existing);
    else selectedTagLabels.add(label);
    rerenderTags();
  });
  rerenderTags();
  const values = () => ({
    metadata: {
      title: record.querySelector('[data-field="title"]').value,
      authors: record.querySelector('[data-field="authors"]').value.split(";").map((value) => value.trim()).filter(Boolean),
      year: record.querySelector('[data-field="year"]').value || null,
      journal: record.querySelector('[data-field="journal"]').value,
      doi: record.querySelector('[data-field="doi"]').value,
      pii: record.querySelector('[data-field="pii"]').value,
    },
    markdown: record.querySelector('[data-field="markdown"]').value,
    project_tags: [...selectedTagLabels],
  });
  const actions = record.querySelector(".button-row");
  const save = document.createElement("button");
  save.type = "button";
  save.textContent = stage === "staged" ? "Save review" : "Save curated entry";
  save.addEventListener("click", async (event) => {
    await withButtonFeedback(event.currentTarget, "Saving", async () => {
      await api(`/api/literature/${stage}/${encodeURIComponent(entry.id)}`, { method: "PATCH", body: JSON.stringify(values()) });
      await loadEntries();
      setSuccess("#literature-repository-message", "Literature review saved.");
    }).catch((error) => setError("#literature-repository-message", error.message));
  });
  actions.append(save);
  if (stage === "staged") {
    const uploadManual = document.createElement("button");
    uploadManual.type = "button";
    uploadManual.className = "secondary";
    uploadManual.textContent = entry.markdown_available ? "Validate as manual Markdown" : "Upload / validate manual Markdown";
    uploadManual.addEventListener("click", async (event) => {
      await withButtonFeedback(event.currentTarget, "Validating", async () => {
        const result = await api(`/api/literature/staged/${encodeURIComponent(entry.id)}/manual-markdown`, { method: "POST", body: JSON.stringify({ markdown: record.querySelector('[data-field="markdown"]').value }) });
        await loadEntries();
        if (result.validation_report?.ok) setSuccess("#literature-repository-message", "Manual Markdown validated and selected as canonical Markdown.");
        else setError("#literature-repository-message", `Manual Markdown is still blocked: ${(result.validation_report?.errors || []).join("; ")}`);
      }).catch((error) => setError("#literature-repository-message", error.message));
    });
    const promote = document.createElement("button");
    promote.type = "button";
    promote.textContent = "Promote to curated literature";
    promote.addEventListener("click", async (event) => {
      await withButtonFeedback(event.currentTarget, "Promoting", async () => {
        await api(`/api/literature/staged/${encodeURIComponent(entry.id)}/promote`, { method: "POST", body: JSON.stringify(values()) });
        state.activeLiteratureTab = "curated";
        await loadEntries();
        setSuccess("#literature-repository-message", "Entry promoted to curated literature.");
      }).catch((error) => setError("#literature-repository-message", error.message));
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "Reject / delete staged entry";
    remove.addEventListener("click", async () => {
      if (!window.confirm("Delete this staged copy? Curated literature and original Zotero data are not affected.")) return;
      await api(`/api/literature/staged/${encodeURIComponent(entry.id)}/reject`, { method: "POST", body: JSON.stringify({ delete: true, confirm: true }) });
      await loadEntries();
      setSuccess("#literature-repository-message", "Staged entry deleted.");
    });
    actions.append(uploadManual, promote, remove);
  }
  return record;
}

function literatureSourceLabel(value, kind) {
  const labels = {
    elsevier_xml: kind === "metadata" ? "Elsevier API" : "Elsevier XML",
    pdf_extraction: "PDF fallback",
    pdf_heuristic: "PDF heuristic",
    "zotero+elsevier_xml": "Zotero + Elsevier API",
    "zotero+crossref": "Zotero + Crossref",
    crossref: "Crossref",
    zotero: "Zotero",
    manual: "Manual input",
    provided_markdown: "Provided Markdown",
  };
  return labels[value] || value || "Unknown";
}

function literatureWorkflowStatus(entry, stage) {
  const values = [
    entry.curation_status,
    entry.import_status,
    entry.duplicate_status,
    entry.literature_status?.state,
    entry.markdown_status,
    entry.fulltext_status,
  ].map((value) => String(value || "").trim()).filter(Boolean);
  if (values.some((value) => ["duplicate", "duplicated"].includes(value))) return "duplicate";
  if (values.includes("rejected")) return "rejected";
  if (stage === "curated") {
    if (values.includes("accepted")) return "accepted";
    if (values.includes("promoted")) return "promoted";
    return "curated";
  }
  if (values.includes("manual_markdown_required") || values.includes("needs_manual_markdown")) return "needs_manual_markdown";
  if (values.includes("needs_review") || values.includes("curation_blocked")) return "needs_review";
  if (entry.markdown_available || entry.markdown_file || values.includes("structured_markdown_created")) return "structured_markdown_created";
  if (entry.title || entry.doi || entry.pii || values.includes("metadata_resolved")) return "metadata_resolved";
  return "new";
}

function literatureSearchText(entry) {
  return normalizeText([
    entry.title,
    Array.isArray(entry.authors) ? entry.authors.join(" ") : entry.authors,
    entry.year,
    entry.journal,
    entry.doi,
    entry.pii,
    entry.literature_type,
    entry.metadata_source,
    entry.content_source,
    entry.source_type,
    entry.api_retrieval_status,
    entry.fulltext_status,
    entry.markdown_status,
    ...(entry.project_tags || []),
  ].filter(Boolean).join(" "));
}

function entryMatchesActiveProjectTags(entry) {
  if (!state.activeProjectTagFilters.size) return true;
  const tags = new Set((entry.project_tags || []).map((tag) => normalizeText(tag)));
  return [...state.activeProjectTagFilters].every((tag) => tags.has(tag));
}

function filteredTwoStageEntries(stage) {
  const isCurated = stage === "curated";
  const search = normalizeText(document.querySelector(`#${isCurated ? "curated" : "uncurated"}-literature-search`)?.value || "");
  const statusFilter = document.querySelector(`#${isCurated ? "curated" : "uncurated"}-literature-status-filter`)?.value || "all";
  const source = isCurated ? state.curatedLiteratureEntries || [] : state.stagedLiteratureEntries || [];
  return source.filter((entry) => {
    const status = literatureWorkflowStatus(entry, stage);
    const isPromoted = entry.import_status === "promoted" || entry.repository_stage === "curated";
    if (isCurated) {
      if (["rejected", "duplicate"].includes(status)) return false;
    } else if (isPromoted) {
      return false;
    }
    const matchesSearch = !search || literatureSearchText(entry).includes(search);
    const matchesStatus = statusFilter === "all" || status === statusFilter || entry.import_status === statusFilter || entry.curation_status === statusFilter;
    return matchesSearch && matchesStatus && entryMatchesActiveProjectTags(entry);
  });
}

function setLiteratureTab(tab) {
  state.activeLiteratureTab = tab === "uncurated" ? "uncurated" : "curated";
  document.querySelectorAll("[data-literature-tab]").forEach((button) => {
    const active = button.dataset.literatureTab === state.activeLiteratureTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll("[data-literature-panel]").forEach((panel) => {
    const active = panel.dataset.literaturePanel === state.activeLiteratureTab;
    panel.classList.toggle("hidden", !active);
    panel.toggleAttribute("hidden", !active);
  });
}

function renderTwoStageLiterature() {
  const staged = document.querySelector("#staged-literature-entries");
  const curated = document.querySelector("#curated-literature-entries");
  if (!staged || !curated) return;
  staged.innerHTML = "";
  curated.innerHTML = "";
  setLiteratureTab(state.activeLiteratureTab);
  filteredTwoStageEntries("staged").forEach((entry) => staged.append(literatureEditor(entry, "staged")));
  filteredTwoStageEntries("curated").forEach((entry) => curated.append(literatureEditor(entry, "curated")));
  if (!staged.children.length) staged.innerHTML = '<p class="message">No new or uncurated literature matches the current filters.</p>';
  if (!curated.children.length) curated.innerHTML = '<p class="message">No curated literature matches the current filters.</p>';
}

function renderEntries() {
  const list = document.querySelector("#zotero-entries");
  if (!list) return;
  list.innerHTML = "";

  const query = normalizeText(document.querySelector("#zotero-filter")?.value);
  const reviewFilter = document.querySelector("#literature-review-filter")?.value || "all";
  state.entries.filter((entry) => {
    const review = entry.literature_review || entry.literature_status || {};
    const matchesText = !query || searchableText(entry).includes(query);
    const matchesReview =
      reviewFilter === "all" ||
      review.state === reviewFilter ||
      review.document_role === reviewFilter ||
      review.metadata_match_status === reviewFilter ||
      review.extraction_quality === reviewFilter ||
      (reviewFilter === "requires_manual_review" && review.requires_manual_review);
    const tags = new Set((entry.project_tags || []).map((tag) => normalizeText(tag)));
    const matchesTags = !state.activeProjectTagFilters.size || [...state.activeProjectTagFilters].every((tag) => tags.has(tag));
    return matchesText && matchesReview && matchesTags;
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
      entry.pii ? `PII ${entry.pii}` : "",
      entry.provider_item_key ? `Zotero key ${entry.provider_item_key}` : "",
    ].filter(Boolean).map(safeText).join(" | ") || "No bibliographic metadata available.";
    const review = entry.literature_review || entry.literature_status || {};
    const reviewMeta = document.createElement("div");
    reviewMeta.className = "status-grid literature-quality-grid";
    [
      ["Metadata title", review.metadata_title || entry.title],
      ["Detected title", review.detected_title || "unknown"],
      ["Title match", `${review.metadata_match_status || "unknown"}${review.title_similarity_score !== undefined && review.title_similarity_score !== null ? ` (${review.title_similarity_score})` : ""}`],
      ["State", review.state || "unknown"],
      ["Source type", entry.source_type || review.source_type || entry.provider || "unknown"],
      ["Import status", entry.import_status || review.import_status || "unknown"],
      ["Duplicate status", entry.duplicate_status || review.duplicate_status || "unknown"],
      ["Document role", review.document_role || "unknown"],
      ["Extraction quality", review.extraction_quality || "unknown"],
      ["Engine", review.extraction_engine_used || "unknown"],
      ["DOI match", review.doi_match_status || "unknown"],
      ["Words", review.word_count || "unknown"],
      ["Manual review", review.requires_manual_review ? "yes" : "no"],
      ["Included in LLM extraction", review.included_in_automatic_llm_extraction ? "yes" : "no"],
    ].forEach(([label, value]) => {
      const item = document.createElement("div");
      item.className = "status-card";
      item.innerHTML = `<strong>${escapeHtml(label)}</strong><span>${escapeHtml(value)}</span>`;
      reviewMeta.append(item);
    });
    const abstract = document.createElement("p");
    abstract.textContent = sectionPreviewText(entry);
    text.append(title, meta, reviewMeta, abstract);

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

    const selectedTagLabels = new Set(entry.project_tags || []);
    const tagButtons = document.createElement("div");
    tagButtons.className = "project-tag-row";
    tagButtons.setAttribute("aria-label", "Project tags");
    const rerenderEntryTags = () => renderProjectTagButtons(tagButtons, [...selectedTagLabels], (label) => {
      const existing = [...selectedTagLabels].find((tag) => normalizeText(tag) === normalizeText(label));
      if (existing) selectedTagLabels.delete(existing);
      else selectedTagLabels.add(label);
      rerenderEntryTags();
    });
    rerenderEntryTags();
    const saveTags = document.createElement("button");
    saveTags.type = "button";
    saveTags.textContent = "Save project tags";
    saveTags.addEventListener("click", async (event) => {
      await withButtonFeedback(event.currentTarget, "Saving tags", async () => {
        const projectTags = [...selectedTagLabels];
        await api(`/api/literature/${encodeURIComponent(entry.id)}/tags`, {
          method: "POST",
          body: JSON.stringify({ project_tags: projectTags }),
        });
        await Promise.all([loadProjectTags(), loadEntries(), loadProjects()]);
        setSuccess("#literature-repository-message", "Project tags saved.");
      }).catch((error) => setError("#literature-repository-message", error.message));
    });
    const tagMeta = document.createElement("span");
    tagMeta.className = "message";
    tagMeta.textContent = (entry.project_tags || []).length
      ? `Project tags: ${(entry.project_tags || []).join(", ")}`
      : "No project tags";

    actions.append(zoteroLink, tagButtons, saveTags, tagMeta);
    if (entry.markdown_file) {
      const toggleInclude = document.createElement("button");
      toggleInclude.type = "button";
      toggleInclude.textContent = review.include_in_llm_extraction ? "Exclude from LLM extraction" : "Include in LLM extraction";
      toggleInclude.addEventListener("click", async (event) => {
        await updateLiteratureReview(
          entry,
          { include_in_llm_extraction: !review.include_in_llm_extraction },
          event.currentTarget
        );
      });
      const approveWeak = document.createElement("button");
      approveWeak.type = "button";
      approveWeak.className = "secondary";
      approveWeak.textContent = "Approve title match";
      approveWeak.disabled = !["weak_match", "metadata_mismatch", "unknown"].includes(review.metadata_match_status);
      approveWeak.addEventListener("click", async (event) => {
        await updateLiteratureReview(
          entry,
          {
            metadata_match_status: "matched",
            requires_manual_review: false,
            include_in_llm_extraction: ["domain_article", "review_article"].includes(review.document_role),
          },
          event.currentTarget
        );
      });
      const roleSelect = document.createElement("select");
      roleSelect.setAttribute("aria-label", "Document role");
      LITERATURE_DOCUMENT_ROLES.forEach((role) => {
        const option = document.createElement("option");
        option.value = role;
        option.textContent = role;
        option.selected = role === review.document_role;
        roleSelect.append(option);
      });
      const saveRole = document.createElement("button");
      saveRole.type = "button";
      saveRole.textContent = "Save role";
      saveRole.addEventListener("click", async (event) => {
        await updateLiteratureReview(entry, { document_role: roleSelect.value }, event.currentTarget);
      });
      const blockButton = document.createElement("button");
      blockButton.type = "button";
      blockButton.className = "secondary";
      blockButton.textContent = review.state === "blocked" ? "Unblock" : "Block";
      blockButton.addEventListener("click", async (event) => {
        const blocked = review.state === "blocked";
        await updateLiteratureReview(
          entry,
          {
            state: blocked ? "ready_for_llm" : "blocked",
            include_in_llm_extraction: blocked,
            requires_manual_review: !blocked,
          },
          event.currentTarget
        );
      });
      const regenerateClean = literatureActionButton(entry, "Regenerate clean", "/api/literature/repository/regenerate-clean");
      const regenerateContext = literatureActionButton(entry, "Regenerate context", "/api/literature/repository/regenerate-context");
      const retryEngine = document.createElement("select");
      retryEngine.setAttribute("aria-label", "Retry extraction engine");
      LITERATURE_RETRY_ENGINES.forEach((engine) => {
        const option = document.createElement("option");
        option.value = engine;
        option.textContent = engine;
        retryEngine.append(option);
      });
      const retryButton = document.createElement("button");
      retryButton.type = "button";
      retryButton.className = "secondary";
      retryButton.textContent = "Retry extraction";
      retryButton.addEventListener("click", async (event) => {
        await runLiteratureRepositoryAction(entry, "/api/literature/repository/retry-extraction", event.currentTarget, {
          engine: retryEngine.value,
        });
      });
      actions.append(
        toggleInclude,
        approveWeak,
        roleSelect,
        saveRole,
        blockButton,
        regenerateClean,
        regenerateContext,
        retryEngine,
        retryButton
      );
    }
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
    if (Array.isArray(review.warnings) && review.warnings.length) {
      const warningList = document.createElement("ul");
      warningList.className = "section-heading-list";
      review.warnings.forEach((warning) => {
        const item = document.createElement("li");
        item.textContent = warning;
        warningList.append(item);
      });
      diagnostics.append(warningList);
    }
    [
      ["Markdown file", entry.literature_status?.markdown_source_file],
      ["Quality report", review.metadata_report_file],
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
    const cleanPre = document.createElement("pre");
    cleanPre.className = "markdown-preview";
    cleanPre.textContent = entry.clean_markdown || "Clean Markdown artifact is not available yet.";
    const contextPre = document.createElement("pre");
    contextPre.className = "markdown-preview";
    contextPre.textContent = entry.llm_context_markdown || "LLM context artifact is not available yet.";
    details.append(
      summary,
      diagnostics,
      previewBlock("Raw / canonical Markdown", pre),
      previewBlock("Clean Markdown", cleanPre),
      previewBlock("LLM context Markdown", contextPre)
    );

    record.append(header, details);
    list.append(record);
  });
  if (!list.children.length) {
    list.innerHTML = '<p class="message">No literature records found.</p>';
  }
}

function literatureActionButton(entry, label, endpoint) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary";
  button.textContent = label;
  button.addEventListener("click", async (event) => {
    await runLiteratureRepositoryAction(entry, endpoint, event.currentTarget);
  });
  return button;
}

async function runLiteratureRepositoryAction(entry, endpoint, button, extra = {}) {
  if (!entry.markdown_file) {
    setError("#literature-repository-message", "This literature record does not have a Markdown file to update.");
    return;
  }
  await withButtonFeedback(button, "Working", async () => {
    await api(endpoint, {
      method: "POST",
      body: JSON.stringify({ markdown_file: entry.markdown_file, ...extra }),
    });
    await loadEntries();
    setSuccess("#literature-repository-message", "Literature artifact action completed.");
  }).catch((error) => setError("#literature-repository-message", error.message));
}

function previewBlock(label, pre) {
  const wrapper = document.createElement("details");
  wrapper.open = label === "Raw / canonical Markdown";
  const summary = document.createElement("summary");
  summary.textContent = label;
  wrapper.append(summary, pre);
  return wrapper;
}

async function updateLiteratureReview(entry, updates, button) {
  if (!entry.markdown_file) {
    setError("#literature-repository-message", "This literature record does not have a Markdown file to update.");
    return;
  }
  await withButtonFeedback(button, "Saving review", async () => {
    await api("/api/literature/repository/review", {
      method: "PATCH",
      body: JSON.stringify({ markdown_file: entry.markdown_file, ...updates }),
    });
    await loadEntries();
    setSuccess("#literature-repository-message", "Literature review metadata saved.");
  }).catch((error) => setError("#literature-repository-message", error.message));
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

async function loadRelationTypes() {
  try {
    const payload = await api("/api/ontology/relation-types");
    state.relationTypes = payload.relation_types || [];
  } catch {
    state.relationTypes = [];
  }
  populateRelationTypeSelects();
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

async function loadLlmProviders() {
  const payload = await api("/api/config/llm/providers");
  state.llmProviders = payload.providers || [];
  const providerSelect = document.querySelector("#llm-provider-select");
  const modelSelect = document.querySelector("#llm-model-select");
  if (!providerSelect || !modelSelect) return;
  const currentProvider = state.status?.llm?.provider || state.llmProviders[0]?.id || "gemini";
  providerSelect.innerHTML = state.llmProviders
    .map((provider) => `<option value="${safeText(provider.id)}">${safeText(provider.label)}</option>`)
    .join("");
  providerSelect.value = currentProvider;
  const renderModels = () => {
    const provider = state.llmProviders.find((item) => item.id === providerSelect.value);
    const currentModel = state.status?.llm?.model || provider?.models?.[0] || "";
    modelSelect.innerHTML = (provider?.models?.length ? provider.models : [provider?.default_model || ""])
      .filter(Boolean)
      .map((model) => `<option value="${safeText(model)}">${safeText(model)}</option>`)
      .join("");
    if (currentModel && [...modelSelect.options].some((option) => option.value === currentModel)) {
      modelSelect.value = currentModel;
    }
    const form = document.querySelector("#llm-config-form");
    if (!form) return;
    const envInput = form.querySelector('[name="api_key_env_var"]');
    const baseInput = form.querySelector('[name="base_url"]');
    const manualModel = form.querySelector('[name="model"]');
    if (envInput && !envInput.value) {
      envInput.value = state.status?.llm?.api_key_env_var || provider?.api_key_env_vars?.[0] || "";
    }
    if (baseInput && !baseInput.value) {
      baseInput.value = state.status?.llm?.base_url || provider?.default_base_url || "";
    }
    if (manualModel) {
      manualModel.placeholder = provider?.manual_model ? "Required custom model name" : "Optional custom model name";
    }
  };
  providerSelect.onchange = () => {
    const form = document.querySelector("#llm-config-form");
    form?.querySelector('[name="api_key_env_var"]') && (form.querySelector('[name="api_key_env_var"]').value = "");
    form?.querySelector('[name="base_url"]') && (form.querySelector('[name="base_url"]').value = "");
    renderModels();
  };
  renderModels();
}

function fillCandidate(node, candidate) {
  node.dataset.id = candidate.id;
  node.dataset.candidate = JSON.stringify(candidate);
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
  const graphReview = candidate.graph_review || {};
  node.querySelector(".relation-source").value = graphReview.relation_source || "";
  node.querySelector(".relation-target").value = graphReview.relation_target || "";
  node.querySelector(".graph-review").value = JSON.stringify(graphReview, null, 2);
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
  node.addEventListener("click", () => activateCandidateForGraph(node));
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
    graph_review: graphReviewFromNode(node),
  };
}

function graphReviewFromNode(node) {
  let review = {};
  try {
    review = JSON.parse(node.querySelector(".graph-review").value || "{}");
  } catch {
    review = {};
  }
  review.relation_source = node.querySelector(".relation-source").value || review.relation_source || null;
  review.relation_target = node.querySelector(".relation-target").value || review.relation_target || null;
  return review;
}

function activeCandidateNode() {
  if (!state.activeCandidateId) return null;
  return document.querySelector(`.candidate[data-id="${state.activeCandidateId}"]`);
}

function activateCandidateForGraph(node) {
  state.activeCandidateId = node.dataset.id;
  document.querySelectorAll(".candidate").forEach((candidateNode) => {
    candidateNode.classList.toggle("is-active-candidate", candidateNode === node);
  });
  const candidate = JSON.parse(node.dataset.candidate || "{}");
  const context = node.querySelector(".parent").value || candidate.selected_local?.iri || candidate.selected_local?.term_id || "";
  if (context && state.ontologyTree) {
    const match = searchOntologyNodes(state.ontologyTree, context)[0];
    if (match) {
      state.selectedOntologyNodeId = match.id;
      state.ontologyFocusNodeId = match.id;
      state.ontologyCenterOnSelected = true;
      renderOntologyTree().catch((error) => setError("#ols-message", error.message));
    }
  }
  updateGraphCurationStatus();
}

function selectedOntologyNodePayload() {
  if (!state.ontologyTree || !state.selectedOntologyNodeId) return null;
  return ontologyIndexes(state.ontologyTree).byId.get(state.selectedOntologyNodeId) || null;
}

function updateGraphCurationStatus() {
  const status = document.querySelector("#graph-curation-active");
  if (!status) return;
  const candidateNode = activeCandidateNode();
  const selected = selectedOntologyNodePayload();
  status.textContent = `Candidate: ${candidateNode?.querySelector(".label")?.value || "none"} | Selected node: ${selected?.label || selected?.id || "none"}`;
}

function updateCandidateGraphReview(mutator) {
  const node = activeCandidateNode();
  const selected = selectedOntologyNodePayload();
  if (!node || !selected) {
    setError("#ols-message", "Select a candidate and an ontology node first.");
    return null;
  }
  const review = graphReviewFromNode(node);
  mutator(review, selected, node);
  node.querySelector(".graph-review").value = JSON.stringify(review, null, 2);
  updateGraphCurationStatus();
  return { node, selected, review };
}

function setSelectedNodeAsParent() {
  const result = updateCandidateGraphReview((review, selected, node) => {
    node.querySelector(".parent").value = selected.id;
    node.querySelector(".decision").value = "propose_new_term";
    review.parent_class = { id: selected.id, label: selected.label || selected.id, source: "ontology_graph" };
  });
  if (result) setSuccess("#ols-message", "Selected ontology node set as proposed parent.");
}

function setSelectedNodeAsRelationRole(role) {
  const result = updateCandidateGraphReview((review, selected, node) => {
    node.querySelector(role === "source" ? ".relation-source" : ".relation-target").value = selected.id;
    review[`relation_${role}`] = selected.id;
  });
  if (result) setSuccess("#ols-message", `Selected ontology node set as relation ${role}.`);
}

function compareCandidateWithSelectedNode() {
  const result = updateCandidateGraphReview((review, selected, node) => {
    const candidateLabel = normalizeText(node.querySelector(".label").value);
    const selectedLabel = normalizeText(selected.label || selected.id);
    review.comparison = {
      selected_node: { id: selected.id, label: selected.label || selected.id },
      label_overlap: candidateLabel && selectedLabel ? Math.round(SequenceMatcherRatio(candidateLabel, selectedLabel) * 100) / 100 : null,
    };
  });
  if (result) setSuccess("#ols-message", "Candidate comparison recorded in graph review proposals.");
}

function SequenceMatcherRatio(left, right) {
  if (!left || !right) return 0;
  if (left === right) return 1;
  const shorter = left.length < right.length ? left : right;
  const longer = left.length >= right.length ? left : right;
  let matches = 0;
  shorter.split(/\s+/).forEach((token) => {
    if (token && longer.includes(token)) matches += token.length;
  });
  return matches / Math.max(1, longer.length);
}

function markCandidateDuplicateOfSelectedNode() {
  const result = updateCandidateGraphReview((review, selected, node) => {
    node.querySelector(".decision").value = "use_existing_local_term";
    review.duplicate_of = { id: selected.id, label: selected.label || selected.id, source: "ontology_graph" };
    review.review_status_suggestion = "duplicate";
  });
  if (result) setSuccess("#ols-message", "Duplicate target recorded. Save the candidate to persist it.");
}

function addGraphRelationProposal() {
  const node = activeCandidateNode();
  if (!node) {
    setError("#ols-message", "Select a candidate first.");
    return;
  }
  const relationSelect = document.querySelector("#graph-relation-type");
  const review = graphReviewFromNode(node);
  const relationType = state.relationTypes.find((item) => item.label === relationSelect?.value || item.id === relationSelect?.value);
  const source = node.querySelector(".relation-source").value;
  const target = node.querySelector(".relation-target").value || selectedOntologyNodePayload()?.id || "";
  const warnings = validateGraphRelationProposal({ source, target, relationType, review });
  document.querySelector("#graph-relation-warnings").textContent = warnings.join(" ");
  review.proposed_relations = review.proposed_relations || [];
  if (!warnings.some((warning) => warning.includes("missing"))) {
    review.proposed_relations.push({
      source,
      target,
      relation: relationType.label,
      relation_id: relationType.id,
      status: "proposed_for_review",
      source_kind: "graph_assisted_candidate_review",
    });
    node.querySelector(".graph-review").value = JSON.stringify(review, null, 2);
    setSuccess("#ols-message", "Proposed relation added to candidate review data.");
  }
}

function validateGraphRelationProposal({ source, target, relationType, review }) {
  const warnings = [];
  if (!source) warnings.push("Relation source missing.");
  if (!target) warnings.push("Relation target missing.");
  if (!relationType) warnings.push("Relation type missing.");
  const duplicate = (review.proposed_relations || []).some(
    (relation) => relation.source === source && relation.target === target && relation.relation === relationType?.label
  );
  if (duplicate) warnings.push("Relation duplicates an existing candidate proposal.");
  const existing = (state.ontologyTree?.relation_edges || []).some(
    (edge) => edge.source === source && edge.target === target && (edge.relation === relationType?.label || edge.relation_label === relationType?.label)
  );
  if (existing) warnings.push("Relation already exists in the indexed ontology.");
  return warnings;
}

function populateRelationTypeSelects() {
  const select = document.querySelector("#graph-relation-type");
  if (!select) return;
  select.innerHTML = state.relationTypes
    .map((relation) => `<option value="${safeText(relation.label)}">${safeText(relation.label)}</option>`)
    .join("");
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

function bindZoteroMetadataSync() {
  const configForm = requiredZoteroElement("#zotero-config-form");
  if (configForm) {
    configForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = event.currentTarget.querySelector('button[type="submit"]');
      if (!button) {
        reportMissingZoteroElement('#zotero-config-form button[type="submit"]');
        return;
      }
      try {
        await withButtonFeedback(button, "Saving", async () => {
          const payload = {
            library_type: zoteroInputValue("#zotero-library-type", { required: true, label: "library type" }),
            library_id: zoteroInputValue("#zotero-library-id", { required: true, label: "library ID" }),
            api_key: zoteroInputValue("#zotero-api-key", { label: "API key" }) || null,
            collection_key: zoteroInputValue("#zotero-collection-key", { label: "collection key" }) || null,
            base_url: zoteroInputValue("#zotero-api-base-url", { label: "API base URL" }) || null,
          };
          await api("/api/config/zotero", {
            method: "POST",
            body: JSON.stringify(payload),
          });
          const apiKeyInput = document.querySelector("#zotero-api-key");
          if (apiKeyInput) apiKeyInput.value = "";
          await loadStatus();
          await loadSavedConfigs();
          setSuccess("#zotero-message", "Zotero configuration saved.");
        });
      } catch (error) {
        setError("#zotero-message", error.message);
      }
    });
  }

  const testButton = requiredZoteroElement("#test-zotero");
  if (testButton) {
    testButton.addEventListener("click", async (event) => {
      try {
        await withButtonFeedback(event.currentTarget, "Testing", async () => {
          const result = await api("/api/config/test-zotero", { method: "POST", body: "{}" });
          setSuccess("#zotero-message", `Zotero connection ok. Items seen: ${result.items_seen}`);
        });
      } catch (error) {
        setError("#zotero-message", error.message);
      }
    });
  }

  const syncButton = requiredZoteroElement("#sync-zotero");
  if (syncButton) {
    syncButton.addEventListener("click", async (event) => {
      try {
        await withButtonFeedback(event.currentTarget, "Syncing", async () => {
          const limitToggle = document.querySelector("#zotero-use-limit");
          const limitInput = document.querySelector("#zotero-limit");
          if (!limitToggle || !limitInput) {
            reportMissingZoteroElement(!limitToggle ? "#zotero-use-limit" : "#zotero-limit");
            return;
          }
          const limit = limitToggle.checked ? Number(limitInput.value || 0) || null : null;
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
  }

  const importTestButton = document.querySelector("#import-test-zotero");
  if (!importTestButton) {
    console.error("Missing Zotero sync form element: #import-test-zotero");
  } else {
    importTestButton.addEventListener("click", async (event) => {
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
  }
}

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
          api_key_env_var: payload.api_key_env_var || null,
          model: payload.model || payload.model_select || null,
          base_url: payload.base_url || null,
          temperature: Number(payload.temperature || 0),
          max_output_tokens: Number(payload.max_output_tokens || 1024),
          timeout_seconds: Number(payload.timeout_seconds || 30),
          retry_count: Number(payload.retry_count || 1),
          stream: Boolean(payload.stream),
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

document.querySelector("#test-llm")?.addEventListener("click", async (event) => {
  try {
    await withButtonFeedback(event.currentTarget, "Testing", async () => {
      const result = await api("/api/config/llm/test", { method: "POST", body: "{}" });
      document.querySelector("#llm-test-result").textContent = JSON.stringify(result, null, 2);
      if (result.ok) {
        setSuccess("#extract-message", `LLM test succeeded for ${result.provider} ${result.model} in ${result.latency_ms} ms.`);
      } else {
        setError("#extract-message", result.error || "LLM test failed.");
      }
    });
  } catch (error) {
    setError("#extract-message", error.message);
  }
});

document.querySelector("#load-docker-odk-diagnostics")?.addEventListener("click", async (event) => {
  try {
    await withButtonFeedback(event.currentTarget, "Checking", async () => {
      const result = await api("/api/diagnostics/docker-odk");
      document.querySelector("#docker-odk-diagnostics").textContent = JSON.stringify(result, null, 2);
      const missingTools = Object.entries(result.tools || {}).filter(([, value]) => !value.available).map(([name]) => name);
      if (missingTools.length) {
        setError("#docker-odk-message", `Missing tools: ${missingTools.join(", ")}`);
      } else {
        setSuccess("#docker-odk-message", "ODK/ROBOT command tools were found.");
      }
    });
  } catch (error) {
    setError("#docker-odk-message", error.message);
  }
});

document.querySelector("#literature-config-form")?.addEventListener("submit", async (event) => {
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

document.querySelector("#publisher-config-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const payload = formPayload(form);
  try {
    await withButtonFeedback(button, "Saving", async () => {
      const result = await api("/api/config/publisher", {
        method: "POST",
        body: JSON.stringify({
          elsevier_api_key: payload.elsevier_api_key ?? "",
          elsevier_inst_token: payload.elsevier_inst_token ?? "",
          elsevier_api_base_url: payload.elsevier_api_base_url || "https://api.elsevier.com",
          publisher_api_enrichment_enabled: Boolean(payload.publisher_api_enrichment_enabled),
          literature_extraction_mode: payload.literature_extraction_mode || "publisher_api_required",
          springer_api_key: payload.springer_api_key ?? "",
          wiley_tdm_token: payload.wiley_tdm_token ?? "",
          crossref_contact_email: payload.crossref_contact_email ?? "",
          ncbi_contact_email: payload.ncbi_contact_email ?? "",
          ncbi_api_key: payload.ncbi_api_key ?? "",
          openalex_email: payload.openalex_email ?? "",
        }),
      });
      ["elsevier_api_key", "elsevier_inst_token", "springer_api_key", "wiley_tdm_token", "ncbi_api_key"].forEach((name) => {
        const input = form.querySelector(`[name="${name}"]`);
        if (input) input.value = "";
      });
      await loadStatus();
      await loadSavedConfigs();
      setSuccess("#publisher-config-message", `Publisher settings saved. Key source: ${result.api_key_source}.`);
    });
  } catch (error) {
    setError("#publisher-config-message", error.message);
  }
});

document.querySelector("#test-provider-settings")?.addEventListener("click", async (event) => {
  try {
    await withButtonFeedback(event.currentTarget, "Testing", async () => {
      const result = await api("/api/config/publisher/test", { method: "POST", body: "{}" });
      document.querySelector("#publisher-api-test-result").textContent = JSON.stringify(result, null, 2);
      setSuccess("#publisher-config-message", "Provider API settings loaded with masked credential status.");
    });
  } catch (error) {
    setError("#publisher-config-message", error.message);
  }
});

document.querySelector("#publisher-api-test-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const payload = formPayload(form);
  try {
    await withButtonFeedback(button, "Testing", async () => {
      const result = await api("/api/literature/test-publisher-api", {
        method: "POST",
        body: JSON.stringify({ doi: payload.doi || null, pii: payload.pii || null, sciencedirect_url: payload.sciencedirect_url || null }),
      });
      document.querySelector("#publisher-api-test-result").textContent = JSON.stringify(result, null, 2);
      setSuccess("#publisher-api-test-message", `Elsevier XML retrieved. Sections: ${result.section_count}; PDF used: ${result.pdf_used ? "Yes" : "No"}.`);
    });
  } catch (error) {
    setError("#publisher-api-test-message", error.message);
  }
});

document.querySelector("#refresh-literature-import-diagnostics")?.addEventListener("click", async (event) => {
  try {
    await withButtonFeedback(event.currentTarget, "Refreshing", loadLiteratureImportDiagnostics);
  } catch (error) {
    setError("#publisher-config-message", error.message);
  }
});

document.querySelector("#run-literature-pipeline").addEventListener("click", async (event) => {
  try {
    setMessage("#literature-import-message", "Retrieving structured publisher XML. PDFs are not used unless the configured mode explicitly allows them...");
    await withButtonFeedback(event.currentTarget, "Importing", async () => {
      const form = document.querySelector("#literature-config-form");
      const values = formPayload(form);
      const body = values.local_literature_source_path
        ? { pdf_dir: values.local_literature_source_path }
        : { zotero_storage: values.zotero_literature_storage_path };
      const result = await api("/api/literature/import", { method: "POST", body: JSON.stringify(body) });
      setSuccess(
        "#literature-import-message",
        `Import complete. Mode: ${result.extraction_mode || state.status?.publisher?.literature_extraction_mode || "publisher_api_required"}; XML imported: ${result.xml_imported ?? result.imported}; PDF used: ${result.pdf_used ? "Yes" : "No"}; fallback used: ${result.fallback_used ? "Yes" : "No"}; failed: ${result.failed}.`
      );
      state.activeLiteratureTab = "uncurated";
      await loadStatus();
      await loadEntries();
    });
  } catch (error) {
    setError("#literature-import-message", error.message);
  }
});

document.querySelector("#cleanup-staged-literature")?.addEventListener("click", async (event) => {
  try {
    await withButtonFeedback(event.currentTarget, "Checking", async () => {
      const preview = await api("/api/literature/cleanup-staged", { method: "POST", body: JSON.stringify({ dry_run: true }) });
      const confirmed = window.confirm(
        `Delete ${preview.deleted_count} uncurated staged entrie(s) and ${preview.files_deleted_count} generated file(s), including ${preview.orphan_files_deleted_count} orphan(s), from ${preview.repositories.length} managed literature location(s)? Curated literature, projects, settings, ontology files, and original Zotero files remain untouched.`
      );
      if (!confirmed) {
        setSuccess("#literature-repository-message", `Cleanup preview only: ${preview.files_deleted_count} generated file(s) would be deleted; no files changed.`);
        return;
      }
      const result = await api("/api/literature/cleanup-staged", { method: "POST", body: JSON.stringify({ confirm: true }) });
      await loadEntries();
      setSuccess("#literature-repository-message", `Deleted ${result.deleted_count} staged entrie(s) and ${result.files_deleted_count} generated file(s), including ${result.orphan_files_deleted_count} orphan(s). Curated retained: ${result.curated_count}; directories cleaned: ${result.directories_cleaned_count}; errors: ${result.errors.length}.`);
    });
  } catch (error) {
    setError("#literature-repository-message", error.message);
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
      <p>${[config.provider, config.library_type, config.library_id, config.base_url, config.model, config.extraction_mode].filter(Boolean).map(safeText).join(" | ")}</p>
      <p>API key: ${config.api_key || "not configured"}${config.kind === "publisher" ? ` | Institutional token: ${config.inst_token || "not configured"}` : ""} | Updated: ${config.updated_at || ""}</p>
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

async function loadOntologyStatus() {
  try {
    const status = await api("/api/ontology/status");
    renderOntologyProjectSummary(status);
    setOntologyControlsEnabled(Boolean(status.project && status.selected_file));
    const input = document.querySelector('#ontology-path-form [name="path"]');
    if (input) input.value = status.path || status.selected_file || "";
    renderOntologyFiles(status.scan?.files || [], status.selected_file);
    if (!status.project) {
      state.ontologyTerms = [];
      state.ontologyTree = null;
      document.querySelector("#ontology-terms").innerHTML = "";
      document.querySelector("#ontology-tree").innerHTML = '<p class="message">Select or create a project before working with ontology files.</p>';
      setMessage("#ontology-message", status.message || "Select or create a project before working with ontology files.");
      return;
    }
    if (!status.selected_file) {
      state.ontologyTerms = [];
      state.ontologyTree = null;
      document.querySelector("#ontology-terms").innerHTML = "";
      document.querySelector("#ontology-tree").innerHTML = '<p class="message">No ontology file configured for this project.</p>';
      setMessage("#ontology-message", status.message || "No ontology file configured for this project.");
      return;
    }
    const statusError = status.error ? ` Selected file error: ${status.error}` : "";
    setMessage("#ontology-message", `${status.message || status.scan?.message || "Ontology status loaded."} Parsed terms: ${status.term_count}.${statusError}`);
    await loadOntologyTerms();
  } catch (error) {
    state.ontologyTerms = [];
    document.querySelector("#ontology-terms").innerHTML = '<p class="message">Ontology terms are unavailable.</p>';
    document.querySelector("#ontology-tree").innerHTML = '<p class="message">Ontology tree is unavailable.</p>';
    setError("#ontology-message", projectErrorMessage("Load ontology section for active project", error, "Select an active project with configured ontology paths, or edit the project metadata."));
    throw error;
  }
}

function setOntologyControlsEnabled(enabled) {
  const selectors = [
    "#scan-ontology",
    "#index-ontology",
    "#ontology-search",
    "#ontology-tree-root",
    "#ontology-tree-search",
    "#ontology-tree-jump",
    "#ontology-tree-focus",
    "#ontology-tree-reset",
    "#ontology-tree-depth",
    "#ontology-tree-relations",
    "#ontology-tree-relation-labels",
    "#ontology-tree-node-labels",
    "#ontology-tree-zoom-in",
    "#ontology-tree-zoom-out",
    "#ontology-tree-fit",
    "#ontology-tree-center",
    "#refresh-ontology-tree",
  ];
  selectors.forEach((selector) => {
    const element = document.querySelector(selector);
    if (element) element.disabled = !enabled;
  });
  ["#scan-ontology", "#index-ontology"].forEach((selector) => {
    const element = document.querySelector(selector);
    if (element) element.disabled = true;
  });
  const form = document.querySelector("#ontology-path-form");
  if (form) form.classList.toggle("hidden", true);
}

function renderOntologyProjectSummary(status) {
  const summary = document.querySelector("#ontology-project-summary");
  if (!summary) return;
  summary.innerHTML = "";
  const project = status.project;
  if (!project) {
    const card = document.createElement("div");
    card.className = "status-card warning";
    card.innerHTML = "<strong>Active project</strong><span>Select or create a project before working with ontology files.</span>";
    summary.append(card);
    return;
  }
  const rows = [
    ["Active project", project.name],
    ["Ontology ID", project.ontology_id || "Not configured"],
    ["Base IRI", project.base_iri || "Not configured"],
    ["Selected ontology source", status.selected_source || "No ontology file configured"],
    ["Selected ontology file", status.selected_file || "Not configured"],
    ["Editable ontology", `${project.editable_ontology_path || "Not configured"} (${statusLabel(status.path_statuses?.editable_ontology_path)})`],
    ["Built ontology", `${project.built_ontology_path || "Not configured"} (${statusLabel(status.path_statuses?.built_ontology_path)})`],
    ["ODK repository", `${project.odk_repo_path || "Not configured"} (${statusLabel(status.path_statuses?.odk_repo_path)})`],
  ];
  rows.forEach(([label, value]) => {
    const card = document.createElement("div");
    card.className = `status-card${status.selected_file ? "" : " warning"}`;
    card.innerHTML = `<strong>${escapeHtml(label)}</strong><span>${escapeHtml(value || "Not available")}</span>`;
    summary.append(card);
  });
}

function renderOntologyFiles(files, selectedFile) {
  state.ontologyFiles = files;
  const list = document.querySelector("#ontology-files");
  list.innerHTML = "";
  files.forEach((file) => {
    const row = document.createElement("div");
    row.className = "file-row";
    row.innerHTML = `<span><strong>${file.path === selectedFile ? "Selected project source: " : ""}${escapeHtml(file.name)}</strong></span>
      <p>${file.suffix} | ${file.kind} | ${file.size_bytes} bytes</p>
      <p>${escapeHtml(file.path)}</p>`;
    list.append(row);
  });
  if (!files.length) {
    list.innerHTML = '<p class="message">No project ontology files found.</p>';
  }
}

async function loadOntologyTerms() {
  const query = document.querySelector("#ontology-search").value || "";
  if (!state.activeProject) {
    state.ontologyTerms = [];
    return;
  }
  const params = new URLSearchParams();
  params.set("project_id", state.activeProject.slug || state.activeProject.project_id || state.activeProject.id);
  if (query) params.set("q", query);
  const terms = await api(query ? `/api/ontology/search?${params.toString()}` : `/api/ontology/terms?${params.toString()}`);
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
  await renderOntologyTree();
}

async function renderOntologyTree() {
  if (!state.activeProject) {
    const container = document.querySelector(currentPage() === "curation" ? "#curation-ontology-tree" : "#ontology-tree");
    if (container) container.innerHTML = '<p class="message">Select or create a project before working with ontology files.</p>';
    return;
  }
  const rootInput = document.querySelector("#ontology-tree-root");
  const depthInput = document.querySelector("#ontology-tree-depth");
  const showRelations = document.querySelector("#ontology-tree-relations")?.checked || false;
  const showRelationLabels = document.querySelector("#ontology-tree-relation-labels")?.checked !== false;
  const showNodeLabels = document.querySelector("#ontology-tree-node-labels")?.checked !== false;
  const params = new URLSearchParams();
  params.set("depth_limit", "12");
  params.set("project_id", state.activeProject.slug || state.activeProject.project_id || state.activeProject.id);
  const tree = await api(`/api/ontology/tree?${params.toString()}`);
  state.ontologyTree = tree;
  const inCuration = currentPage() === "curation";
  const container = document.querySelector(inCuration ? "#curation-ontology-tree" : "#ontology-tree");
  const details = document.querySelector(inCuration ? "#curation-ontology-details" : "#ontology-graph-details");
  if (!container) return;
  if (!tree.nodes?.length) {
    container.innerHTML = '<p class="message">No ontology hierarchy available.</p>';
    return;
  }
  container.innerHTML = "";
  refreshOntologyTreeSearchOptions();
  const visibleTree = deriveVisibleOntologyTree(tree, {
    depthLimit: Number(depthInput?.value || 2) || 2,
    rootQuery: rootInput?.value?.trim() || "",
    focusNodeId: state.ontologyFocusNodeId,
    selectedNodeId: state.selectedOntologyNodeId,
    collapsedNodes: state.collapsedOntologyNodes,
  });
  if (!visibleTree.roots.length) {
    container.innerHTML = '<p class="message">No matching ontology section available.</p>';
    return;
  }
  const layout = layoutOntologyTree(visibleTree.roots);
  if (state.ontologyCenterOnSelected && state.selectedOntologyNodeId && layout.byId.has(state.selectedOntologyNodeId)) {
    const selected = layout.byId.get(state.selectedOntologyNodeId);
    state.ontologyViewport.tx = layout.width / 2 - selected.x * state.ontologyViewport.scale;
    state.ontologyViewport.ty = layout.height / 2 - selected.y * state.ontologyViewport.scale;
    state.ontologyCenterOnSelected = false;
  }
  renderOntologyTreeSvg(container, details, tree, layout, {
    showRelations,
    showRelationLabels,
    showNodeLabels,
    visibleNodeIds: visibleTree.visibleNodeIds,
    selectedNodeId: state.selectedOntologyNodeId,
    focusNodeId: state.ontologyFocusNodeId,
    relatedNodeIds: selectedOntologyContextIds(tree, state.selectedOntologyNodeId),
  });
  renderOntologyTreeSummary(container, visibleTree);
  if (state.selectedOntologyNodeId) {
    const selected = ontologyIndexes(tree).byId.get(state.selectedOntologyNodeId);
    showOntologyNodeDetails(selected || { id: state.selectedOntologyNodeId }, tree, details);
  } else if (details) {
    details.innerHTML = '<p class="empty">Select an ontology node to inspect label, ID, definition, parents, subclasses, and relations.</p>';
  }
  const warnings = tree.metadata?.warnings || [];
  if (warnings.length) {
    const warning = document.createElement("p");
    warning.className = "message error";
    warning.textContent = `Tree warnings: ${warnings.join("; ")}`;
    container.append(warning);
  }
}

function ontologyIndexes(tree) {
  const nodes = tree.nodes || [];
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const childrenByParent = new Map();
  const parentsByChild = new Map();
  (tree.hierarchy_edges || []).forEach((edge) => {
    if (!byId.has(edge.source) || !byId.has(edge.target)) return;
    if (!childrenByParent.has(edge.source)) childrenByParent.set(edge.source, []);
    childrenByParent.get(edge.source).push(edge.target);
    if (!parentsByChild.has(edge.target)) parentsByChild.set(edge.target, []);
    parentsByChild.get(edge.target).push(edge.source);
  });
  childrenByParent.forEach((children) => children.sort((left, right) => safeText(byId.get(left)?.label || left).localeCompare(safeText(byId.get(right)?.label || right))));
  parentsByChild.forEach((parents) => parents.sort((left, right) => safeText(byId.get(left)?.label || left).localeCompare(safeText(byId.get(right)?.label || right))));
  const childIds = new Set([...(tree.hierarchy_edges || []).map((edge) => edge.target)]);
  const rootIds = (tree.root_ids || nodes.map((node) => node.id).filter((id) => !childIds.has(id))).filter((id) => byId.has(id));
  return { byId, childrenByParent, parentsByChild, rootIds };
}

function selectedOntologyContextIds(tree, nodeId) {
  const ids = new Set();
  if (!tree || !nodeId) return ids;
  const indexes = ontologyIndexes(tree);
  if (!indexes.byId.has(nodeId)) return ids;
  ids.add(nodeId);
  (indexes.parentsByChild.get(nodeId) || []).forEach((id) => ids.add(id));
  (indexes.childrenByParent.get(nodeId) || []).forEach((id) => ids.add(id));
  lateralRelationsFor(nodeId, tree).forEach((edge) => {
    if (edge.source) ids.add(edge.source);
    if (edge.target) ids.add(edge.target);
  });
  return ids;
}

function deriveVisibleOntologyTree(tree, options) {
  const indexes = ontologyIndexes(tree);
  const overviewRootLimit = 8;
  const visibleNodeIds = new Set();
  const warnings = [];

  function cloneSubtree(nodeId, depth, seen = new Set()) {
    if (!indexes.byId.has(nodeId) || seen.has(nodeId)) return null;
    const source = indexes.byId.get(nodeId);
    visibleNodeIds.add(nodeId);
    const childIds = indexes.childrenByParent.get(nodeId) || [];
    const collapsed = options.collapsedNodes.has(nodeId);
    const canShowChildren = !collapsed && depth < options.depthLimit;
    const children = canShowChildren
      ? childIds.map((childId) => cloneSubtree(childId, depth + 1, new Set([...seen, nodeId]))).filter(Boolean)
      : [];
    return {
      ...source,
      parents: source.parent_ids || source.parents || [],
      children_ids: childIds,
      child_count: childIds.length,
      hidden_child_count: canShowChildren ? Math.max(0, childIds.length - children.length) : childIds.length,
      collapsed,
      depth,
      children,
    };
  }

  function ancestorPath(nodeId) {
    const path = [];
    const seen = new Set();
    let current = nodeId;
    while (current && indexes.byId.has(current) && !seen.has(current)) {
      seen.add(current);
      path.unshift(current);
      current = (indexes.parentsByChild.get(current) || [])[0];
    }
    return path;
  }

  if (options.focusNodeId && indexes.byId.has(options.focusNodeId)) {
    const path = ancestorPath(options.focusNodeId);
    const focusedSubtree = cloneSubtree(options.focusNodeId, 0);
    let current = focusedSubtree;
    for (let index = path.length - 2; index >= 0; index -= 1) {
      const id = path[index];
      const source = indexes.byId.get(id);
      visibleNodeIds.add(id);
      current = {
        ...source,
        parents: source.parent_ids || source.parents || [],
        children_ids: indexes.childrenByParent.get(id) || [],
        child_count: (indexes.childrenByParent.get(id) || []).length,
        hidden_child_count: Math.max(0, (indexes.childrenByParent.get(id) || []).length - 1),
        collapsed: false,
        depth: index,
        children: [current],
      };
    }
    const semanticRoots = lateralRelationsFor(options.focusNodeId, tree)
      .map((edge) => (edge.source === options.focusNodeId ? edge.target : edge.source))
      .filter((id) => indexes.byId.has(id) && !visibleNodeIds.has(id))
      .map((id) => cloneSubtree(id, 0, new Set([options.focusNodeId])))
      .filter(Boolean)
      .map((node) => ({ ...node, semantic_context: true }));
    return { roots: current ? [current, ...semanticRoots] : semanticRoots, visibleNodeIds, mode: "focus", warnings };
  }

  let rootIds = indexes.rootIds;
  if (options.rootQuery) {
    const matched = searchOntologyNodes(tree, options.rootQuery)[0];
    rootIds = matched ? [matched.id] : rootIds.filter((id) => searchableOntologyNodeText(indexes.byId.get(id), tree).includes(normalizeText(options.rootQuery)));
  }
  if (!options.rootQuery && rootIds.length > overviewRootLimit) {
    warnings.push(`Showing ${overviewRootLimit} of ${rootIds.length} top-level classes. Search, jump, or focus to inspect a section.`);
    rootIds = rootIds.slice(0, overviewRootLimit);
  }
  return {
    roots: rootIds.map((id) => cloneSubtree(id, 0)).filter(Boolean),
    visibleNodeIds,
    mode: options.rootQuery ? "root" : "overview",
    warnings,
  };
}

function layoutOntologyTree(roots) {
  const nodeWidth = 230;
  const nodeHeight = 66;
  const levelGap = 112;
  const siblingGap = 276;
  const rootGap = 1;
  const margin = 52;
  const positionedNodes = [];
  const hierarchyLinks = [];
  let cursor = 0;
  let maxDepth = 0;

  function assign(node, depth, parent = null) {
    maxDepth = Math.max(maxDepth, depth);
    const children = node.children || [];
    if (children.length) {
      children.forEach((child) => assign(child, depth + 1, node));
      node.x = (children[0].x + children[children.length - 1].x) / 2;
    } else {
      node.x = cursor * siblingGap + nodeWidth / 2;
      cursor += 1;
    }
    node.y = depth * levelGap + nodeHeight / 2;
    positionedNodes.push(node);
    if (parent) {
      hierarchyLinks.push({ source: parent, target: node, relation: "is_a", edgeType: "hierarchy" });
    }
  }

  roots.forEach((root) => {
    assign(root, 0);
    cursor += rootGap;
  });

  const minX = Math.min(...positionedNodes.map((node) => node.x), nodeWidth / 2);
  positionedNodes.forEach((node) => {
    node.x = node.x - minX + margin + nodeWidth / 2;
    node.y += margin;
  });
  const byId = new Map(positionedNodes.map((node) => [node.id, node]));
  const width = Math.max(760, Math.max(...positionedNodes.map((node) => node.x), 0) + nodeWidth / 2 + margin);
  const height = Math.max(360, margin * 2 + nodeHeight + maxDepth * levelGap);
  return { nodes: positionedNodes, hierarchyLinks, byId, width, height, nodeWidth, nodeHeight };
}

function renderOntologyTreeSvg(container, details, tree, layout, options) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "ontology-tree-svg");
  svg.setAttribute("viewBox", `0 0 ${layout.width} ${layout.height}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Top-down ontology class hierarchy tree");

  const viewport = document.createElementNS("http://www.w3.org/2000/svg", "g");
  svg.append(viewport);
  applyOntologyViewportTransform(viewport);
  wireOntologyViewportControls(svg, viewport, layout);

  layout.hierarchyLinks.forEach((edge) => {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    const dimmed = options.selectedNodeId && !options.relatedNodeIds.has(edge.source.id) && !options.relatedNodeIds.has(edge.target.id);
    path.setAttribute("class", `tree-hierarchy-edge ${dimmed ? "is-dimmed" : ""}`);
    path.setAttribute("d", hierarchyPath(edge.source, edge.target, layout.nodeHeight));
    viewport.append(path);
  });

  if (options.showRelations) {
    (tree.relation_edges || []).forEach((edge) => {
      const source = layout.byId.get(edge.source);
      const target = layout.byId.get(edge.target);
      if (!source || !target) return;
      if (options.focusNodeId && edge.source !== options.focusNodeId && edge.target !== options.focusNodeId) return;
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      const dimmed = options.selectedNodeId && edge.source !== options.selectedNodeId && edge.target !== options.selectedNodeId;
      path.setAttribute("class", `tree-semantic-edge ${dimmed ? "is-dimmed" : ""}`);
      path.setAttribute("d", semanticPath(source, target, layout.nodeWidth));
      path.addEventListener("click", (event) => {
        event.stopPropagation();
        showOntologyEdgeDetails(edge, details);
      });
      viewport.append(path);
      if (options.showRelationLabels) {
        const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
        label.setAttribute("class", "tree-semantic-label");
        label.setAttribute("x", (source.x + target.x) / 2);
        label.setAttribute("y", (source.y + target.y) / 2 - 8);
        label.textContent = edge.relation || edge.relation_label || edge.relation_type || "related";
        viewport.append(label);
      }
    });
  }

  graphReviewProposedRelations().forEach((edge) => {
    const source = layout.byId.get(edge.source);
    const target = layout.byId.get(edge.target);
    if (!source || !target) return;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("class", "tree-proposed-edge");
    path.setAttribute("d", semanticPath(source, target, layout.nodeWidth));
    viewport.append(path);
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("class", "tree-proposed-label");
    label.setAttribute("x", (source.x + target.x) / 2);
    label.setAttribute("y", (source.y + target.y) / 2 + 14);
    label.textContent = `proposed: ${edge.relation || "relation"}`;
    viewport.append(label);
  });

  layout.nodes.forEach((node) => {
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    const selected = node.id === options.selectedNodeId;
    const focused = node.id === options.focusNodeId;
    const dimmed = options.selectedNodeId && !selected && !options.relatedNodeIds.has(node.id);
    group.setAttribute("class", `ontology-tree-node ${selected ? "is-selected" : ""} ${focused ? "is-focused" : ""} ${dimmed ? "is-dimmed" : ""} ${node.semantic_context ? "is-semantic-context" : ""}`);
    group.setAttribute("transform", `translate(${node.x} ${node.y})`);
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = `${node.label || node.id} (${node.id})`;
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("class", "tree-node-box");
    rect.setAttribute("x", -layout.nodeWidth / 2);
    rect.setAttribute("y", -layout.nodeHeight / 2);
    rect.setAttribute("width", layout.nodeWidth);
    rect.setAttribute("height", layout.nodeHeight);
    group.append(title, rect);

    if (node.child_count > 0) {
      const toggle = document.createElementNS("http://www.w3.org/2000/svg", "text");
      toggle.setAttribute("class", "tree-node-toggle");
      toggle.setAttribute("x", -layout.nodeWidth / 2 + 14);
      toggle.setAttribute("y", 5);
      toggle.textContent = node.collapsed ? "+" : "-";
      toggle.addEventListener("click", (event) => {
        event.stopPropagation();
        if (state.collapsedOntologyNodes.has(node.id)) {
          state.collapsedOntologyNodes.delete(node.id);
        } else {
          state.collapsedOntologyNodes.add(node.id);
        }
        renderOntologyTree().catch((error) => setError("#ontology-message", error.message));
      });
      group.append(toggle);
    }

    if (options.showNodeLabels) {
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("class", "tree-node-label");
      label.setAttribute("x", -layout.nodeWidth / 2 + 32);
      label.setAttribute("y", -5);
      label.textContent = truncateLabel(node.label || node.id, 28);
      const idText = document.createElementNS("http://www.w3.org/2000/svg", "text");
      idText.setAttribute("class", "tree-node-id");
      idText.setAttribute("x", -layout.nodeWidth / 2 + 32);
      idText.setAttribute("y", 17);
      idText.textContent = truncateLabel(node.id, 30);
      group.append(label, idText);
    }

    if (node.hidden_child_count) {
      const badge = document.createElementNS("http://www.w3.org/2000/svg", "text");
      badge.setAttribute("class", "tree-node-badge");
      badge.setAttribute("x", layout.nodeWidth / 2 - 12);
      badge.setAttribute("y", 20);
      badge.textContent = `+${node.hidden_child_count}`;
      group.append(badge);
    }

    group.addEventListener("click", (event) => {
      event.stopPropagation();
      state.selectedOntologyNodeId = node.id;
      showOntologyNodeDetails(node, tree, details);
      updateGraphCurationStatus();
      renderOntologyTree().catch((error) => setError("#ontology-message", error.message));
    });
    viewport.append(group);
  });

  container.append(svg);
}

function renderOntologyTreeSummary(container, visibleTree) {
  const summary = document.createElement("p");
  summary.className = "message tree-summary";
  const visibleCount = visibleTree.visibleNodeIds.size;
  const mode = visibleTree.mode === "focus" ? "Focused section" : visibleTree.mode === "root" ? "Selected section" : "Top-level overview";
  const tree = state.ontologyTree || {};
  const sourceFiles = tree.metadata?.source_files || [];
  const sourceText = sourceFiles.length ? sourceFiles.slice(0, 2).join("; ") : "source not available";
  const selected = selectedOntologyNodePayload();
  const selectedText = selected ? `${selected.label || selected.id} (${selected.id})` : "none";
  summary.textContent = `${mode}: ${visibleCount} visible of ${tree.term_count || tree.nodes?.length || 0} classes. Source: ${sourceText}. Selected: ${selectedText}. ${visibleTree.warnings.join(" ")}`;
  container.append(summary);
}

function applyOntologyViewportTransform(viewport) {
  viewport.setAttribute(
    "transform",
    `translate(${state.ontologyViewport.tx} ${state.ontologyViewport.ty}) scale(${state.ontologyViewport.scale})`
  );
}

function wireOntologyViewportControls(svg, viewport) {
  let dragging = false;
  let last = null;
  svg.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoomOntologyTree(event.deltaY > 0 ? 0.9 : 1.1, viewport);
  });
  svg.addEventListener("pointerdown", (event) => {
    dragging = true;
    last = { x: event.clientX, y: event.clientY };
    svg.setPointerCapture?.(event.pointerId);
  });
  svg.addEventListener("pointermove", (event) => {
    if (!dragging || !last) return;
    state.ontologyViewport.tx += event.clientX - last.x;
    state.ontologyViewport.ty += event.clientY - last.y;
    last = { x: event.clientX, y: event.clientY };
    applyOntologyViewportTransform(viewport);
  });
  svg.addEventListener("pointerup", (event) => {
    dragging = false;
    last = null;
    svg.releasePointerCapture?.(event.pointerId);
  });
}

function zoomOntologyTree(factor, viewport = null) {
  state.ontologyViewport.scale = Math.max(0.35, Math.min(3.2, state.ontologyViewport.scale * factor));
  if (viewport) applyOntologyViewportTransform(viewport);
  else renderOntologyTree().catch((error) => setError("#ontology-message", error.message));
}

function fitOntologyTree() {
  state.ontologyViewport = { scale: 1, tx: 0, ty: 0 };
  renderOntologyTree().catch((error) => setError("#ontology-message", error.message));
}

function centerSelectedOntologyNode() {
  if (!state.ontologyTree || !state.selectedOntologyNodeId) return;
  state.ontologyViewport = { scale: 1.15, tx: 0, ty: 0 };
  state.ontologyCenterOnSelected = true;
  renderOntologyTree().catch((error) => setError("#ontology-message", error.message));
}

function hierarchyPath(source, target, nodeHeight) {
  const startY = source.y + nodeHeight / 2;
  const endY = target.y - nodeHeight / 2;
  const midY = (startY + endY) / 2;
  return `M ${source.x} ${startY} V ${midY} H ${target.x} V ${endY}`;
}

function semanticPath(source, target, nodeWidth) {
  const direction = source.x <= target.x ? 1 : -1;
  const startX = source.x + direction * (nodeWidth / 2);
  const targetX = target.x - direction * (nodeWidth / 2);
  const curve = Math.max(72, Math.abs(target.x - source.x) * 0.35);
  return `M ${startX} ${source.y} C ${startX + direction * curve} ${source.y}, ${targetX - direction * curve} ${target.y}, ${targetX} ${target.y}`;
}

function truncateLabel(value, maxLength) {
  const text = safeText(value);
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}...` : text;
}

function showOntologyNodeDetails(node, tree, details) {
  if (!details) return;
  const sourceNode = ontologyIndexes(tree).byId.get(node.id) || node;
  const indexes = ontologyIndexes(tree);
  const unavailable = "not available";
  const parentIds = sourceNode.parent_ids || sourceNode.parents || indexes.parentsByChild.get(sourceNode.id) || [];
  const childIds = sourceNode.child_ids || sourceNode.children_ids || indexes.childrenByParent.get(sourceNode.id) || [];
  const semanticRelations = lateralRelationsFor(sourceNode.id, tree).map((edge) => {
    const relation = edge.relation_label || edge.relation || edge.relation_type || "related to";
    const otherId = edge.source === sourceNode.id ? edge.target : edge.source;
    const other = indexes.byId.get(otherId);
    const direction = edge.source === sourceNode.id ? relation : `inverse ${relation}`;
    return `${direction} ${other?.label || otherId}`;
  });
  const row = (label, value) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value || unavailable)}</dd>`;
  details.innerHTML = `
    <div class="node-detail-card">
      <h3>Selected Ontology Node</h3>
      <p class="node-detail-title">${escapeHtml(sourceNode.label || sourceNode.id || unavailable)}</p>
      <p class="node-detail-id">${escapeHtml(sourceNode.id || sourceNode.iri || unavailable)}</p>
      <dl>
        ${row("Definition", sourceNode.definition)}
        ${row("Synonyms", (sourceNode.synonyms || []).join("; "))}
        ${row("Parent / superclass", parentIds.join("; "))}
        ${row("Direct subclasses", childIds.join("; "))}
        ${row("Semantic relations", semanticRelations.join("; "))}
        ${row("Source path", sourceNode.source_file || sourceNode.source_ontology)}
        ${row("Status", sourceNode.status || sourceNode.review_state)}
      </dl>
    </div>
  `;
}

function showOntologyEdgeDetails(edge, details) {
  if (!details) return;
  details.textContent = [
    `Relation: ${edge.relation || edge.relation_label || edge.relation_type || "related"}`,
    `Type: ${edge.edgeType || "semantic"}`,
    `Source: ${edge.source}`,
    `Target: ${edge.target}`,
  ].join("\n");
}

function lateralRelationsFor(nodeId, tree) {
  return (tree.relation_edges || []).filter((edge) => edge.source === nodeId || edge.target === nodeId);
}

function graphReviewProposedRelations() {
  const node = activeCandidateNode();
  if (!node) return [];
  return graphReviewFromNode(node).proposed_relations || [];
}

function searchableOntologyNodeText(node, tree) {
  if (!node) return "";
  const relationText = (tree.relation_edges || [])
    .filter((edge) => edge.source === node.id || edge.target === node.id)
    .map((edge) => [edge.source, edge.target, edge.relation, edge.relation_label, edge.relation_type].filter(Boolean).join(" "))
    .join(" ");
  return normalizeText([node.id, node.label, node.definition, ...(node.synonyms || []), relationText].filter(Boolean).join(" "));
}

function searchOntologyNodes(tree, query) {
  const normalized = normalizeText(query);
  if (!normalized) return [];
  return (tree.nodes || [])
    .filter((node) => searchableOntologyNodeText(node, tree).includes(normalized))
    .slice(0, 30);
}

function refreshOntologyTreeSearchOptions() {
  const datalist = document.querySelector("#ontology-tree-search-results");
  const input = document.querySelector("#ontology-tree-search");
  if (!datalist || !input || !state.ontologyTree) return;
  const results = searchOntologyNodes(state.ontologyTree, input.value).slice(0, 12);
  datalist.innerHTML = "";
  results.forEach((node) => {
    const option = document.createElement("option");
    option.value = `${node.label || node.id} (${node.id})`;
    datalist.append(option);
  });
}

function selectedSearchNode() {
  const input = document.querySelector("#ontology-tree-search");
  if (!input || !state.ontologyTree) return null;
  const query = input.value.trim();
  const idMatch = query.match(/\(([^()]+)\)$/);
  if (idMatch) {
    return ontologyIndexes(state.ontologyTree).byId.get(idMatch[1]) || null;
  }
  return searchOntologyNodes(state.ontologyTree, query)[0] || null;
}

function jumpToOntologySearch({ focus = true } = {}) {
  const node = selectedSearchNode();
  if (!node) {
    setError("#ontology-message", "No matching ontology class found.");
    return;
  }
  state.selectedOntologyNodeId = node.id;
  if (focus) state.ontologyFocusNodeId = node.id;
  state.collapsedOntologyNodes.delete(node.id);
  state.ontologyViewport = { scale: 1, tx: 0, ty: 0 };
  showOntologyNodeDetails(node, state.ontologyTree, document.querySelector("#ontology-graph-details"));
  renderOntologyTree().catch((error) => setError("#ontology-message", error.message));
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

document.querySelector("#refresh-ontology-tree")?.addEventListener("click", (event) => {
  state.collapsedOntologyNodes.clear();
  state.ontologyViewport = { scale: 1, tx: 0, ty: 0 };
  withButtonFeedback(event.currentTarget, "Refreshing", renderOntologyTree)
    .catch((error) => setError("#ontology-message", error.message));
});

document.querySelector("#ontology-tree-search")?.addEventListener("input", refreshOntologyTreeSearchOptions);

document.querySelector("#ontology-tree-search")?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    jumpToOntologySearch({ focus: true });
  }
});

document.querySelector("#ontology-tree-root")?.addEventListener("change", () => {
  state.ontologyFocusNodeId = null;
  state.ontologyViewport = { scale: 1, tx: 0, ty: 0 };
  renderOntologyTree().catch((error) => setError("#ontology-message", error.message));
});

document.querySelector("#ontology-tree-root")?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    state.ontologyFocusNodeId = null;
    state.ontologyViewport = { scale: 1, tx: 0, ty: 0 };
    renderOntologyTree().catch((error) => setError("#ontology-message", error.message));
  }
});

document.querySelector("#ontology-tree-jump")?.addEventListener("click", () => {
  jumpToOntologySearch({ focus: true });
});

document.querySelector("#ontology-tree-focus")?.addEventListener("click", () => {
  if (!state.selectedOntologyNodeId) {
    setError("#ontology-message", "Select an ontology class before focusing.");
    return;
  }
  state.ontologyFocusNodeId = state.selectedOntologyNodeId;
  state.ontologyViewport = { scale: 1, tx: 0, ty: 0 };
  const relationsToggle = document.querySelector("#ontology-tree-relations");
  if (relationsToggle) relationsToggle.checked = true;
  renderOntologyTree().catch((error) => setError("#ontology-message", error.message));
});

document.querySelector("#ontology-tree-reset")?.addEventListener("click", () => {
  state.ontologyFocusNodeId = null;
  state.selectedOntologyNodeId = null;
  state.collapsedOntologyNodes.clear();
  state.ontologyViewport = { scale: 1, tx: 0, ty: 0 };
  const rootInput = document.querySelector("#ontology-tree-root");
  const searchInput = document.querySelector("#ontology-tree-search");
  if (rootInput) rootInput.value = "";
  if (searchInput) searchInput.value = "";
  renderOntologyTree().catch((error) => setError("#ontology-message", error.message));
});

document.querySelector("#ontology-tree-zoom-in")?.addEventListener("click", () => zoomOntologyTree(1.18));
document.querySelector("#ontology-tree-zoom-out")?.addEventListener("click", () => zoomOntologyTree(0.84));
document.querySelector("#ontology-tree-fit")?.addEventListener("click", fitOntologyTree);
document.querySelector("#ontology-tree-center")?.addEventListener("click", centerSelectedOntologyNode);
document.querySelector("#graph-set-parent")?.addEventListener("click", setSelectedNodeAsParent);
document.querySelector("#graph-set-source")?.addEventListener("click", () => setSelectedNodeAsRelationRole("source"));
document.querySelector("#graph-set-target")?.addEventListener("click", () => setSelectedNodeAsRelationRole("target"));
document.querySelector("#graph-compare")?.addEventListener("click", compareCandidateWithSelectedNode);
document.querySelector("#graph-duplicate")?.addEventListener("click", markCandidateDuplicateOfSelectedNode);
document.querySelector("#graph-open-details")?.addEventListener("click", () => {
  const selected = selectedOntologyNodePayload();
  if (selected && state.ontologyTree) {
    showOntologyNodeDetails(selected, state.ontologyTree, document.querySelector("#curation-ontology-details"));
  }
});
document.querySelector("#graph-add-relation")?.addEventListener("click", addGraphRelationProposal);
document.querySelector("#graph-relation-target-search")?.addEventListener("change", (event) => {
  if (!state.ontologyTree) return;
  const match = searchOntologyNodes(state.ontologyTree, event.currentTarget.value)[0];
  const node = activeCandidateNode();
  if (match && node) {
    node.querySelector(".relation-target").value = match.id;
    state.selectedOntologyNodeId = match.id;
    state.ontologyFocusNodeId = match.id;
    renderOntologyTree().catch((error) => setError("#ols-message", error.message));
  }
});

[
  "#ontology-tree-relations",
  "#ontology-tree-relation-labels",
  "#ontology-tree-node-labels",
  "#ontology-tree-depth",
].forEach((selector) => {
  document.querySelector(selector)?.addEventListener("change", () => {
    state.ontologyViewport = { scale: 1, tx: 0, ty: 0 };
    renderOntologyTree().catch((error) => setError("#ontology-message", error.message));
  });
});

document.querySelector("#zotero-filter")?.addEventListener("input", renderEntries);
document.querySelector("#literature-review-filter")?.addEventListener("change", renderEntries);
document.querySelectorAll("[data-literature-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    setLiteratureTab(button.dataset.literatureTab);
    renderTwoStageLiterature();
  });
});
["#curated-literature-search", "#uncurated-literature-search"].forEach((selector) => {
  document.querySelector(selector)?.addEventListener("input", renderTwoStageLiterature);
});
["#curated-literature-status-filter", "#uncurated-literature-status-filter"].forEach((selector) => {
  document.querySelector(selector)?.addEventListener("change", renderTwoStageLiterature);
});

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
        `Curation complete. Suggestions: ${result.suggestion_count}; warnings: ${result.warning_count}; chunks: ${result.chunk_count}; approx. input: ${result.input_chars || 0} chars / ${result.input_approx_tokens || 0} tokens.`
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

document.querySelector("#build-literature-context")?.addEventListener("click", async (event) => {
  try {
    await withButtonFeedback(event.currentTarget, "Building", async () => {
      const result = await api("/api/literature/build-combined", { method: "POST", body: "{}" });
      setSuccess(
        "#literature-repository-message",
        `Built ${result.count} canonical paper(s): ${result.combined_output_file}`
      );
    });
  } catch (error) {
    setError("#literature-repository-message", error.message);
  }
});

document.querySelector("#scan-literature-duplicates")?.addEventListener("click", async (event) => {
  try {
    await withButtonFeedback(event.currentTarget, "Scanning", async () => {
      const result = await api("/api/literature/deduplicate", { method: "POST", body: JSON.stringify({ apply: false }) });
      setSuccess("#literature-repository-message", `Duplicate scan complete: ${result.suspected_duplicates} suspected duplicate(s).`);
    });
  } catch (error) {
    setError("#literature-repository-message", error.message);
  }
});

document.querySelector("#apply-literature-deduplication")?.addEventListener("click", async (event) => {
  if (!window.confirm("Merge duplicate literature entries after creating a full backup?")) return;
  try {
    await withButtonFeedback(event.currentTarget, "Deduplicating", async () => {
      const result = await api("/api/literature/deduplicate", { method: "POST", body: JSON.stringify({ apply: true, confirm: true }) });
      setSuccess("#literature-repository-message", `Deduplication complete. Backup: ${result.backup || "not needed"}`);
      await loadEntries();
    });
  } catch (error) {
    setError("#literature-repository-message", error.message);
  }
});

document.querySelector("#reset-literature-repository")?.addEventListener("click", async (event) => {
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

document.querySelector("#project-create-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const payload = formPayload(event.currentTarget);
  const body = {
    name: payload.name,
    ontology_id: payload.ontology_id,
    ontology_title: payload.ontology_title || null,
    project_type: payload.project_type || "domain_ontology",
    parent_project_id: payload.parent_project_id || null,
    ontology_namespace: payload.ontology_namespace || null,
    ontology_scope: parseListField(payload.minimal_scope_notes || ""),
    minimal_scope_notes: payload.minimal_scope_notes || null,
    base_iri: payload.base_iri || null,
    github_url: payload.github_url || null,
    local_git_repository_path: payload.local_git_repository_path || null,
    odk_repo_path: payload.odk_repo_path || null,
    editable_ontology_path: payload.editable_ontology_path || null,
    built_ontology_path: payload.built_ontology_path || null,
    literature_repository_path: payload.literature_repository_path || null,
    description: payload.description || null,
  };
  try {
    await withButtonFeedback(button, payload.project_ref ? "Saving project" : "Creating project", async () => {
      const project = await api(
        payload.project_ref ? `/api/projects/${encodeURIComponent(payload.project_ref)}` : "/api/projects",
        {
          method: payload.project_ref ? "PATCH" : "POST",
          body: JSON.stringify({
            ...body,
            local_workspace_path: payload.local_workspace_path || null,
            zotero_literature_source_path: payload.zotero_literature_source_path || null,
            activate: true,
          }),
        }
      );
      state.selectedProjectRef = project.slug;
      resetProjectForm();
      await loadProjects();
      renderProjectDetail(project);
      setSuccess(
        "#project-message",
        payload.project_ref
          ? `Saved project metadata for ${project.name}. Changes are visible in the project detail panel.`
          : `Created and selected ${project.name}. Review the next-step guide below before moving to literature or ontology.`
      );
    });
  } catch (error) {
    const message = error.message || "Could not save project.";
    if (/base iri|ontology id|project type|parent/i.test(message)) {
      setProjectWizardStep(0);
    }
    updateProjectWizardReview();
    setProjectError(payload.project_ref ? "Project update" : "Project creation", error, "Correct the highlighted project metadata, then save again. Your form values are still present.");
  }
});

document.querySelector("#project-cancel-edit")?.addEventListener("click", () => {
  resetProjectForm();
  setMessage("#project-message", "Project edit cancelled.");
});

document.querySelector("#project-ai-suggest")?.addEventListener("click", async (event) => {
  const idea = document.querySelector("#project-ai-idea")?.value || "";
  if (!idea.trim()) {
    setError("#project-message", "Enter a short project idea first.");
    return;
  }
  await withButtonFeedback(event.currentTarget, "Suggesting metadata", async () => {
    const result = await api("/api/projects/suggest-metadata", {
      method: "POST",
      body: JSON.stringify({ idea }),
    });
    const suggestion = result.suggestion || {};
    const form = document.querySelector("#project-create-form");
    if (!form) return;
    const proposed = [];
    const fillIfEmpty = (fieldName, value, label) => {
      const field = form[fieldName];
      const text = String(value || "").trim();
      if (!field || !text) return;
      if (!field.value.trim()) {
        field.value = text;
      } else if (field.value.trim() !== text) {
        proposed.push(`${label}: ${text}`);
      }
    };
    fillIfEmpty("name", suggestion.project_name, "Project name");
    fillIfEmpty("ontology_id", suggestion.ontology_id, "Ontology ID");
    fillIfEmpty("ontology_title", suggestion.project_name, "Ontology title");
    fillIfEmpty("description", suggestion.short_description, "Short description");
    fillIfEmpty("minimal_scope_notes", suggestion.minimal_scope_notes, "Minimal scope notes");
    fillIfEmpty("base_iri", suggestion.base_iri, "Base IRI");
    if (suggestion.project_type && [...form.project_type.options].some((option) => option.value === suggestion.project_type)) {
      if (!form.project_type.value) {
        form.project_type.value = suggestion.project_type;
      } else if (form.project_type.value !== suggestion.project_type) {
        proposed.push(`Project type: ${suggestion.project_type}`);
      }
    }
    if (!form.ontology_namespace.value && form.ontology_id.value) {
      form.ontology_namespace.value = form.ontology_id.value.toLowerCase();
    }
    updateProjectWizardReview();
    const suffix = proposed.length ? ` Suggestions for filled fields: ${proposed.join(" | ")}` : "";
    setSuccess("#project-message", `AI metadata draft received. Empty fields were filled; review before saving.${suffix}`);
  }).catch((error) => setProjectError("AI project metadata suggestion", error, "Check LLM settings or continue filling the project form manually."));
});

document.querySelectorAll("[data-project-step]").forEach((button) => {
  button.addEventListener("click", () => setProjectWizardStep(Number(button.dataset.projectStep)));
});

document.querySelector("#project-wizard-prev")?.addEventListener("click", () => {
  setProjectWizardStep(state.projectWizardStep - 1);
});

document.querySelector("#project-wizard-next")?.addEventListener("click", () => {
  setProjectWizardStep(state.projectWizardStep + 1);
});

document.querySelector("#project-create-form")?.addEventListener("input", (event) => {
  const form = event.currentTarget;
  if (event.target.name === "base_iri") {
    state.projectBaseIriEdited = true;
  }
  if (event.target.name === "ontology_id") {
    if (!state.projectBaseIriEdited) {
      form.base_iri.value = suggestedBaseIriFor(form.ontology_id.value);
    }
    if (!form.ontology_namespace.value) {
      form.ontology_namespace.value = form.ontology_id.value.toLowerCase();
    }
  }
  updateProjectWizardReview();
});

document.querySelector("#curation-run-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const payload = formPayload(event.currentTarget);
  await withButtonFeedback(button, "Creating run", async () => {
    const result = await api("/api/curation/runs", {
      method: "POST",
      body: JSON.stringify({
        name: payload.name || null,
        strategy: payload.strategy,
        model: payload.model || null,
        prompt_text: payload.prompt_text || null,
        raw_output: payload.raw_output || null,
      }),
    });
    await Promise.all([loadCurationRuns(), loadSuggestions()]);
    setSuccess(
      "#suggestions-message",
      `Run ${result.id} created. Parsed ${result.parsed_suggestions || 0} suggestion(s).${result.warning ? ` ${result.warning}` : ""}`
    );
  });
});

document.querySelector("#load-suggestions")?.addEventListener("click", async (event) => {
  await withButtonFeedback(event.currentTarget, "Refreshing", async () => {
    await Promise.all([loadCurationRuns(), loadSuggestions()]);
    setSuccess("#suggestions-message", "Suggestions refreshed.");
  });
});

document.querySelector("#compute-evaluation")?.addEventListener("click", async (event) => {
  await withButtonFeedback(event.currentTarget, "Computing", async () => {
    const result = await api("/api/evaluation/compute", { method: "POST", body: "{}" });
    document.querySelector("#evaluation-output").textContent = JSON.stringify(result.metrics, null, 2);
    setSuccess("#evaluation-message", "Evaluation metrics computed.");
  });
});

document.querySelector("#compare-runs-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const payload = formPayload(event.currentTarget);
  await withButtonFeedback(button, "Comparing", async () => {
    const result = await api("/api/evaluation/compare", {
      method: "POST",
      body: JSON.stringify({
        first_run_id: Number(payload.first_run_id),
        second_run_id: Number(payload.second_run_id),
      }),
    });
    document.querySelector("#evaluation-output").textContent = JSON.stringify(result, null, 2);
    setSuccess("#evaluation-message", "Run comparison complete.");
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

onDomReady(() => {
  bindZoteroMetadataSync();
  applyTheme();
  showCurrentPage();
  initializeWorkspace();
});
