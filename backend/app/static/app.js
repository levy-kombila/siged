/* GEDarchive — interface web (JavaScript natif, sans dépendance). Consomme l'API REST. */
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
const KINDS = { SITE: "Site", SALLE: "Salle", RAYONNAGE: "Rayonnage", TRAVEE: "Travée", TABLETTE: "Tablette", BOITE: "Boîte" };
const TITLES = { dashboard: "Tableau de bord", search: "Rechercher", upload: "Déposer", scan: "Numériser", plan: "Plan de classement",
  users: "Utilisateurs", shelving: "Rayonnage", deadlines: "Échéances", compliance: "Conformité", integrations: "Interopérabilité" };
const daysLeft = (d) => Math.round((new Date(d + "T00:00:00") - new Date(new Date().toDateString())) / 86400000);
function dueChip(d) {
  if (!d) return "";
  const n = daysLeft(d);
  const cls = n <= 0 ? "late" : n <= 30 ? "soon" : "later";
  const txt = n < 0 ? `Obsolète depuis ${-n} j` : n === 0 ? "Obsolète aujourd'hui" : `Obsolète dans ${n} j`;
  return `<span class="due ${cls}" title="Fin de validité : ${fmtDate(d)}">${txt}</span>`;
}
const docOpen = (d) => !["ARCHIVED", "DESTROYED"].includes(d.status);

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
    $("#who").textContent = `${me.name} (${me.role})`;
    $("#avatar").textContent = (me.name || "?").trim().charAt(0).toUpperCase();
    refreshBell();
    clearInterval(S.bellTimer);
    S.bellTimer = setInterval(refreshBell, 120000);
    document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("hidden", !!a.dataset.perm && !can(a.dataset.perm)));
    go(location.hash.slice(1) || "dashboard");
  } catch { showLogin(); }
}
function showLogin() { $("#app").classList.add("hidden"); $("#login-view").classList.remove("hidden"); }
function logout() { clearInterval(S.bellTimer); S.token = null; sessionStorage.removeItem("siged_token"); showLogin(); }

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  try {
    const t = await api("/api/auth/login", { method: "POST", body: new URLSearchParams(new FormData(e.target)) });
    hideAllPasswords($("#login-form")); e.target.reset();   // ne pas laisser le mot de passe visible ni rempli
    S.token = t.access_token;
    sessionStorage.setItem("siged_token", S.token);
    boot();
  } catch (err) { $("#login-error").textContent = err.message; }
});
$("#logout").onclick = logout;

/* Mot de passe : afficher / masquer (repasse en masqué à l'envoi) et avertissement Verr. Maj */
function setPwdVisible(btn, show) {
  const input = btn.parentElement.querySelector("input");
  input.type = show ? "text" : "password";
  btn.setAttribute("aria-pressed", String(show));
  btn.setAttribute("aria-label", show ? "Masquer le mot de passe" : "Afficher le mot de passe");
  btn.title = btn.getAttribute("aria-label");
  btn.querySelector("use").setAttribute("href", show ? "#i-eye-off" : "#i-eye");
}
// Tous les champs mot de passe (connexion, Mon compte, Utilisateurs) : bouton œil générique
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".pwd-toggle");
  if (!btn) return;
  setPwdVisible(btn, btn.getAttribute("aria-pressed") !== "true");
  btn.parentElement.querySelector("input").focus();
});
const hideAllPasswords = (root = document) => root.querySelectorAll('.pwd-toggle[aria-pressed="true"]').forEach((b) => setPwdVisible(b, false));
const pwdField = (name, label, auto = "new-password", extra = "") => `<label for="f-${name}">${label}</label>
  <div class="pwd"><input id="f-${name}" name="${name}" type="password" autocomplete="${auto}" ${extra}>
  <button type="button" class="pwd-toggle" aria-label="Afficher le mot de passe" aria-pressed="false"><svg class="i"><use href="#i-eye"/></svg></button></div>`;
function strongPassword() {
  const sets = ["ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnopqrstuvwxyz", "23456789", "#@%+=?!*"];
  const rnd = (n) => crypto.getRandomValues(new Uint32Array(1))[0] % n;
  const chars = sets.map((x) => x[rnd(x.length)]);
  const all = sets.join("");
  while (chars.length < 14) chars.push(all[rnd(all.length)]);
  for (let i = chars.length - 1; i > 0; i--) { const j = rnd(i + 1); [chars[i], chars[j]] = [chars[j], chars[i]]; }
  return chars.join("");
}

/* Mon compte : changement de mot de passe */
$("#account-btn").onclick = () => {
  $("#pwf").reset(); $("#pw-error").textContent = ""; hideAllPasswords($("#pwf"));
  $("#account-info").textContent = `${S.name} · profil ${S.role}`;
  $("#account-dialog").showModal();
};
$("#account-close").onclick = () => $("#account-dialog").close();
$("#pwf").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  $("#pw-error").textContent = "";
  if (f.get("new_password") !== f.get("confirm")) { $("#pw-error").textContent = "Les deux nouveaux mots de passe ne sont pas identiques."; return; }
  try {
    await api("/api/auth/password", { method: "POST", json: { current_password: f.get("current_password"), new_password: f.get("new_password") } });
    hideAllPasswords($("#pwf")); $("#account-dialog").close(); toast("Mot de passe changé");
  } catch (err) { $("#pw-error").textContent = err.message; }
};
["keydown", "keyup"].forEach((ev) => $("#login-password").addEventListener(ev, (e) => {
  if (e.getModifierState) $("#caps").classList.toggle("hidden", !e.getModifierState("CapsLock"));
}));
$("#nav").addEventListener("click", (e) => { const a = e.target.closest("a[data-view]"); if (a) go(a.dataset.view); });

const VIEWS = {};
function go(view) {
  if (!VIEWS[view]) view = "dashboard";
  location.hash = view;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  $("#page-title").textContent = TITLES[view] || "";
  stopCamera();
  closeBell();
  $("#main").innerHTML = '<p class="muted">Chargement…</p>';
  VIEWS[view]().catch((e) => ($("#main").innerHTML = `<p class="error">${esc(e.message)}</p>`));
}

/* ------------------------------------------------------------------ Notifications */
async function refreshBell() {
  try {
    const n = await api("/api/notifications?size=1");
    const c = $("#bell-count");
    c.textContent = n.unread > 99 ? "99+" : n.unread;
    c.classList.toggle("hidden", !n.unread);
  } catch { /* silencieux : la cloche ne doit jamais bloquer l'interface */ }
}
function closeBell() { $("#notif-panel").classList.add("hidden"); $("#bell-btn").setAttribute("aria-expanded", "false"); }
async function openBell() {
  const panel = $("#notif-panel");
  const n = await api("/api/notifications?size=30");
  panel.innerHTML = `<header><strong>Notifications</strong><span class="spacer"></span>
      ${n.unread ? '<button class="btn sm ghost" id="read-all">Tout marquer comme lu</button>' : ""}</header>
    <div class="notif-list">${n.items.length ? n.items.map((x) => `
      <div class="notif ${x.read_at ? "read" : "unread"}" data-n="${x.id}" data-doc="${esc(x.document_id || "")}">
        <span class="dot"></span><div><strong>${esc(x.title)}</strong><p>${esc(x.message)}</p>
        <p class="muted">${fmtDT(x.created_at)}</p></div></div>`).join("")
      : '<p class="empty">Aucune notification. Les alertes d\'obsolescence apparaîtront ici.</p>'}</div>`;
  panel.classList.remove("hidden");
  $("#bell-btn").setAttribute("aria-expanded", "true");
  if ($("#read-all")) $("#read-all").onclick = async (e) => {
    e.stopPropagation(); await api("/api/notifications/read-all", { method: "POST" }); refreshBell(); openBell(); };
  panel.querySelectorAll("[data-n]").forEach((el) => (el.onclick = async () => {
    await api(`/api/notifications/${el.dataset.n}/read`, { method: "POST" }).catch(() => {});
    refreshBell(); closeBell();
    if (el.dataset.doc) openDoc(el.dataset.doc);
  }));
}
$("#bell-btn").onclick = (e) => { e.stopPropagation(); $("#notif-panel").classList.contains("hidden") ? openBell().catch((err) => toast(err.message, true)) : closeBell(); };
document.addEventListener("click", (e) => { if (!e.target.closest("#bell")) closeBell(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeBell(); });

/* ------------------------------------------------------------------ Tableau de bord */
VIEWS.dashboard = async () => {
  const s = await api("/api/admin/stats");
  const st = s.documents_by_status;
  const [recent, soon] = await Promise.all([api("/api/search?sort=created_desc&size=8"), api("/api/obsolescence/upcoming?days=30")]);
  $("#main").innerHTML = `
    <h1>Bonjour ${esc((S.name || "").split(" ")[0])}</h1>
    <p class="lede">Voici l'état de vos archives aujourd'hui, ${new Date().toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" })}.</p>
    <div class="kpis">
      <div class="kpi"><b>${(st.DRAFT || 0) + (st.PENDING_VALIDATION || 0) + (st.VALIDATED || 0)}</b><span>documents actifs</span></div>
      <div class="kpi"><b>${st.PENDING_VALIDATION || 0}</b><span>en attente de validation</span></div>
      <div class="kpi ${s.obsolete_soon ? "alert" : ""}"><b>${s.obsolete_soon}</b><span>deviennent obsolètes sous 30 jours</span></div>
      <div class="kpi ${s.retention_due ? "alert" : ""}"><b>${s.retention_due}</b><span>DUA échues à traiter</span></div>
      <div class="kpi"><b>${s.shelved}</b><span>exemplaires papier rangés</span></div>
    </div>
    <div class="grid split">
      <div class="card"><h2>Derniers dépôts</h2>${docTable(recent.items, false, true)}</div>
      <div class="card"><div class="row"><h2>À surveiller sous 30 jours</h2><span class="spacer"></span><a data-go="deadlines">Toutes les échéances</a></div>
        ${deadlineList(soon.slice(0, 8))}</div>
    </div>`;
  $("#main").querySelector("[data-go]").onclick = () => go("deadlines");
  bindRows();
};

function docTable(items, withSnippet = false, compact = false) {
  if (!items.length) return '<p class="empty">Aucun document pour le moment.</p>';
  if (compact) return `<table><tbody>${items.map((d) => `<tr class="click" data-id="${esc(d.id)}">
      <td><span class="ref">${esc(d.reference)}</span><div><strong>${esc(d.title)}</strong></div><div class="muted">${esc(d.author)}</div></td>
      <td class="muted">${fmtDate(d.document_date)}</td><td>${badge(d.status)}</td></tr>`).join("")}</tbody></table>`;
  return `<table><thead><tr><th>Cote</th><th>Titre</th><th>Type</th><th>Date</th><th>Rubrique</th><th>Statut</th></tr></thead><tbody>
    ${items.map((d) => `<tr class="click" data-id="${esc(d.id)}">
      <td class="ref">${esc(d.reference)}</td>
      <td><strong>${esc(d.title)}</strong><div class="muted">${esc(d.author)}</div>
        ${withSnippet && d.snippet ? `<div class="snippet">${safeSnippet(d.snippet)}</div>` : ""}</td>
      <td>${esc(d.doc_type)}</td><td>${fmtDate(d.document_date)}</td>
      <td>${d.classification ? `<span class="ref">${esc(d.classification.code)}</span>` : '<span class="muted">—</span>'}</td>
      <td><div class="row">${badge(d.status)}${d.legal_hold ? '<span class="badge">Gel</span>' : ""}
        ${docOpen(d) && d.valid_until && daysLeft(d.valid_until) <= 30 ? dueChip(d.valid_until) : ""}</div></td></tr>`).join("")}
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
    <p class="lede">Remplissez la fiche une fois : elle s'applique à tous les fichiers déposés ensemble.
      Un document papier à numériser ? <a data-go="scan">Utilisez l'appareil photo</a>.</p>
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
        <label>Fin de validité <small>date à laquelle le document devient obsolète (contrat, attestation…)</small>
          <input type="date" name="valid_until"></label>
      </div>
      <label>Description<textarea name="description" rows="2"></textarea></label>
      <label>Fichier(s) * — plusieurs fichiers ou un ZIP = import par lot<input type="file" name="file" multiple required></label>
      <div class="row"><button class="btn primary">Déposer</button><span class="muted">Chaque fichier est scellé (SHA-256), chiffré et converti en PDF/A avec OCR.</span></div>
      <div id="up-res"></div>
    </form>`;
  $("#main").querySelector('[data-go="scan"]').onclick = () => go("scan");
  $("#uf").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const files = f.getAll("file");
    const meta = {
      title: f.get("title"), author: f.get("author"), document_date: f.get("document_date"),
      doc_type: f.get("doc_type"), keywords: f.get("keywords").split(",").map((k) => k.trim()).filter(Boolean),
      description: f.get("description"), valid_until: f.get("valid_until") || null,
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

/* ------------------------------------------------------------------ Utilisateurs */
VIEWS.users = async () => {
  const [users, roles, me] = await Promise.all([api("/api/users"), api("/api/roles"), api("/api/auth/me")]);
  const myId = me.user?.id;
  const ROLE_LABEL = { admin: "Administrateur", archiviste: "Archiviste", validateur: "Validateur", contributeur: "Contributeur", lecteur: "Lecteur" };
  const roleName = (r) => ROLE_LABEL[r] || r;
  const locked = (u) => u.locked_until && new Date(u.locked_until) > new Date();
  const state = (u) => !u.is_active ? '<span class="badge pill-off">Désactivé</span>'
    : locked(u) ? `<span class="badge pill-lock" title="Trop d'échecs de connexion">Verrouillé jusqu'à ${new Date(u.locked_until).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}</span>`
    : '<span class="badge VALIDATED">Actif</span>';
  $("#main").innerHTML = `<h1>Utilisateurs</h1>
    <p class="lede">Créez les comptes, attribuez un profil et désactivez un compte quand une personne quitte le service.
      Un compte n'est jamais supprimé : son historique reste dans le journal d'audit.</p>
    <div class="grid split">
      <div class="card"><div class="row"><h2 style="margin:0">${users.length} compte${users.length > 1 ? "s" : ""}</h2><span class="spacer"></span>
          <input id="ufilter" placeholder="Filtrer par nom ou identifiant" style="max-width:260px"></div>
        <table style="margin-top:12px"><thead><tr><th>Utilisateur</th><th>Profil</th><th>État</th><th></th></tr></thead><tbody>
        ${users.map((u) => `<tr data-u="${u.id}" data-s="${esc((u.full_name + " " + u.username + " " + u.email).toLowerCase())}">
          <td><strong>${esc(u.full_name || u.username)}</strong>${u.id === myId ? ' <span class="muted">(vous)</span>' : ""}
            <div class="muted">${esc(u.username)} · ${esc(u.email)}</div></td>
          <td><select data-role="${u.id}" ${u.id === myId ? "disabled" : ""} aria-label="Profil de ${esc(u.username)}" style="width:auto">
            ${roles.map((r) => `<option value="${esc(r.name)}" ${r.name === u.role.name ? "selected" : ""}>${esc(roleName(r.name))}</option>`).join("")}</select></td>
          <td>${state(u)}</td>
          <td><div class="row" style="justify-content:flex-end">
            <button class="btn sm" data-reset="${u.id}">Nouveau mot de passe</button>
            ${u.id === myId ? "" : u.is_active
              ? `<button class="btn sm danger" data-active="${u.id}" data-v="false">Désactiver</button>`
              : `<button class="btn sm" data-active="${u.id}" data-v="true">Réactiver</button>`}
            ${u.is_active && locked(u) ? `<button class="btn sm" data-active="${u.id}" data-v="true">Déverrouiller</button>` : ""}</div></td></tr>`).join("")}
        </tbody></table></div>
      <div class="sticky">
        <form id="nuf" class="card grid" autocomplete="off"><h2>Nouveau compte</h2>
          <div class="grid g2"><label>Identifiant *<input name="username" required pattern="[a-zA-Z0-9_.\-]{3,80}" placeholder="j.mba"></label>
            <label>Profil<select name="role">${roles.map((r) => `<option value="${esc(r.name)}" ${r.name === "contributeur" ? "selected" : ""}>${esc(roleName(r.name))}</option>`).join("")}</select></label></div>
          <label>Nom complet<input name="full_name" placeholder="Jeanne Mba"></label>
          <label>E-mail *<input type="email" name="email" required></label>
          ${pwdField("password", "Mot de passe initial *", "new-password", 'required minlength="10"')}
          <div class="row"><button type="button" class="btn sm" id="genpw">Générer un mot de passe sûr</button>
            <span class="muted">Communiquez-le à la personne, qui le changera dans « Mon compte ».</span></div>
          <button class="btn primary">Créer le compte</button></form>
        <div class="card"><h2>Profils</h2><dl class="role-list">${roles.map((r) => `<dt>${esc(roleName(r.name))}</dt><dd>${esc(r.description)}</dd>`).join("")}</dl></div>
      </div>
    </div>`;
  const patch = async (id, body, msg) => {
    try { await api(`/api/users/${id}`, { method: "PATCH", json: body }); toast(msg); VIEWS.users(); }
    catch (err) { toast(err.message, true); VIEWS.users(); }
  };
  $("#ufilter").oninput = (e) => { const q = e.target.value.trim().toLowerCase();
    $("#main").querySelectorAll("tr[data-s]").forEach((tr) => tr.classList.toggle("hidden", !!q && !tr.dataset.s.includes(q))); };
  $("#main").querySelectorAll("[data-role]").forEach((sel) => (sel.onchange = () => patch(sel.dataset.role, { role: sel.value }, "Profil modifié")));
  $("#main").querySelectorAll("[data-active]").forEach((b) => (b.onclick = () => {
    const on = b.dataset.v === "true";
    if (!on && !confirm("Désactiver ce compte ? La personne ne pourra plus se connecter.")) return;
    patch(b.dataset.active, { is_active: on }, on ? "Compte réactivé et déverrouillé" : "Compte désactivé");
  }));
  $("#main").querySelectorAll("[data-reset]").forEach((b) => (b.onclick = async () => {
    const pw = strongPassword();
    if (!confirm(`Remplacer le mot de passe par :\n\n${pw}\n\nNotez-le avant de valider : il ne sera plus affiché.`)) return;
    try { await api(`/api/users/${b.dataset.reset}`, { method: "PATCH", json: { password: pw } }); toast("Mot de passe remplacé"); VIEWS.users(); }
    catch (err) { toast(err.message, true); }
  }));
  $("#genpw").onclick = () => {
    const input = $("#f-password"); input.value = strongPassword();
    setPwdVisible($("#nuf .pwd-toggle"), true);
  };
  $("#nuf").onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    try { const u = await api("/api/users", { method: "POST", json: f }); toast(`Compte ${u.username} créé`); VIEWS.users(); }
    catch (err) { toast(err.message, true); }
  };
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
          <input name="url" placeholder="https://sirh.exemple.ga/webhooks/gedarchive" required>
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

/* ------------------------------------------------------------------ Numérisation */
const SCAN = { pages: [], current: -1 };
const MAX_EXPORT = 2400;   // côté long des photos envoyées (suffisant pour 300 ppp en A4 après recadrage)

function stopCamera() {
  if (S.stream) { S.stream.getTracks().forEach((t) => t.stop()); S.stream = null; }
}
const loadImage = (src) => new Promise((ok, ko) => { const i = new Image(); i.onload = () => ok(i); i.onerror = () => ko(new Error("Image illisible")); i.src = src; });

/* Détection automatique de la feuille : plus grande zone claire de l'image (seuil d'Otsu),
   coins = points extrêmes de cette zone. Retourne null si rien de plausible. */
function detectCorners(src) {
  const k = 180 / Math.max(src.naturalWidth || src.width, src.naturalHeight || src.height);
  const w = Math.max(8, Math.round((src.naturalWidth || src.width) * k)), h = Math.max(8, Math.round((src.naturalHeight || src.height) * k));
  const c = document.createElement("canvas"); c.width = w; c.height = h;
  const ctx = c.getContext("2d", { willReadFrequently: true });
  ctx.filter = "blur(1px)"; ctx.drawImage(src, 0, 0, w, h);
  const px = ctx.getImageData(0, 0, w, h).data;
  const g = new Uint8Array(w * h), hist = new Array(256).fill(0);
  for (let i = 0; i < w * h; i++) { const v = (px[i * 4] * 0.299 + px[i * 4 + 1] * 0.587 + px[i * 4 + 2] * 0.114) | 0; g[i] = v; hist[v]++; }
  let sum = 0; hist.forEach((n, v) => (sum += n * v));
  let sB = 0, wB = 0, best = 0, t = 128;
  for (let v = 0; v < 256; v++) {
    wB += hist[v]; if (!wB) continue; const wF = w * h - wB; if (!wF) break;
    sB += v * hist[v]; const d = sB / wB - (sum - sB) / wF; const between = wB * wF * d * d;
    if (between > best) { best = between; t = v; }
  }
  const seen = new Uint8Array(w * h); let bestComp = null;
  for (let i = 0; i < w * h; i++) {
    if (seen[i] || g[i] <= t) continue;
    const stack = [i], comp = []; seen[i] = 1;
    while (stack.length) {
      const j = stack.pop(); comp.push(j); const x = j % w, y = (j / w) | 0;
      for (const n of [x > 0 && j - 1, x < w - 1 && j + 1, y > 0 && j - w, y < h - 1 && j + w])
        if (n !== false && !seen[n] && g[n] > t) { seen[n] = 1; stack.push(n); }
    }
    if (!bestComp || comp.length > bestComp.length) bestComp = comp;
  }
  if (!bestComp) return null;
  const ratio = bestComp.length / (w * h);
  if (ratio < 0.15 || ratio > 0.97) return null;
  let tl, tr, br, bl;
  for (const j of bestComp) {
    const x = j % w + 0.5, y = ((j / w) | 0) + 0.5;
    if (!tl || x + y < tl[0] + tl[1]) tl = [x, y];
    if (!br || x + y > br[0] + br[1]) br = [x, y];
    if (!tr || x - y > tr[0] - tr[1]) tr = [x, y];
    if (!bl || x - y < bl[0] - bl[1]) bl = [x, y];
  }
  const q = [tl, tr, br, bl].map(([x, y]) => [x / w, y / h]);
  return convex(q) ? q : null;
}
function convex(q) {
  let sign = 0;
  for (let i = 0; i < 4; i++) {
    const [a, b, c] = [q[i], q[(i + 1) % 4], q[(i + 2) % 4]];
    const cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
    if (Math.abs(cr) < 1e-4) return false;
    if (sign && Math.sign(cr) !== sign) return false; sign = Math.sign(cr);
  }
  return sign > 0;
}
const FULL = () => [[0, 0], [1, 0], [1, 1], [0, 1]];

async function addPhoto(source) {
  // source : File (photo / import) ou HTMLCanvasElement (caméra en direct)
  let img = source, url;
  if (source instanceof Blob) { url = URL.createObjectURL(source); img = await loadImage(url); }
  const sw = img.naturalWidth || img.width, sh = img.naturalHeight || img.height;
  const k = Math.min(1, MAX_EXPORT / Math.max(sw, sh));
  const c = document.createElement("canvas"); c.width = Math.round(sw * k); c.height = Math.round(sh * k);
  c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);   // orientation EXIF déjà appliquée par le navigateur
  if (url) URL.revokeObjectURL(url);
  const blob = await new Promise((ok) => c.toBlob(ok, "image/jpeg", 0.9));
  const auto = detectCorners(c);
  SCAN.pages.push({ blob, url: URL.createObjectURL(blob), w: c.width, h: c.height, corners: auto || FULL(), auto: !!auto, rotation: 0 });
  SCAN.current = SCAN.pages.length - 1;
}

VIEWS.scan = async () => {
  const today = new Date().toISOString().slice(0, 10);
  const live = !!(navigator.mediaDevices?.getUserMedia && window.isSecureContext);
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
  $("#main").innerHTML = `<h1>Numériser</h1>
    <p class="lede">Photographiez chaque page avec le téléphone ou la webcam. GEDarchive repère la feuille, la redresse,
      blanchit le fond puis assemble les pages en un seul PDF où le texte est reconnu et cherchable.</p>
    <div class="grid split">
      <div>
        <div class="card">
          <div class="row">
            <label class="btn primary file-btn"><svg class="i"><use href="#i-camera"/></svg>Photographier une page
              <input type="file" accept="image/*" capture="environment" id="snap"></label>
            <label class="btn file-btn"><svg class="i"><use href="#i-upload"/></svg>Importer des photos
              <input type="file" accept="image/*" multiple id="pick"></label>
            ${live ? '<button class="btn" type="button" id="live">Caméra en direct</button>' : ""}
          </div>
          <div id="cam" class="cam hidden"><video id="video" playsinline muted></video>
            <div class="row cam-bar"><button class="btn rose" type="button" id="shoot">Capturer la page</button>
              <button class="btn" type="button" id="cam-close">Fermer la caméra</button></div></div>
          <p class="muted tip">Posez la feuille à plat sur un fond plus sombre, bien éclairée : ses bords sont alors détectés automatiquement.</p>
        </div>
        <div class="card hidden" id="editor"></div>
        <div class="card"><div class="row"><h2 style="margin:0">Pages</h2><span class="spacer"></span><span class="muted" id="pcount"></span></div>
          <div id="strip" class="strip"></div></div>
      </div>
      <div class="sticky">
        <form id="scf" class="card grid"><h2>Fiche du document</h2>
          <label>Rendu
            <select name="mode"><option value="document">Document : texte net, fond blanc</option>
              <option value="gris">Niveaux de gris</option><option value="couleur">Couleur : photos, tampons</option></select></label>
          <label>Titre *<input name="title" required></label>
          <div class="grid g2"><label>Auteur *<input name="author" required value="${esc(S.name || "")}"></label>
            <label>Date du document *<input type="date" name="document_date" value="${today}" required></label></div>
          <div class="grid g2"><label>Type *<input name="doc_type" required placeholder="facture, courrier…"></label>
            <label>Mots-clés *<input name="keywords" required placeholder="séparés par des virgules"></label></div>
          <label>Rubrique<select name="classification_id">${planOptions()}</select></label>
          <div class="grid g2"><label>DUA (années) <small>vide = rubrique</small><input type="number" min="0" max="200" name="dua_years"></label>
            <label>Sort final<select name="final_disposition"><option value="">Hérité de la rubrique</option>
              <option value="DESTROY">Destruction</option><option value="ARCHIVE">Archivage définitif</option></select></label></div>
          <label>Fin de validité <small>facultatif</small><input type="date" name="valid_until"></label>
          <button class="btn primary" id="scan-go" disabled>Ajoutez au moins une page</button>
        </form>
        <div class="card qr-card"><h2>Continuer sur le téléphone</h2>
          <p class="muted">Visez ce code avec l'appareil photo du téléphone pour ouvrir cette page, puis connectez-vous.</p>
          <div id="qr" class="qr"></div>
          ${local ? `<p class="muted"><strong>${esc(location.host)}</strong> n'est joignable que depuis ce PC. Pour le téléphone,
            mettez le site en ligne (tunnel) et ouvrez cette page par son adresse publique.</p>` : ""}</div>
      </div>
    </div>`;

  const handleFiles = async (files) => {
    for (const f of files) { try { await addPhoto(f); } catch (err) { toast(err.message, true); } }
    renderScan();
  };
  $("#snap").onchange = (e) => { handleFiles([...e.target.files]); e.target.value = ""; };
  $("#pick").onchange = (e) => { handleFiles([...e.target.files]); e.target.value = ""; };
  if ($("#live")) $("#live").onclick = async () => {
    try {
      S.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false });
      const v = $("#video"); v.srcObject = S.stream; await v.play();
      $("#cam").classList.remove("hidden");
    } catch (err) { toast("Caméra inaccessible : " + err.message, true); }
  };
  $("#shoot").onclick = async () => {
    const v = $("#video"); if (!v.videoWidth) return;
    const c = document.createElement("canvas"); c.width = v.videoWidth; c.height = v.videoHeight;
    c.getContext("2d").drawImage(v, 0, 0);
    await addPhoto(c); renderScan(); toast(`Page ${SCAN.pages.length} capturée`);
  };
  $("#cam-close").onclick = () => { stopCamera(); $("#cam").classList.add("hidden"); };
  api(`/api/scan/qr?url=${encodeURIComponent(location.origin + "/#scan")}`, { raw: true })
    .then(async (r) => { if (!$("#qr")) return; const u = URL.createObjectURL(await r.blob()); $("#qr").innerHTML = `<img src="${u}" alt="QR code vers la page Numériser">`; })
    .catch(() => {});

  $("#scf").onsubmit = async (e) => {
    e.preventDefault();
    if (!SCAN.pages.length) return;
    const f = new FormData(e.target);
    const meta = { title: f.get("title"), author: f.get("author"), document_date: f.get("document_date"), doc_type: f.get("doc_type"),
      keywords: f.get("keywords").split(",").map((k) => k.trim()).filter(Boolean), valid_until: f.get("valid_until") || null,
      dua_years: f.get("dua_years") ? +f.get("dua_years") : null, final_disposition: f.get("final_disposition") || null,
      classification_id: f.get("classification_id") ? +f.get("classification_id") : null };
    const body = new FormData();
    SCAN.pages.forEach((p, i) => body.append("pages", p.blob, `page-${i + 1}.jpg`));
    body.append("metadata", JSON.stringify(meta));
    body.append("options", JSON.stringify({ mode: f.get("mode"), pages: SCAN.pages.map((p) => ({ corners: p.corners, rotation: p.rotation })) }));
    const btn = $("#scan-go"); btn.disabled = true; btn.textContent = "Création du PDF…";
    try {
      const d = await api("/api/scan", { method: "POST", body });
      SCAN.pages.forEach((p) => URL.revokeObjectURL(p.url)); SCAN.pages = []; SCAN.current = -1;
      toast(`Document ${d.reference} créé`); e.target.reset(); renderScan(); openDoc(d.id);
    } catch (err) { toast(err.message, true); renderScan(); }
  };
  renderScan();
};

function renderScan() {
  if (!$("#strip")) return;
  const n = SCAN.pages.length;
  $("#pcount").textContent = n ? `${n} page${n > 1 ? "s" : ""}` : "";
  const btn = $("#scan-go");
  btn.disabled = !n; btn.textContent = n ? `Créer le document (${n} page${n > 1 ? "s" : ""})` : "Ajoutez au moins une page";
  $("#strip").innerHTML = n ? SCAN.pages.map((p, i) => `<figure class="thumb ${i === SCAN.current ? "on" : ""}" data-i="${i}">
      <div class="thumb-img"><img src="${p.url}" alt="Page ${i + 1}" style="transform:rotate(${p.rotation}deg)"></div>
      <figcaption>Page ${i + 1}</figcaption></figure>`).join("")
    : '<p class="empty">Aucune page. Photographiez la première page du document.</p>';
  $("#strip").querySelectorAll("[data-i]").forEach((el) => (el.onclick = () => { SCAN.current = +el.dataset.i; renderScan(); }));
  renderEditor();
}

function renderEditor() {
  const ed = $("#editor");
  const p = SCAN.pages[SCAN.current];
  if (!p) { ed.classList.add("hidden"); ed.innerHTML = ""; return; }
  ed.classList.remove("hidden");
  const i = SCAN.current, last = SCAN.pages.length - 1;
  ed.innerHTML = `<div class="row"><h2 style="margin:0">Page ${i + 1}</h2>
      <span class="muted">${p.auto ? "Bords détectés. Faites glisser un coin pour l'ajuster." : "Bords non détectés : placez les 4 coins sur ceux de la feuille."}</span></div>
    <div class="crop"><img src="${p.url}" alt="Photo de la page ${i + 1}" draggable="false">
      <svg viewBox="0 0 ${p.w} ${p.h}" preserveAspectRatio="none" id="crop-svg">
        <path class="shade" fill-rule="evenodd" d=""></path><polygon class="quad" points=""></polygon>
        ${p.corners.map((_, k) => `<circle class="handle" data-k="${k}"></circle>`).join("")}
      </svg></div>
    <div class="row">
      <button class="btn sm" type="button" data-a="auto">Détecter les bords</button>
      <button class="btn sm" type="button" data-a="full">Page entière</button>
      <button class="btn sm" type="button" data-a="rl">Pivoter à gauche</button>
      <button class="btn sm" type="button" data-a="rr">Pivoter à droite</button>
      <span class="spacer"></span>
      <button class="btn sm" type="button" data-a="left" ${i === 0 ? "disabled" : ""}>Placer avant</button>
      <button class="btn sm" type="button" data-a="right" ${i === last ? "disabled" : ""}>Placer après</button>
      <button class="btn sm danger" type="button" data-a="del">Supprimer la page</button></div>
    ${p.rotation ? `<p class="muted">La page sera pivotée de ${p.rotation}° dans le PDF.</p>` : ""}`;
  const svg = $("#crop-svg");
  const draw = () => {
    const pts = p.corners.map(([x, y]) => [x * p.w, y * p.h]);
    svg.querySelector(".quad").setAttribute("points", pts.map((q) => q.join(",")).join(" "));
    svg.querySelector(".shade").setAttribute("d", `M0 0H${p.w}V${p.h}H0Z M${pts.map((q) => q.join(" ")).join(" L")} Z`);
    // Rayon fixe à l'écran (doigt : 16 px, souris : 10 px), quelle que soit la résolution de la photo
    const scale = p.w / (svg.getBoundingClientRect().width || p.w);
    const r = (matchMedia("(pointer: coarse)").matches ? 16 : 10) * scale;
    svg.querySelectorAll(".handle").forEach((c) => { const [x, y] = pts[+c.dataset.k]; c.setAttribute("cx", x); c.setAttribute("cy", y); c.setAttribute("r", r); });
  };
  draw();
  $("#editor img").onload = draw;
  svg.querySelectorAll(".handle").forEach((c) => {
    c.onpointerdown = (e) => {
      e.preventDefault(); c.setPointerCapture(e.pointerId);
      const k = +c.dataset.k;
      c.onpointermove = (ev) => {
        const r = svg.getBoundingClientRect();
        const nx = Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)), ny = Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height));
        const next = p.corners.map((q, j) => (j === k ? [nx, ny] : q));
        if (convex(next)) { p.corners = next; draw(); }
      };
      c.onpointerup = c.onpointercancel = () => { c.onpointermove = null; };
    };
  });
  ed.querySelectorAll("[data-a]").forEach((b) => (b.onclick = async () => {
    const a = b.dataset.a;
    if (a === "full") p.corners = FULL();
    else if (a === "auto") {
      const found = detectCorners(await loadImage(p.url));
      if (found) { p.corners = found; p.auto = true; } else toast("Feuille non détectée : placez les coins à la main", true);
    } else if (a === "rl") p.rotation = (p.rotation + 270) % 360;
    else if (a === "rr") p.rotation = (p.rotation + 90) % 360;
    else if (a === "left" || a === "right") {
      const j = a === "left" ? i - 1 : i + 1;
      [SCAN.pages[i], SCAN.pages[j]] = [SCAN.pages[j], SCAN.pages[i]]; SCAN.current = j;
    } else if (a === "del") { URL.revokeObjectURL(p.url); SCAN.pages.splice(i, 1); SCAN.current = Math.min(i, SCAN.pages.length - 1); }
    renderScan();
  }));
}

/* ------------------------------------------------------------------ Échéances */
function deadlineList(items) {
  if (!items.length) return '<p class="empty">Aucune échéance sur la période.</p>';
  return `<table><tbody>${items.map((i) => `<tr class="click" data-id="${esc(i.document.id)}">
    <td>${i.kind === "VALIDITY" ? dueChip(i.due_date)
      : `<span class="due ${i.days_left <= 0 ? "late" : "later"}">${i.days_left <= 0 ? "DUA échue" : `DUA dans ${i.days_left} j`}</span>`}</td>
    <td><span class="ref">${esc(i.document.reference)}</span><div><strong>${esc(i.document.title)}</strong></div></td>
    <td class="muted">${fmtDate(i.due_date)}</td></tr>`).join("")}</tbody></table>`;
}

VIEWS.deadlines = async () => {
  $("#main").innerHTML = `<h1>Échéances</h1>
    <p class="lede">Documents qui deviennent obsolètes (fin de validité) ou dont la durée de conservation (DUA) arrive à son terme.
      Les personnes concernées reçoivent une notification 90, 30 et 7 jours avant, puis le jour même.</p>
    <div class="card"><div class="row">
      <label class="row" style="font-weight:600">Afficher les
        <select id="hz" style="width:auto"><option value="30">30 prochains jours</option><option value="90" selected>90 prochains jours</option>
          <option value="180">6 prochains mois</option><option value="365">12 prochains mois</option></select></label>
      <label class="row" style="font-weight:600">Type
        <select id="kd" style="width:auto"><option value="">Tous</option><option value="VALIDITY">Fin de validité</option><option value="RETENTION">Fin de DUA</option></select></label>
      <span class="spacer"></span>
      ${can("admin:jobs") ? '<button class="btn rose" id="run-alerts">Envoyer les alertes maintenant</button>' : ""}
    </div><div id="dl" style="margin-top:12px"></div></div>`;
  const load = async () => {
    const items = (await api(`/api/obsolescence/upcoming?days=${$("#hz").value}`)).filter((i) => !$("#kd").value || i.kind === $("#kd").value);
    $("#dl").innerHTML = items.length ? `<table><thead><tr><th>Échéance</th><th>Document</th><th>Motif</th><th>Rubrique</th><th>Exemplaire papier</th></tr></thead><tbody>
      ${items.map((i) => `<tr class="click" data-id="${esc(i.document.id)}">
        <td>${i.kind === "VALIDITY" ? dueChip(i.due_date) : `<span class="due ${i.days_left <= 0 ? "late" : i.days_left <= 30 ? "soon" : "later"}">${i.days_left <= 0 ? "Échue" : `Dans ${i.days_left} j`}</span>`}
          <div class="muted">${fmtDate(i.due_date)}</div></td>
        <td><span class="ref">${esc(i.document.reference)}</span><div><strong>${esc(i.document.title)}</strong></div><div class="muted">${esc(i.document.author)}</div></td>
        <td>${i.kind === "VALIDITY" ? "Fin de validité" : `Fin de DUA, puis ${i.document.final_disposition === "ARCHIVE" ? "archivage définitif" : "destruction"}`}</td>
        <td>${i.document.classification ? `<span class="ref">${esc(i.document.classification.code)}</span>` : '<span class="muted">—</span>'}</td>
        <td>${i.document.shelf_location ? esc(i.document.shelf_location.path) : '<span class="muted">—</span>'}</td></tr>`).join("")}</tbody></table>`
      : '<p class="empty">Aucune échéance sur cette période.</p>';
    bindRows($("#dl"));
  };
  $("#hz").onchange = load; $("#kd").onchange = load;
  if ($("#run-alerts")) $("#run-alerts").onclick = async () => {
    try { const r = await api("/api/notifications/run", { method: "POST" }); toast(`${r.created} alerte(s) envoyée(s)`); refreshBell(); }
    catch (err) { toast(err.message, true); }
  };
  await load();
};

/* ------------------------------------------------------------------ Rayonnage */
VIEWS.shelving = async (selected = null) => {
  const [tree, flat] = await Promise.all([api("/api/shelving"), api("/api/shelving/flat")]);
  S.shelves = flat;
  const manage = can("shelving:manage");
  const meter = (n) => n.capacity ? `<span class="meter ${n.documents >= n.capacity ? "full" : ""}"><i style="width:${Math.min(100, n.documents / n.capacity * 100)}%"></i></span>
    <span class="muted">${n.documents}/${n.capacity}</span>` : `<span class="muted">${n.total_documents} doc.</span>`;
  // Les boîtes (feuilles) d'un niveau sont dessinées posées sur une tablette ; les autres niveaux restent en arbre.
  const render = (nodes) => nodes.map((n) => {
    const boxes = n.children.filter((c) => !c.children.length && c.kind === "BOITE");
    const others = n.children.filter((c) => !boxes.includes(c));
    return `<div class="${n.kind === "SITE" || n.kind === "SALLE" ? "shelf-site" : ""}">
      <div class="shelf-head"><span class="kind">${KINDS[n.kind]}</span><span class="ref">${esc(n.code)}</span>
        <strong>${esc(n.label)}</strong>${meter(n)}
        <button class="btn sm ghost" data-loc="${n.id}">Voir le contenu</button></div>
      ${boxes.length ? `<div class="shelf-plank">${boxes.map((b) => {
        const pct = b.capacity ? Math.min(100, b.documents / b.capacity * 100) : Math.min(100, b.documents * 10);
        return `<button class="box ${b.capacity && b.documents >= b.capacity ? "full" : ""} ${selected === b.id ? "selected" : ""}" data-loc="${b.id}"
          title="${esc(b.path)}"><span class="fill" style="height:${pct}%"></span>
          <span class="code">${esc(b.code)}</span><span class="n">${b.documents}${b.capacity ? ` / ${b.capacity}` : ""} doc.</span></button>`; }).join("")}</div>` : ""}
      ${others.length ? `<div class="shelf-node">${render(others)}</div>` : ""}</div>`;
  }).join("");
  const opts = `<option value="">(aucun : niveau racine)</option>` + flat.map((l) => `<option value="${l.id}">${esc(l.path)}</option>`).join("");
  $("#main").innerHTML = `<h1>Rayonnage</h1>
    <p class="lede">Où se trouve chaque exemplaire papier : site, salle, rayonnage, travée, tablette, boîte.
      Rangez un document depuis sa fiche ; la jauge indique le remplissage des boîtes.</p>
    <div class="grid split">
      <div class="card">${tree.length ? render(tree) : `<p class="empty">Aucun emplacement pour le moment.${manage ? " Commencez par créer une salle." : ""}</p>`}</div>
      <div class="sticky">
        <div class="card" id="loc-docs"><h2>Contenu</h2><p class="muted">Sélectionnez un emplacement ou une boîte.</p></div>
        ${manage ? `<form id="sh" class="card grid"><h2>Nouvel emplacement</h2>
          <div class="grid g2"><label>Niveau<select name="kind">${Object.entries(KINDS).map(([k, v]) => `<option value="${k}" ${k === "BOITE" ? "selected" : ""}>${v}</option>`).join("")}</select></label>
          <label>Code *<input name="code" required placeholder="MAG1-R03-B015"></label></div>
          <label>Libellé *<input name="label" required placeholder="Boîte 15"></label>
          <label>Dans<select name="parent_id">${opts}</select></label>
          <label>Capacité <small>nombre maximum de documents, facultatif</small><input type="number" min="1" name="capacity"></label>
          <button class="btn primary">Créer l'emplacement</button></form>` : ""}
      </div>
    </div>`;
  const showLoc = async (id) => {
    const loc = flat.find((l) => l.id === id);
    const docs = await api(`/api/shelving/${id}/documents`);
    $("#loc-docs").innerHTML = `<div class="row"><h2 style="margin:0">${esc(loc.label)}</h2><span class="spacer"></span>
        ${manage ? `<button class="btn sm danger" id="del-loc">Supprimer</button>` : ""}</div>
      <p class="muted">${esc(loc.path)}</p>
      ${docs.length ? `<table><tbody>${docs.map((d) => `<tr class="click" data-id="${esc(d.id)}"><td><span class="ref">${esc(d.reference)}</span>
        <div><strong>${esc(d.title)}</strong></div>${d.physical_ref ? `<div class="muted">${esc(d.physical_ref)}</div>` : ""}</td>
        <td>${badge(d.status)}</td></tr>`).join("")}</tbody></table>` : '<p class="empty">Aucun document rangé directement ici.</p>'}`;
    bindRows($("#loc-docs"));
    if ($("#del-loc")) $("#del-loc").onclick = async () => {
      if (!confirm(`Supprimer l'emplacement ${loc.code} ?`)) return;
      try { await api(`/api/shelving/${id}`, { method: "DELETE" }); toast("Emplacement supprimé"); VIEWS.shelving(); }
      catch (err) { toast(err.message, true); }
    };
    $("#main").querySelectorAll(".box").forEach((b) => b.classList.toggle("selected", +b.dataset.loc === id));
  };
  $("#main").querySelectorAll("[data-loc]").forEach((b) => (b.onclick = () => showLoc(+b.dataset.loc).catch((e) => toast(e.message, true))));
  if (selected) showLoc(selected);
  if ($("#sh")) $("#sh").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      const l = await api("/api/shelving", { method: "POST", json: { code: f.get("code"), label: f.get("label"), kind: f.get("kind"),
        parent_id: f.get("parent_id") ? +f.get("parent_id") : null, capacity: f.get("capacity") ? +f.get("capacity") : null } });
      toast(`Emplacement ${l.code} créé`); VIEWS.shelving(l.id);
    } catch (err) { toast(err.message, true); }
  };
};

/* ------------------------------------------------------------------ Fiche document */
async function openDoc(id, tab = "meta") {
  const d = await api(`/api/documents/${id}`);
  if (can("shelving:manage") && tab === "meta") S.shelves = await api("/api/shelving/flat").catch(() => []);
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
      <dt>Fin de validité</dt><dd>${d.valid_until ? `${fmtDate(d.valid_until)} ${docOpen(d) ? dueChip(d.valid_until) : ""}` : "—"}</dd>
      <dt>Exemplaire papier</dt><dd>${d.shelf_location ? `<span class="ref">${esc(d.shelf_location.code)}</span> ${esc(d.shelf_location.path)}${d.physical_ref ? ` (${esc(d.physical_ref)})` : ""}` : '<span class="muted">Non rangé</span>'}</dd>
      <dt>Source</dt><dd>${esc(d.source)}</dd><dt>Description</dt><dd>${esc(d.description) || "—"}</dd>
      ${Object.entries(d.extra).map(([k, val]) => `<dt>${esc(k)}</dt><dd>${esc(val)}</dd>`).join("")}
      ${d.current_version ? `<dt>SHA-256</dt><dd class="mono">${esc(d.current_version.sha256)}</dd>
        <dt>Format pérenne</dt><dd>${esc(d.current_version.archival_format || "—")} · conversion ${esc(d.current_version.conversion_status)}${d.current_version.ocr_applied ? " · OCR" : ""}</dd>` : ""}
    </dl>
    ${editable ? `<form id="mf" class="grid" style="margin-top:14px"><h3>Modifier (brouillon)</h3>
      <label>Titre<input name="title" value="${esc(d.title)}"></label>
      <div class="grid g2"><label>Auteur<input name="author" value="${esc(d.author)}"></label><label>Type<input name="doc_type" value="${esc(d.doc_type)}"></label></div>
      <label>Mots-clés<input name="keywords" value="${esc(d.keywords.join(", "))}"></label>
      <div class="grid g2"><label>Rubrique<select name="classification_id">${planOptions(d.classification?.id)}</select></label>
      <label>Fin de validité<input type="date" name="valid_until" value="${esc(d.valid_until || "")}"></label></div>
      <button class="btn">Enregistrer</button></form>` : ""}
    ${can("shelving:manage") && d.status !== "DESTROYED" ? `<form id="lf" class="grid sub"><h3>Ranger l'exemplaire papier</h3>
      <div class="grid g2"><label>Emplacement<select name="shelf_location_id"><option value="">Non rangé</option>
        ${(S.shelves || []).map((l) => `<option value="${l.id}" ${d.shelf_location?.id === l.id ? "selected" : ""}>${esc(l.path)}</option>`).join("")}</select></label>
      <label>Repère dans l'emplacement <small>liasse, chemise…</small><input name="physical_ref" maxlength="100" value="${esc(d.physical_ref || "")}"></label></div>
      <div class="row"><button class="btn">Ranger</button>${(S.shelves || []).length ? "" : '<span class="muted">Créez d\'abord des emplacements dans Rayonnage.</span>'}</div></form>` : ""}`;
    if ($("#lf")) $("#lf").onsubmit = async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      try {
        await api(`/api/documents/${d.id}/location`, { method: "PUT", json: {
          shelf_location_id: f.get("shelf_location_id") ? +f.get("shelf_location_id") : null, physical_ref: f.get("physical_ref") } });
        toast(f.get("shelf_location_id") ? "Exemplaire rangé" : "Exemplaire retiré du rayonnage"); openDoc(d.id);
      } catch (err) { toast(err.message, true); }
    };
    if ($("#mf")) $("#mf").onsubmit = async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      try {
        await api(`/api/documents/${d.id}`, { method: "PATCH", json: { title: f.get("title"), author: f.get("author"),
          doc_type: f.get("doc_type"), valid_until: f.get("valid_until") || null, keywords: f.get("keywords").split(",").map((k) => k.trim()).filter(Boolean),
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
