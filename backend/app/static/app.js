/* SIGED — interface web (JavaScript natif, sans dépendance). Consomme l'API REST. */
"use strict";

const S = { token: sessionStorage.getItem("siged_token"), perms: [], role: "", name: "", plan: [] };
const $ = (sel, el = document) => el.querySelector(sel);
const STATUS = { DRAFT: "Brouillon", PENDING_VALIDATION: "En validation", VALIDATED: "Validé",
                 ARCHIVED: "Archivé (définitif)", DESTROYED: "Éliminé" };
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeSnippet = (s) => esc(s).replaceAll("&lt;mark&gt;", "<mark>").replaceAll("&lt;/mark&gt;", "</mark>");
const badge = (s) => `<span class="badge ${esc(s)}">${esc(STATUS[s] || s)}</span>`;
const fmtDate = (d) => (d ? new Date(d).toLocaleDateString("fr-FR") : "—");
const fmtDT = (d) => (d ? new Date(d).toLocaleString("fr-FR") : "—");
const fmtSize = (b) => (b > 1048576 ? (b / 1048576).toFixed(1) + " Mo" : Math.max(1, Math.round(b / 1024)) + " Ko");
const can = (p) => S.perms.includes(p);

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (err ? " err" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.className = "toast"), 3500);
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (S.token) headers.Authorization = "Bearer " + S.token;
  if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); }
  const r = await fetch(path, { ...opts, headers });
  if (r.status === 401 && path !== "/api/auth/login") { logout(); throw new Error("Session expirée"); }
  if (opts.raw) { if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText); return r; }
  const data = r.status === 204 ? null : await r.json().catch(() => null);
  if (!r.ok) {
    const d = data?.detail;
    throw new Error(Array.isArray(d) ? d.map((e) => e.msg || e).join(" ; ") : d || r.statusText);
  }
  return data;
}

/* ------------------------------------------------------------------ Session */
async function boot() {
  if (!S.token) return showLogin();
  try {
    const me = await api("/api/auth/me");
    Object.assign(S, { perms: me.permissions, role: me.role, name: me.name });
    S.plan = await api("/api/classification/flat");
    $("#login-view").classList.add("hidden");
    $("#app").classList.remove("hidden");
    $("#who").textContent = `${me.name} · ${me.role}`;
    document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("hidden", !!a.dataset.perm && !can(a.dataset.perm)));
    go(location.hash.slice(1) || "dashboard");
  } catch { showLogin(); }
}
function showLogin() { $("#app").classList.add("hidden"); $("#login-view").classList.remove("hidden"); }
function logout() { S.token = null; sessionStorage.removeItem("siged_token"); showLogin(); }

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  try {
    const t = await api("/api/auth/login", { method: "POST", body: new URLSearchParams(new FormData(e.target)) });
    S.token = t.access_token;
    sessionStorage.setItem("siged_token", S.token);
    boot();
  } catch (err) { $("#login-error").textContent = err.message; }
});
$("#logout").onclick = logout;
$("#nav").addEventListener("click", (e) => { if (e.target.dataset.view) go(e.target.dataset.view); });

const VIEWS = {};
function go(view) {
  if (!VIEWS[view]) view = "dashboard";
  location.hash = view;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  $("#main").innerHTML = '<p class="muted">Chargement…</p>';
  VIEWS[view]().catch((e) => ($("#main").innerHTML = `<p class="error">${esc(e.message)}</p>`));
}

/* ------------------------------------------------------------------ Tableau de bord */
VIEWS.dashboard = async () => {
  const s = await api("/api/admin/stats");
  const st = s.documents_by_status;
  const recent = await api("/api/search?sort=created_desc&size=8");
  $("#main").innerHTML = `
    <h1>Tableau de bord</h1>
    <div class="grid g4">
      <div class="kpi"><b>${(st.DRAFT || 0) + (st.PENDING_VALIDATION || 0) + (st.VALIDATED || 0)}</b><span>documents actifs</span></div>
      <div class="kpi"><b>${st.PENDING_VALIDATION || 0}</b><span>en attente de validation</span></div>
      <div class="kpi"><b>${s.versions}</b><span>versions · ${fmtSize(s.bytes)}</span></div>
      <div class="kpi"><b>${s.retention_due}</b><span>DUA échues à traiter</span></div>
    </div>
    <div class="card" style="margin-top:16px"><h2>Derniers dépôts</h2>${docTable(recent.items)}</div>`;
  bindRows();
};

function docTable(items, withSnippet = false) {
  if (!items.length) return '<p class="muted">Aucun document.</p>';
  return `<table><thead><tr><th>Cote</th><th>Titre</th><th>Type</th><th>Date</th><th>Rubrique</th><th>Statut</th></tr></thead><tbody>
    ${items.map((d) => `<tr class="click" data-id="${esc(d.id)}">
      <td class="ref">${esc(d.reference)}</td>
      <td><strong>${esc(d.title)}</strong><div class="muted">${esc(d.author)}</div>
        ${withSnippet && d.snippet ? `<div class="snippet">${safeSnippet(d.snippet)}</div>` : ""}</td>
      <td>${esc(d.doc_type)}</td><td>${fmtDate(d.document_date)}</td>
      <td>${d.classification ? `<span class="ref">${esc(d.classification.code)}</span>` : '<span class="muted">—</span>'}</td>
      <td>${badge(d.status)}${d.legal_hold ? ' <span class="badge">Gel</span>' : ""}</td></tr>`).join("")}
  </tbody></table>`;
}
function bindRows(root = document) { root.querySelectorAll("tr[data-id]").forEach((tr) => (tr.onclick = () => openDoc(tr.dataset.id))); }
const planOptions = (sel = "") => `<option value="">— Automatique —</option>` +
  S.plan.map((n) => `<option value="${n.id}" ${String(sel) === String(n.id) ? "selected" : ""}>${esc(n.code)} · ${esc(n.label)}</option>`).join("");

/* ------------------------------------------------------------------ Recherche */
VIEWS.search = async () => {
  $("#main").innerHTML = `
    <h1>Rechercher</h1>
    <form id="sf" class="card grid">
      <div class="row"><input name="q" placeholder="Recherche plein texte (contenu OCR, titre…)" style="flex:1">
        <button class="btn primary">Rechercher</button></div>
      <div class="grid g4">
        <label>Titre<input name="title"></label><label>Auteur<input name="author"></label>
        <label>Type<input name="doc_type" placeholder="facture, pv…"></label><label>Mot-clé<input name="keyword"></label>
        <label>Du<input type="date" name="date_from"></label><label>Au<input type="date" name="date_to"></label>
        <label>Statut<select name="status"><option value="">Tous (hors éliminés)</option>
          ${Object.entries(STATUS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
        <label>Rubrique<select name="classification_id">${planOptions().replace("— Automatique —", "Toutes")}</select></label>
        <label>Métadonnée (clé)<input name="meta_key" placeholder="matricule"></label><label>Valeur<input name="meta_value"></label>
        <label>Tri<select name="sort"><option value="relevance">Pertinence</option><option value="date_desc">Date ↓</option>
          <option value="date_asc">Date ↑</option><option value="title">Titre</option></select></label>
      </div>
    </form>
    <div id="results" class="card"></div>`;
  const run = async (page = 1) => {
    const p = new URLSearchParams([...new FormData($("#sf"))].filter(([, v]) => v));
    p.set("page", page);
    const r = await api("/api/search?" + p);
    const pages = Math.ceil(r.total / r.size);
    $("#results").innerHTML = `<div class="row"><strong>${r.total} résultat(s)</strong><span class="muted">en ${r.took_ms} ms</span>
      <span class="spacer"></span>${page > 1 ? `<button class="btn sm" data-p="${page - 1}">‹ Préc.</button>` : ""}
      <span class="muted">${page}/${pages || 1}</span>${page < pages ? `<button class="btn sm" data-p="${page + 1}">Suiv. ›</button>` : ""}</div>
      ${docTable(r.items, true)}`;
    $("#results").querySelectorAll("[data-p]").forEach((b) => (b.onclick = () => run(+b.dataset.p)));
    bindRows($("#results"));
  };
  $("#sf").onsubmit = (e) => { e.preventDefault(); run(); };
  run();
};

/* ------------------------------------------------------------------ Dépôt */
VIEWS.upload = async () => {
  const today = new Date().toISOString().slice(0, 10);
  $("#main").innerHTML = `
    <h1>Déposer des documents</h1>
    <form id="uf" class="card grid">
      <h2>Fiche de métadonnées</h2>
      <div class="grid g2">
        <label>Titre *<input name="title" required></label><label>Auteur *<input name="author" required></label>
        <label>Date du document *<input type="date" name="document_date" value="${today}" required></label>
        <label>Type de document *<input name="doc_type" required placeholder="facture, contrat, pv, courrier…"></label>
        <label>Mots-clés * (séparés par des virgules)<input name="keywords" required></label>
        <label>Rubrique du plan de classement<select name="classification_id">${planOptions()}</select></label>
        <label>DUA (années) — vide = héritée de la rubrique<input type="number" min="0" max="200" name="dua_years"></label>
        <label>Sort final<select name="final_disposition"><option value="">Hérité de la rubrique</option>
          <option value="DESTROY">Destruction</option><option value="ARCHIVE">Archivage définitif</option></select></label>
      </div>
      <label>Description<textarea name="description" rows="2"></textarea></label>
      <label>Fichier(s) * — plusieurs fichiers ou un ZIP = import par lot<input type="file" name="file" multiple required></label>
      <div class="row"><button class="btn primary">Déposer</button><span class="muted">Empreinte SHA-256, chiffrement AES-256 et conversion PDF/A + OCR automatiques.</span></div>
      <div id="up-res"></div>
    </form>`;
  $("#uf").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const files = f.getAll("file");
    const meta = {
      title: f.get("title"), author: f.get("author"), document_date: f.get("document_date"),
      doc_type: f.get("doc_type"), keywords: f.get("keywords").split(",").map((k) => k.trim()).filter(Boolean),
      description: f.get("description"),
      dua_years: f.get("dua_years") ? +f.get("dua_years") : null,
      final_disposition: f.get("final_disposition") || null,
      classification_id: f.get("classification_id") ? +f.get("classification_id") : null,
    };
    const body = new FormData();
    try {
      if (files.length === 1 && !files[0].name.toLowerCase().endsWith(".zip")) {
        body.append("file", files[0]);
        body.append("metadata", JSON.stringify(meta));
        const d = await api("/api/documents", { method: "POST", body });
        toast(`Document ${d.reference} déposé`);
        openDoc(d.id);
      } else {
        files.forEach((x) => body.append("files", x));
        delete meta.title;
        body.append("metadata", JSON.stringify(meta));
        const r = await api("/api/documents/batch", { method: "POST", body });
        $("#up-res").innerHTML = `<p><strong>${r.created.length}</strong> créé(s), <strong>${r.errors.length}</strong> erreur(s)</p>
          ${r.errors.map((x) => `<p class="error">${esc(x.file)} : ${esc(JSON.stringify(x.error))}</p>`).join("")}
          ${docTable(r.created)}`;
        bindRows($("#up-res"));
      }
    } catch (err) { toast(err.message, true); }
  };
};

/* ------------------------------------------------------------------ Plan de classement */
VIEWS.plan = async () => {
  const tree = await api("/api/classification");
  const render = (nodes) => `<ul>${nodes.map((n) => `<li><span class="ref">${esc(n.code)}</span> <strong>${esc(n.label)}</strong>
    ${n.default_dua_years != null ? `<span class="muted"> · DUA ${n.default_dua_years} ans · ${n.default_final_disposition === "ARCHIVE" ? "archivage définitif" : "destruction"}</span>` : ""}
    ${n.children.length ? render(n.children) : ""}</li>`).join("")}</ul>`;
  $("#main").innerHTML = `<h1>Plan de classement</h1>
    <div class="grid ${can("classification:manage") ? "g2" : ""}">
      <div class="card tree">${render(tree)}</div>
      ${can("classification:manage") ? `<form id="pf" class="card grid"><h2>Nouvelle rubrique</h2>
        <label>Code *<input name="code" required placeholder="RH.03"></label><label>Libellé *<input name="label" required></label>
        <label>Rubrique parente<select name="parent_id">${planOptions().replace("— Automatique —", "(racine)")}</select></label>
        <div class="grid g2"><label>DUA par défaut (ans)<input type="number" name="default_dua_years"></label>
        <label>Sort final<select name="default_final_disposition"><option value="">—</option><option>DESTROY</option><option>ARCHIVE</option></select></label></div>
        <label>Types de documents (classement auto, virgules)<input name="rule_doc_types"></label>
        <label>Mots-clés déclencheurs (virgules)<input name="rule_keywords"></label>
        <button class="btn primary">Créer</button></form>` : ""}
    </div>`;
  if ($("#pf")) $("#pf").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const list = (k) => (f.get(k) || "").split(",").map((x) => x.trim()).filter(Boolean);
    try {
      await api("/api/classification", { method: "POST", json: {
        code: f.get("code"), label: f.get("label"), parent_id: f.get("parent_id") ? +f.get("parent_id") : null,
        default_dua_years: f.get("default_dua_years") ? +f.get("default_dua_years") : null,
        default_final_disposition: f.get("default_final_disposition") || null,
        rule_doc_types: list("rule_doc_types"), rule_keywords: list("rule_keywords") } });
      S.plan = await api("/api/classification/flat");
      toast("Rubrique créée"); go("plan");
    } catch (err) { toast(err.message, true); }
  };
};

/* ------------------------------------------------------------------ Conformité */
VIEWS.compliance = async () => {
  $("#main").innerHTML = `<h1>Conformité &amp; traçabilité</h1>
    <div class="grid g2">
      <div class="card"><h2>Journal d'audit</h2><p class="muted">Chaîne d'empreintes SHA-256 : toute altération est détectée.</p>
        <button class="btn" id="vchain">Vérifier la chaîne</button><div id="chain-res"></div></div>
      <div class="card"><h2>Intégrité des fichiers</h2><p class="muted">Recalcul des empreintes SHA-256 de tous les fichiers stockés.</p>
        ${can("admin:jobs") ? '<button class="btn" id="vint">Lancer le contrôle</button>' : ""}<div id="int-res"></div></div>
    </div>
    ${can("retention:manage") ? `<div class="card"><div class="row"><h2>DUA échues — bordereau</h2><span class="spacer"></span>
      <button class="btn" id="rdry">Simuler</button><button class="btn danger" id="rrun">Appliquer le sort final</button></div>
      <div id="due"></div></div>` : ""}
    <div class="card"><h2>Dernières entrées du journal</h2><div id="audit"></div></div>`;
  $("#vchain").onclick = async () => {
    const r = await api("/api/audit/verify");
    $("#chain-res").innerHTML = `<p class="${r.valid ? "" : "error"}"><strong>${esc(r.message)}</strong> — ${r.entries_checked} entrées vérifiées</p>`;
  };
  const showInt = (r) => r && ($("#int-res").innerHTML = `<p>${r.files_checked} fichiers contrôlés le ${fmtDT(r.finished_at)} :
    <strong class="${r.failures.length ? "error" : ""}">${r.failures.length} anomalie(s)</strong></p>
    ${r.failures.map((f) => `<p class="error mono">${esc(f.storage_key)} — ${esc(f.error)}</p>`).join("")}`);
  showInt(await api("/api/admin/integrity/last"));
  if ($("#vint")) $("#vint").onclick = async () => showInt(await api("/api/admin/integrity/run", { method: "POST" }));
  if ($("#due")) {
    const loadDue = async () => { $("#due").innerHTML = docTable(await api("/api/retention/due")); bindRows($("#due")); };
    await loadDue();
    $("#rdry").onclick = async () => {
      const r = await api("/api/retention/run", { method: "POST", json: { dry_run: true } });
      toast(`Simulation : ${r.destroyed.length} à éliminer, ${r.archived.length} à verser`);
    };
    $("#rrun").onclick = async () => {
      if (!confirm("Appliquer le sort final (destruction physique irréversible / versement définitif) ?")) return;
      const r = await api("/api/retention/run", { method: "POST", json: { dry_run: false } });
      toast(`${r.destroyed.length} éliminé(s), ${r.archived.length} versé(s)`); loadDue();
    };
  }
  const logs = await api("/api/audit?size=40");
  $("#audit").innerHTML = `<table><thead><tr><th>Date</th><th>Acteur</th><th>Action</th><th>Objet</th><th>IP</th></tr></thead><tbody>
    ${logs.map((l) => `<tr><td>${fmtDT(l.created_at)}</td><td>${esc(l.actor)}</td><td><span class="badge">${esc(l.action)}</span></td>
      <td class="mono">${esc(l.object_type)} ${esc(l.object_id || "")}</td><td class="mono">${esc(l.ip_address)}</td></tr>`).join("")}</tbody></table>`;
};

/* ------------------------------------------------------------------ Interopérabilité */
VIEWS.integrations = async () => {
  const [keys, hooks, evs] = await Promise.all([api("/api/integrations/api-keys"), api("/api/integrations/webhooks"), api("/api/integrations/events")]);
  $("#main").innerHTML = `<h1>Interopérabilité</h1>
    <p class="muted">Contrat d'API complet : <a href="/docs" target="_blank">/docs</a> (OpenAPI). Les applications (ERP, SIRH) s'authentifient avec l'en-tête <span class="mono">X-API-Key</span>.</p>
    <div class="grid g2">
      <div class="card"><h2>Clés d'API</h2>
        <table><tbody>${keys.map((k) => `<tr><td><strong>${esc(k.name)}</strong><div class="mono">${esc(k.key_prefix)}… · ${esc(k.role.name)}</div></td>
          <td>${k.is_active ? "Active" : "Révoquée"}</td><td>${k.is_active ? `<button class="btn sm danger" data-revoke="${k.id}">Révoquer</button>` : ""}</td></tr>`).join("")}</tbody></table>
        <form id="kf" class="row" style="margin-top:12px"><input name="name" placeholder="ERP Sage" required style="flex:1">
          <select name="role" style="width:auto"><option>contributeur</option><option>lecteur</option><option>validateur</option><option>archiviste</option></select>
          <button class="btn primary">Créer</button></form><div id="newkey"></div></div>
      <div class="card"><h2>Webhooks</h2>
        <table><tbody>${hooks.map((h) => `<tr><td><strong>${esc(h.name)}</strong><div class="mono">${esc(h.url)}</div></td><td class="mono">${esc(h.events.join(", "))}</td>
          <td>${h.is_active ? "Actif" : "Inactif"}</td></tr>`).join("")}</tbody></table>
        <form id="hf" class="grid" style="margin-top:12px"><input name="name" placeholder="SIRH" required>
          <input name="url" placeholder="https://sirh.exemple.ga/webhooks/siged" required>
          <select name="events" multiple size="4"><option value="*" selected>* (tous)</option>${evs.map((e) => `<option>${e}</option>`).join("")}</select>
          <button class="btn primary">Abonner</button></form><div id="newhook"></div></div>
    </div>`;
  $("#main").querySelectorAll("[data-revoke]").forEach((b) => (b.onclick = async () => {
    await api(`/api/integrations/api-keys/${b.dataset.revoke}`, { method: "DELETE" }); go("integrations"); }));
  $("#kf").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const k = await api("/api/integrations/api-keys", { method: "POST", json: Object.fromEntries(new FormData(e.target)) });
      $("#newkey").innerHTML = `<p>Clé à copier maintenant (elle ne sera plus affichée) :</p><p class="mono card">${esc(k.api_key)}</p>`;
    } catch (err) { toast(err.message, true); }
  };
  $("#hf").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      const h = await api("/api/integrations/webhooks", { method: "POST", json: { name: f.get("name"), url: f.get("url"), events: f.getAll("events") } });
      $("#newhook").innerHTML = `<p>Secret HMAC (à conserver) :</p><p class="mono card">${esc(h.secret)}</p>`;
    } catch (err) { toast(err.message, true); }
  };
};

/* ------------------------------------------------------------------ Fiche document */
async function openDoc(id, tab = "meta") {
  const d = await api(`/api/documents/${id}`);
  const v = d.current_version;
  const dlg = $("#doc-dialog");
  const wf = [];
  if (d.status === "DRAFT" && can("document:write")) wf.push(`<button class="btn primary" data-wf="submit">Soumettre à validation</button>`);
  if (d.status === "PENDING_VALIDATION" && can("document:validate"))
    wf.push(`<button class="btn primary" data-wf="approve">Approuver</button><button class="btn danger" data-wf="reject">Rejeter</button>`);
  $("#doc-panel").innerHTML = `
    <div class="row"><span class="ref">${esc(d.reference)}</span>${badge(d.status)}${d.legal_hold ? '<span class="badge">Gel juridique</span>' : ""}
      <span class="spacer"></span><button class="btn ghost" id="close">Fermer ✕</button></div>
    <h1 style="margin-top:8px">${esc(d.title)}</h1>
    <div class="row">${wf.join("")}
      ${v && d.status !== "DESTROYED" ? `<button class="btn" data-dl="original">Télécharger l'original</button>` : ""}
      ${v && v.archival_format ? `<button class="btn" data-dl="archival">Télécharger le PDF/A</button>` : ""}
      ${can("retention:manage") && d.status !== "DESTROYED" ? `<button class="btn" id="aip">Exporter l'AIP (OAIS)</button>
        <button class="btn" id="hold">${d.legal_hold ? "Lever le gel" : "Geler"}</button>` : ""}</div>
    <div class="doc-layout" style="margin-top:14px">
      <div id="pv" class="preview"><p class="muted" style="padding:12px">Aperçu en cours de chargement…</p></div>
      <div>
        <div class="tabs">${[["meta", "Métadonnées"], ["versions", "Versions"], ["wf", "Circuit"], ["audit", "Traçabilité"]]
          .map(([k, l]) => `<button data-tab="${k}" class="${k === tab ? "active" : ""}">${l}</button>`).join("")}</div>
        <div id="tab"></div>
      </div>
    </div>`;
  if (!dlg.open) dlg.showModal();
  $("#close").onclick = () => dlg.close();
  $("#doc-panel").querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => openDoc(id, b.dataset.tab)));
  $("#doc-panel").querySelectorAll("[data-wf]").forEach((b) => (b.onclick = async () => {
    let comment = "";
    if (b.dataset.wf === "reject") { comment = prompt("Motif du rejet (obligatoire) :") || ""; if (!comment) return; }
    try { await api(`/api/documents/${id}/${b.dataset.wf}`, { method: "POST", json: { comment } }); toast("Statut mis à jour"); openDoc(id, "wf"); }
    catch (err) { toast(err.message, true); }
  }));
  $("#doc-panel").querySelectorAll("[data-dl]").forEach((b) => (b.onclick = () => download(`/api/documents/${id}/download?format=${b.dataset.dl}`)));
  if ($("#aip")) $("#aip").onclick = () => download(`/api/documents/${id}/aip`);
  if ($("#hold")) $("#hold").onclick = async () => {
    const reason = prompt("Motif :"); if (!reason) return;
    try { await api(`/api/documents/${id}/legal-hold`, { method: "PUT", json: { legal_hold: !d.legal_hold, reason } }); openDoc(id, tab); }
    catch (err) { toast(err.message, true); }
  };
  renderTab(d, tab);
  loadPreview(d);
}

const blobUrls = [];
async function loadPreview(d) {
  const box = $("#pv");
  blobUrls.splice(0).forEach((u) => URL.revokeObjectURL(u));
  try {
    const info = await api(`/api/documents/${d.id}/preview/pages`);
    if (info.pages > 0) {
      // Aperçu en images rendues côté serveur : fonctionne sur tous les navigateurs, y compris mobiles
      box.innerHTML = `<div class="row" style="padding:8px"><span class="muted">${info.pages} page(s)</span><span class="spacer"></span>
        <button class="btn sm" id="pdfview">Ouvrir le PDF</button></div><div id="pages"></div>`;
      $("#pdfview").onclick = async () => {
        const r = await api(`/api/documents/${d.id}/preview`, { raw: true });
        const u = URL.createObjectURL(await r.blob()); blobUrls.push(u); window.open(u, "_blank");
      };
      for (let i = 1; i <= Math.min(info.pages, 30); i++) {
        if (!$("#pages")) return; // fiche fermée entre-temps
        const r = await api(`/api/documents/${d.id}/preview/page/${i}`, { raw: true });
        const u = URL.createObjectURL(await r.blob()); blobUrls.push(u);
        $("#pages").insertAdjacentHTML("beforeend", `<img class="page" src="${u}" alt="Page ${i}">`);
      }
      return;
    }
    const r = await api(`/api/documents/${d.id}/preview`, { raw: true });
    const blob = await r.blob();
    const u = URL.createObjectURL(blob); blobUrls.push(u);
    box.innerHTML = blob.type.startsWith("image/") ? `<img class="page" src="${u}" alt="Aperçu">`
      : `<iframe src="${u}" title="Aperçu" style="width:100%;height:100%;border:0"></iframe>`;
  } catch (err) { box.innerHTML = `<p class="muted" style="padding:12px">${esc(err.message)}</p>`; }
}

async function download(path) {
  try {
    const r = await api(path, { raw: true });
    const cd = r.headers.get("content-disposition") || "";
    const m = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)/.exec(cd);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await r.blob());
    a.download = m ? decodeURIComponent(m[1] || m[2]) : "document";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  } catch (err) { toast(err.message, true); }
}

async function renderTab(d, tab) {
  const el = $("#tab");
  if (tab === "meta") {
    const editable = d.status === "DRAFT" && can("document:write");
    el.innerHTML = `<dl class="meta">
      <dt>Auteur</dt><dd>${esc(d.author)}</dd><dt>Date</dt><dd>${fmtDate(d.document_date)}</dd>
      <dt>Type</dt><dd>${esc(d.doc_type)}</dd><dt>Mots-clés</dt><dd>${d.keywords.map(esc).join(", ")}</dd>
      <dt>Rubrique</dt><dd>${d.classification ? `${esc(d.classification.code)} · ${esc(d.classification.label)}` : "—"}</dd>
      <dt>DUA</dt><dd>${d.dua_years} ans → ${fmtDate(d.retention_until)}</dd>
      <dt>Sort final</dt><dd>${d.final_disposition === "ARCHIVE" ? "Archivage définitif" : "Destruction"}</dd>
      <dt>Source</dt><dd>${esc(d.source)}</dd><dt>Description</dt><dd>${esc(d.description) || "—"}</dd>
      ${Object.entries(d.extra).map(([k, val]) => `<dt>${esc(k)}</dt><dd>${esc(val)}</dd>`).join("")}
      ${d.current_version ? `<dt>SHA-256</dt><dd class="mono">${esc(d.current_version.sha256)}</dd>
        <dt>Format pérenne</dt><dd>${esc(d.current_version.archival_format || "—")} · conversion ${esc(d.current_version.conversion_status)}${d.current_version.ocr_applied ? " · OCR" : ""}</dd>` : ""}
    </dl>
    ${editable ? `<form id="mf" class="grid" style="margin-top:14px"><h3>Modifier (brouillon)</h3>
      <label>Titre<input name="title" value="${esc(d.title)}"></label>
      <div class="grid g2"><label>Auteur<input name="author" value="${esc(d.author)}"></label><label>Type<input name="doc_type" value="${esc(d.doc_type)}"></label></div>
      <label>Mots-clés<input name="keywords" value="${esc(d.keywords.join(", "))}"></label>
      <label>Rubrique<select name="classification_id">${planOptions(d.classification?.id)}</select></label>
      <button class="btn">Enregistrer</button></form>` : ""}`;
    if ($("#mf")) $("#mf").onsubmit = async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      try {
        await api(`/api/documents/${d.id}`, { method: "PATCH", json: { title: f.get("title"), author: f.get("author"),
          doc_type: f.get("doc_type"), keywords: f.get("keywords").split(",").map((k) => k.trim()).filter(Boolean),
          classification_id: f.get("classification_id") ? +f.get("classification_id") : null } });
        toast("Métadonnées enregistrées"); openDoc(d.id);
      } catch (err) { toast(err.message, true); }
    };
  } else if (tab === "versions") {
    el.innerHTML = `<table><thead><tr><th>Version</th><th>Fichier</th><th>Déposée</th><th></th></tr></thead><tbody>
      ${[...d.versions].reverse().map((v) => `<tr><td><strong>v${esc(v.label)}</strong>${v.is_current ? " ●" : ""}${v.is_frozen ? ' <span class="badge">figée</span>' : ""}
        <div class="muted">${esc(v.comment)}</div></td>
        <td>${esc(v.original_filename)}<div class="muted">${fmtSize(v.size_bytes)} · ${esc(v.archival_format || v.mime_type)}</div></td>
        <td>${fmtDT(v.created_at)}</td>
        <td><button class="btn sm" data-ver="${v.id}">Vérifier</button> <button class="btn sm" data-get="${v.id}">Original</button></td></tr>`).join("")}
    </tbody></table>
    ${can("document:write") && !["PENDING_VALIDATION", "ARCHIVED", "DESTROYED"].includes(d.status) ? `<form id="vf" class="grid" style="margin-top:14px">
      <h3>Nouvelle version</h3>${d.status === "VALIDATED" ? '<p class="muted">Document validé : la nouvelle version sera majeure et repassera en brouillon.</p>' : ""}
      <input type="file" name="file" required><input name="comment" placeholder="Commentaire de version">
      <label class="row" style="font-weight:400"><input type="checkbox" name="major" value="true" style="width:auto"> Version majeure</label>
      <button class="btn primary">Déposer la version</button></form>` : ""}`;
    el.querySelectorAll("[data-ver]").forEach((b) => (b.onclick = async () => {
      const r = await api(`/api/documents/${d.id}/versions/${b.dataset.ver}/verify`);
      toast(r.intact ? `v${r.version} intègre (SHA-256 conforme)` : `v${r.version} ALTÉRÉE : ${r.failures.map((f) => f.error).join(" ; ")}`, !r.intact);
    }));
    el.querySelectorAll("[data-get]").forEach((b) => (b.onclick = () => download(`/api/documents/${d.id}/download?version_id=${b.dataset.get}`)));
    if ($("#vf")) $("#vf").onsubmit = async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      if (!f.get("major")) f.set("major", "false");
      try { const v = await api(`/api/documents/${d.id}/versions`, { method: "POST", body: f }); toast(`Version ${v.label} déposée`); openDoc(d.id, "versions"); }
      catch (err) { toast(err.message, true); }
    };
  } else if (tab === "wf") {
    const h = await api(`/api/documents/${d.id}/workflow`);
    el.innerHTML = h.length ? `<table><tbody>${h.map((x) => `<tr><td>${fmtDT(x.created_at)}</td><td>${badge(x.from_status)} → ${badge(x.to_status)}</td>
      <td><strong>${esc(x.actor_name)}</strong><div class="muted">${esc(x.comment)}</div></td></tr>`).join("")}</tbody></table>`
      : '<p class="muted">Aucune étape de validation pour l\'instant.</p>';
  } else if (tab === "audit") {
    if (!can("audit:read")) { el.innerHTML = '<p class="muted">Réservé aux profils habilités (audit:read).</p>'; return; }
    const logs = await api(`/api/documents/${d.id}/audit`);
    el.innerHTML = `<table><tbody>${logs.map((l) => `<tr><td>${fmtDT(l.created_at)}</td><td><span class="badge">${esc(l.action)}</span></td>
      <td>${esc(l.actor)}</td></tr>`).join("")}</tbody></table>`;
  }
}

boot();
