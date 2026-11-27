/* =========================================================
   Test Case Generator — Frontend (Vanilla JS, 외부 라이브러리 없음)
   ========================================================= */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ } },
  };

  const ICON = {
    ok: '<svg class="ic" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 9.8"/></svg>',
    err: '<svg class="ic" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5h.01"/></svg>',
    warn: '<svg class="ic" viewBox="0 0 24 24"><path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17h.01"/></svg>',
    eye: '<svg class="ic" viewBox="0 0 24 24"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
    trash: '<svg class="ic" viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg>',
  };
  const STATUS_COLOR = { "성공": "var(--ok)", "실패": "var(--bad)", "보류": "var(--warn)", "미실행": "var(--idle)" };
  const PRI_ORDER = { "높음": 0, "중간": 1, "낮음": 2 };
  const STATUS_ORDER = { "실패": 0, "보류": 1, "미실행": 2, "성공": 3 };
  const SRC_TYPE = { "요구사항": ["REQ", "요구"], "XML": ["XML", "XML"], "SQL": ["SQL", "SQL"], "Java": ["JAVA", "Java"], "변경감지": ["CHG", "변경"] };

  const EXAMPLE_REQ = `사용자가 신청기간과 신청상태를 입력하면 해당 조건에 맞는 제출내역을 조회한다.
시작일과 종료일은 필수이며, 조회 결과가 없는 경우 '조회된 내역이 없습니다' 메시지를 표시한다.
조회 기간은 최대 3개월을 초과할 수 없다.
비고는 최대 200자 이내로 입력한다.
관리자만 제출 내역을 삭제할 수 있다.`;

  const S = {
    meta: null, projects: [], project: null, dirty: false, tab: "inputs", job: null, poll: null,
    filter: { q: "", status: "", category: "", priority: "", feature: "", review: false },
    sort: { key: null, dir: 1 }, selected: new Set(), drawer: null, drawerDirty: false, lastErrors: [],
  };

  // ------------------------------------------------------------------ API
  async function api(method, url, body) {
    let res;
    try {
      res = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
    } catch (e) {
      throw new Error("서버에 연결할 수 없습니다. 프로그램(run.py)이 실행 중인지 확인하세요.");
    }
    let j;
    try { j = await res.json(); } catch { throw new Error(`서버 응답을 해석할 수 없습니다 (HTTP ${res.status})`); }
    if (!j.ok) throw new Error(j.error || "요청을 처리하지 못했습니다.");
    return j.data;
  }
  const guard = (fn) => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message, "err"); } };

  // ------------------------------------------------------------------ UI primitives
  function toast(msg, type = "ok", ms = 3200) {
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.innerHTML = (type === "err" ? ICON.err : ICON.ok) + `<div>${esc(msg)}</div>`;
    $("#toasts").appendChild(el);
    setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 260); }, type === "err" ? Math.max(ms, 5200) : ms);
  }

  let modalResolve = null;
  function modal({ title, body, buttons = [], wide = false, onOpen }) {
    return new Promise((resolve) => {
      modalResolve = resolve;
      $("#modalTitle").textContent = title;
      $("#modalBody").innerHTML = body;
      $("#modal .modal").classList.toggle("wide", wide);
      const foot = $("#modalFoot");
      foot.innerHTML = "";
      foot.classList.toggle("hidden", !buttons.length);
      buttons.forEach((b) => {
        const el = document.createElement("button");
        el.className = `btn ${b.cls || ""}`;
        el.textContent = b.label;
        el.onclick = async () => {
          if (b.onClick) { const r = await b.onClick(); if (r === false) return; closeModal(b.value ?? r); }
          else closeModal(b.value);
        };
        foot.appendChild(el);
      });
      $("#modal").classList.remove("hidden");
      onOpen && onOpen();
    });
  }
  function closeModal(v) {
    $("#modal").classList.add("hidden");
    if (modalResolve) { const r = modalResolve; modalResolve = null; r(v); }
  }
  const confirmBox = (title, msg, okLabel = "확인", danger = false) => modal({
    title, body: `<p style="margin:4px 0 8px;line-height:1.65">${msg}</p>`,
    buttons: [{ label: "취소", value: false }, { label: okLabel, cls: danger ? "btn-danger" : "btn-brand", value: true }],
  });

  // ------------------------------------------------------------------ Projects
  async function loadProjects() {
    S.projects = await api("GET", "/api/projects");
    renderProjects();
  }
  function renderProjects() {
    const q = $("#projectSearch").value.trim().toLowerCase();
    const list = S.projects.filter((p) => !q || p.name.toLowerCase().includes(q) || (p.description || "").toLowerCase().includes(q));
    $("#projectCount").textContent = S.projects.length ? `· ${S.projects.length}` : "";
    const nav = $("#projectList");
    if (!list.length) {
      nav.innerHTML = `<div class="side-empty">${S.projects.length ? "검색 결과가 없습니다." : "아직 프로젝트가 없습니다.<br>화면 또는 업무 단위로 프로젝트를 만들어 보세요."}</div>`;
      return;
    }
    nav.innerHTML = list.map((p) => `
      <button class="proj-item ${S.project && S.project.id === p.id ? "active" : ""}" data-id="${p.id}" title="${esc(p.description || p.name)}">
        <div class="proj-name">${esc(p.name)}</div>
        <div class="proj-meta">
          <span class="pill-mini">${p.caseCount}건</span>
          ${p.passCount ? `<span class="pm-pass">✓ ${p.passCount}</span>` : ""}
          ${p.failCount ? `<span class="pm-fail">✕ ${p.failCount}</span>` : ""}
          <span>${esc((p.updatedAt || "").slice(5, 16))}</span>
        </div>
      </button>`).join("");
  }

  async function openProject(id, { force = false } = {}) {
    if (!force && S.dirty && S.project && S.project.id !== id) {
      const ok = await confirmBox("저장되지 않은 변경", "현재 프로젝트에 저장되지 않은 변경 사항이 있습니다. 저장하지 않고 이동할까요?", "이동");
      if (!ok) return;
    }
    stopPoll();
    const p = await api("GET", `/api/projects/${id}`);
    S.project = p;
    S.dirty = false;
    S.selected.clear();
    S.job = null;
    store.set("tcgen.last", id);
    $("#welcome").classList.add("hidden");
    $("#workspace").classList.remove("hidden");
    $("#analyzeResult").classList.add("hidden");
    $("#progressWrap").classList.add("hidden");
    $("#logBox").classList.add("hidden");
    renderAll();
    renderProjects();
  }

  function renderAll() {
    const p = S.project;
    $("#projName").value = p.name;
    $("#projDesc").value = p.description || "";
    $("#reqText").value = p.requirementText || "";
    updateReqCount();
    renderMeta();
    setDirty(false);
    renderFiles();
    renderCases();
    renderReport();
    switchTab(S.tab);
  }

  function renderMeta() {
    const p = S.project;
    const a = p.analysis;
    $("#projMeta").innerHTML = `
      <span>생성 ${esc(p.createdAt?.slice(0, 16))}</span>
      <span>수정 ${esc(p.updatedAt?.slice(0, 16))}</span>
      <span>${a ? `최근 분석 ${esc(a.lastRunAt.slice(0, 16))}` : "아직 분석하지 않음"}</span>`;
    const on = p.files.filter((f) => f.enabled).length;
    $("#tabBadgeFiles").textContent = p.files.length ? `${on}/${p.files.length}` : "";
    $("#tabBadgeCases").textContent = p.testCases.length || "";
  }

  function setDirty(v) {
    S.dirty = v;
    $("#dirtyFlag").classList.toggle("hidden", !v);
  }

  async function saveProject({ silent = false } = {}) {
    const p = S.project;
    const name = $("#projName").value.trim();
    if (!name) { toast("프로젝트명을 입력해 주세요.", "err"); $("#projName").focus(); throw new Error("no name"); }
    const saved = await api("PUT", `/api/projects/${p.id}`, { name, description: $("#projDesc").value, requirementText: $("#reqText").value });
    Object.assign(S.project, { name: saved.name, description: saved.description, requirementText: saved.requirementText, updatedAt: saved.updatedAt });
    setDirty(false);
    renderMeta();
    await loadProjects();
    if (!silent) toast("프로젝트를 저장했습니다.");
  }

  async function newProjectDialog() {
    let created = null;
    await modal({
      title: "새 프로젝트",
      body: `
        <label class="field"><span>프로젝트명 *</span><input id="npName" maxlength="100" placeholder="예) 제출내역 조회, 부인 신청, 배치 대상자 추출"></label>
        <label class="field"><span>설명</span><textarea id="npDesc" rows="3" placeholder="화면 또는 업무 단위 설명"></textarea></label>
        <div class="muted sm" id="npErr" style="color:var(--bad)"></div>`,
      onOpen: () => { setTimeout(() => $("#npName").focus(), 30); $("#npName").onkeydown = (e) => { if (e.key === "Enter") $("#modalFoot .btn-brand").click(); }; },
      buttons: [
        { label: "취소", value: null },
        {
          label: "만들기", cls: "btn-brand", onClick: async () => {
            try {
              created = await api("POST", "/api/projects", { name: $("#npName").value, description: $("#npDesc").value });
              return created;
            } catch (e) { $("#npErr").textContent = e.message; return false; }
          },
        },
      ],
    });
    if (created) {
      await loadProjects();
      S.tab = "inputs";
      await openProject(created.id, { force: true });
      toast(`'${created.name}' 프로젝트를 만들었습니다.`);
    }
  }

  async function createSampleProject() {
    let name = "제출내역 조회 (샘플)", i = 2;
    const names = new Set(S.projects.map((p) => p.name));
    while (names.has(name)) name = `제출내역 조회 (샘플 ${i++})`;
    const p = await api("POST", "/api/projects", { name, description: "WebSquare5 화면 · MyBatis Mapper · SQL · Java 서비스 · 요구사항 문서 샘플" });
    await api("POST", `/api/projects/${p.id}/samples`, {});
    await loadProjects();
    S.tab = "inputs";
    await openProject(p.id, { force: true });
    toast("샘플 자료를 불러왔습니다. 분석을 시작합니다.");
    await startAnalysis({ jumpToCases: true });
  }

  async function deleteProject() {
    const p = S.project;
    const ok = await confirmBox("프로젝트 삭제", `<b>${esc(p.name)}</b> 프로젝트와 테스트 케이스 ${p.testCases.length}건, 업로드한 파일 사본이 모두 삭제됩니다.<br>이 작업은 되돌릴 수 없습니다.`, "삭제", true);
    if (!ok) return;
    await api("DELETE", `/api/projects/${p.id}`);
    S.project = null;
    S.dirty = false;
    store.set("tcgen.last", null);
    $("#workspace").classList.add("hidden");
    $("#welcome").classList.remove("hidden");
    await loadProjects();
    toast("프로젝트를 삭제했습니다.");
  }

  // ------------------------------------------------------------------ Tabs
  function switchTab(tab) {
    S.tab = tab;
    $$("#tabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
    ["inputs", "cases", "report"].forEach((t) => $(`#panel-${t}`).classList.toggle("hidden", t !== tab));
  }

  // ------------------------------------------------------------------ Files
  const fmtSize = (n) => n < 1024 ? `${n}B` : n < 1048576 ? `${(n / 1024).toFixed(1)}KB` : `${(n / 1048576).toFixed(1)}MB`;
  function fileReport(name) {
    const a = S.project.analysis;
    return a && (a.files || []).find((f) => f.file === name);
  }
  function renderFiles() {
    const files = S.project.files;
    const ul = $("#fileList");
    $("#fileToolbar").classList.toggle("hidden", !files.length);
    const on = files.filter((f) => f.enabled).length;
    $("#fileSummary").textContent = `${files.length}개 파일 · 분석 포함 ${on}개`;
    if (!files.length) {
      ul.innerHTML = `<li class="file-empty">업로드된 파일이 없습니다.</li>`;
      return;
    }
    ul.innerHTML = files.map((f) => {
      const rep = fileReport(f.name);
      let st = "";
      if (f.analyzedHash && f.analyzedHash !== f.hash) st = `<span class="chg">● 변경됨 (재분석 필요)</span>`;
      else if (rep && rep.ok) st = `<span class="okc">✓ 분석 요소 ${rep.facts}건</span>`;
      else if (rep && !rep.ok) st = `<span class="err">✕ 분석 오류${rep.error?.line ? ` (L${rep.error.line})` : ""}</span>`;
      return `
      <li class="file-item ${f.enabled ? "" : "off"}" data-id="${f.id}">
        <span class="chip t-${f.type}">${esc(typeShort(f.type))}</span>
        <div class="file-main">
          <div class="file-name" title="${esc(f.name)}">${esc(f.name)}</div>
          <div class="file-sub"><span>${esc(f.typeLabel)}</span><span>${fmtSize(f.size)}</span>${st}</div>
        </div>
        <label class="switch" title="${f.enabled ? "분석에 포함" : "분석에서 제외"}"><input type="checkbox" data-act="toggle" ${f.enabled ? "checked" : ""}><span></span></label>
        <button class="icon-btn" data-act="preview" title="내용 보기">${ICON.eye}</button>
        <button class="icon-btn" data-act="remove" title="목록에서 삭제">${ICON.trash}</button>
      </li>`;
    }).join("");
  }
  const typeShort = (t) => ({ REQ: "TXT", EXCEL: "XLSX", XML: "XML", MAPPER: "MAPPER", SQL: "SQL", JAVA: "JAVA" }[t] || t);

  function toB64(buf) {
    const bytes = new Uint8Array(buf);
    let s = "";
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(s);
  }
  async function uploadFiles(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    const supported = new Set(S.meta.supported);
    const payload = [], rejected = [];
    for (const f of files) {
      const ext = f.name.includes(".") ? f.name.slice(f.name.lastIndexOf(".")).toLowerCase() : "";
      if (!supported.has(ext)) { rejected.push(`${f.name}: 지원하지 않는 형식`); continue; }
      if (f.size > 20 * 1024 * 1024) { rejected.push(`${f.name}: 20MB 초과`); continue; }
      payload.push({ name: f.name, content: toB64(await f.arrayBuffer()) });
    }
    rejected.forEach((r) => toast(r, "err"));
    if (!payload.length) return;
    const res = await api("POST", `/api/projects/${S.project.id}/files`, { files: payload });
    S.project.files = res.files;
    res.rejected.forEach((r) => toast(`${r.name}: ${r.reason}`, "err"));
    const replaced = res.added.filter((a) => a.replaced).length;
    if (res.added.length) toast(`${res.added.length}개 파일을 추가했습니다${replaced ? ` (${replaced}개는 같은 이름 파일 교체)` : ""}.`);
    renderFiles();
    renderMeta();
    loadProjects();
  }

  async function previewFile(fid, hlLine) {
    const f = S.project.files.find((x) => x.id === fid);
    const d = await api("GET", `/api/projects/${S.project.id}/files/${fid}`);
    const rep = fileReport(f.name);
    const errLine = hlLine || (rep && !rep.ok && rep.error?.line);
    const lines = (d.text || "").split("\n");
    const body = d.error ? `<div class="err-list"><li>${ICON.err}${esc(d.error)}</li></div>` : `
      <div class="muted sm" style="margin-bottom:8px">${esc(f.typeLabel)} · ${esc(d.encoding || "")} · ${lines.length.toLocaleString()}줄 ${d.truncated ? "· 앞부분만 표시" : ""} · 읽기 전용</div>
      <pre class="code-view">${lines.map((l, i) => `<span class="ln${errLine && i + 1 === errLine ? " hl" : ""}" ${errLine && i + 1 === errLine ? 'id="hlLine"' : ""}>${esc(l) || " "}</span>`).join("")}</pre>`;
    modal({ title: f.name, body, wide: true, buttons: [{ label: "닫기", value: null }], onOpen: () => { const h = $("#hlLine"); h && h.scrollIntoView({ block: "center" }); } });
  }

  // ------------------------------------------------------------------ Analysis
  async function startAnalysis({ jumpToCases = false } = {}) {
    if (S.dirty) await saveProject({ silent: true });
    const p = S.project;
    if (!p.requirementText.trim() && !p.files.some((f) => f.enabled)) {
      showAnalyzeResult({ status: "error", errors: [{ message: "분석할 자료가 없습니다. 요구사항을 입력하거나 파일을 업로드한 뒤 분석 대상으로 포함해 주세요." }], logs: [] });
      return;
    }
    const job = await api("POST", `/api/projects/${p.id}/analyze`);
    S.job = job;
    $("#btnAnalyze").disabled = true;
    $("#btnCancel").disabled = false;
    $("#progressWrap").classList.remove("hidden");
    $("#analyzeResult").classList.add("hidden");
    $("#progressBar").classList.add("running");
    updateProgress(job);
    stopPoll();
    S.poll = setInterval(async () => {
      try {
        const j = await api("GET", `/api/jobs/${job.id}`);
        S.job = j;
        updateProgress(j);
        if (!["queued", "running"].includes(j.status)) { stopPoll(); await finishAnalysis(j, jumpToCases); }
      } catch (e) { stopPoll(); toast(e.message, "err"); resetAnalyzeButtons(); }
    }, 350);
  }
  function stopPoll() { if (S.poll) { clearInterval(S.poll); S.poll = null; } }
  function resetAnalyzeButtons() {
    $("#btnAnalyze").disabled = false;
    $("#btnCancel").disabled = true;
    $("#progressBar").classList.remove("running");
  }
  function updateProgress(j) {
    $("#progressBar").style.width = `${j.progress}%`;
    $("#progressStep").textContent = j.step;
    $("#progressPct").textContent = `${j.progress}%`;
    $("#logText").textContent = (j.logs || []).join("\n");
    $("#logBox").classList.toggle("hidden", !(j.logs || []).length);
  }
  async function finishAnalysis(j, jumpToCases) {
    resetAnalyzeButtons();
    if (j.status === "done") {
      const p = await api("GET", `/api/projects/${S.project.id}`);
      S.project = p;
      renderFiles(); renderCases(); renderReport(); renderMeta(); loadProjects();
      toast(`분석 완료 — 테스트 케이스 ${j.stats.total}건 (신규 ${j.stats.added}건)`);
      if (jumpToCases) switchTab("cases");
    } else if (j.status === "cancelled") {
      toast("분석을 취소했습니다. 프로젝트는 변경되지 않았습니다.");
    }
    showAnalyzeResult(j);
  }
  function showAnalyzeResult(j) {
    const box = $("#analyzeResult");
    box.classList.remove("hidden");
    let html = "";
    if (j.status === "done") {
      const s = j.stats;
      html += `<div class="result-strip">${ICON.ok}<b><span class="rs-num">${s.total}</span>건의 테스트 케이스</b>
        <span class="kv">생성 ${s.generated}</span><span class="kv">신규 ${s.added}</span><span class="kv">갱신 ${s.updated}</span>
        <span class="kv">수정 보존 ${s.kept}</span><span class="kv">삭제 ${s.removed}</span>${s.stale ? `<span class="kv">근거 소실 ${s.stale}</span>` : ""}
        <div class="spacer"></div><button class="btn btn-sm btn-brand" id="btnGoCases">테스트 케이스 보기 →</button></div>`;
    } else if (j.status === "cancelled") {
      html += `<div class="result-strip cancel">${ICON.warn}<b>분석이 취소되었습니다.</b> 프로젝트 데이터는 변경되지 않았습니다.</div>`;
    } else if (j.status === "error") {
      html += `<div class="result-strip err">${ICON.err}<b>분석을 완료하지 못했습니다.</b></div>`;
    }
    const errs = (j.errors || []).filter((e) => e.file || j.status === "error");
    const warns = j.warnings || [];
    if (errs.length || warns.length) {
      html += `<ul class="err-list">` + errs.map((e) => {
        const f = e.file && S.project.files.find((x) => x.name === e.file);
        return `<li>${ICON.err}<div><b>${esc(e.file || "분석 오류")}</b> ${e.line ? `<span class="err-loc">라인 ${e.line}${e.column ? `:${e.column}` : ""}</span>` : ""}
          <div>${esc(e.message)}</div>${f ? `<button class="btn btn-ghost btn-sm" data-preview="${f.id}" data-line="${e.line || ""}" style="margin-top:4px;padding-left:0">파일 보기</button>` : ""}</div></li>`;
      }).join("") + warns.slice(0, 8).map((w) => `<li class="warn">${ICON.warn}<div><b>${esc(w.file)}</b> ${w.line ? `<span class="err-loc">라인 ${w.line}</span>` : ""}<div>${esc(w.message)}</div></div></li>`).join("") + `</ul>`;
    }
    box.innerHTML = html;
    const go = $("#btnGoCases");
    if (go) go.onclick = () => switchTab("cases");
  }

  // ------------------------------------------------------------------ Cases
  function catClass(cat) { const i = S.meta.categories.indexOf(cat); return `c${i < 0 ? 9 : i}`; }
  function srcChips(c) {
    const types = [...new Set((c.sources || []).map((s) => s.type))];
    if (!types.length) return `<span class="tag ${c.origin === "manual" ? "manual" : ""}">${c.origin === "manual" ? "수동" : "-"}</span>`;
    return types.map((t) => { const m = SRC_TYPE[t] || ["CHG", t]; return `<span class="chip t-${m[0]}">${esc(m[1])}</span>`; }).join("");
  }

  function filtered() {
    const f = S.filter;
    const q = f.q.trim().toLowerCase();
    let list = S.project.testCases.filter((c) =>
      (!f.status || c.status === f.status) && (!f.category || c.category === f.category) &&
      (!f.priority || c.priority === f.priority) && (!f.feature || c.feature === f.feature) &&
      (!f.review || c.needsReview) &&
      (!q || [c.testId, c.feature, c.scenario, c.expected, c.sourceText, c.note].some((v) => (v || "").toLowerCase().includes(q))));
    const k = S.sort.key;
    if (k) {
      const ord = k === "priority" ? PRI_ORDER : k === "status" ? STATUS_ORDER : null;
      list = list.slice().sort((a, b) => {
        const va = ord ? ord[a[k]] ?? 9 : (a[k] || "");
        const vb = ord ? ord[b[k]] ?? 9 : (b[k] || "");
        return (va < vb ? -1 : va > vb ? 1 : 0) * S.sort.dir;
      });
    }
    return list;
  }

  function renderStats() {
    const cs = S.project.testCases;
    const n = cs.length;
    const cnt = (st) => cs.filter((c) => c.status === st).length;
    const pass = cnt("성공"), fail = cnt("실패"), hold = cnt("보류"), todo = cnt("미실행");
    const review = cs.filter((c) => c.needsReview).length;
    const done = pass + fail;
    const rate = done ? Math.round((pass / done) * 100) : 0;
    const prog = n ? Math.round(((n - todo) / n) * 100) : 0;
    const R = 30, C = 2 * Math.PI * R;
    const seg = (v) => (n ? (v / n) * 100 : 0);
    const card = (label, num, color, status, sub) => `
      <div class="stat ${S.filter.status === status && status ? "on" : ""}" data-status="${status}">
        <div class="stat-label"><span class="stat-dot" style="background:${color}"></span>${label}</div>
        <div class="stat-num">${num}</div><div class="stat-sub">${sub}</div>
      </div>`;
    $("#stats").innerHTML = `
      <div class="stat stat-hero">
        <svg class="ring" viewBox="0 0 76 76">
          <circle class="bg" cx="38" cy="38" r="${R}"/>
          <circle cx="38" cy="38" r="${R}" stroke="url(#rg)" stroke-linecap="round" stroke-dasharray="${C}" stroke-dashoffset="${C * (1 - prog / 100)}" transform="rotate(-90 38 38)"/>
          <defs><linearGradient id="rg"><stop offset="0" stop-color="var(--brand)"/><stop offset="1" stop-color="var(--brand-2)"/></linearGradient></defs>
          <text x="38" y="38">${prog}%</text>
        </svg>
        <div style="flex:1;min-width:0">
          <div class="stat-label">테스트 진행률</div>
          <div class="stat-num" style="font-size:22px">${n - todo} <span class="muted" style="font-size:14px;font-weight:600">/ ${n}건 수행</span></div>
          <div class="stackbar"><span style="width:${seg(pass)}%;background:var(--ok)"></span><span style="width:${seg(fail)}%;background:var(--bad)"></span><span style="width:${seg(hold)}%;background:var(--warn)"></span></div>
          <div class="stat-sub" style="margin-top:6px">성공률(수행 대비) <b style="color:var(--text)">${done ? rate + "%" : "-"}</b></div>
        </div>
      </div>
      ${card("전체", n, "var(--brand)", "", `확인 필요 ${review}건`)}
      ${card("성공", pass, "var(--ok)", "성공", n ? `${Math.round(seg(pass))}%` : "-")}
      ${card("실패", fail, "var(--bad)", "실패", fail ? "클릭하여 실패 건만 보기" : "실패 없음")}
      ${card("보류", hold, "var(--warn)", "보류", n ? `${Math.round(seg(hold))}%` : "-")}
      ${card("미실행", todo, "var(--idle)", "미실행", n ? `${Math.round(seg(todo))}%` : "-")}`;
  }

  function renderFilters() {
    const cs = S.project.testCases;
    const counts = {};
    cs.forEach((c) => { counts[c.status] = (counts[c.status] || 0) + 1; });
    $("#statusSeg").innerHTML = [["", "전체", cs.length], ...S.meta.statuses.map((s) => [s, s, counts[s] || 0])]
      .map(([v, l, n]) => `<button data-v="${v}" class="${S.filter.status === v ? "on" : ""}">${l}<span class="cnt">${n}</span></button>`).join("");
    const fill = (sel, items, all, cur) => { $(sel).innerHTML = `<option value="">${all}</option>` + items.map((i) => `<option ${i === cur ? "selected" : ""}>${esc(i)}</option>`).join(""); };
    const cats = S.meta.categories.filter((c) => cs.some((x) => x.category === c));
    fill("#fCategory", cats, "전체 분류", S.filter.category);
    fill("#fPriority", S.meta.priorities, "전체 중요도", S.filter.priority);
    fill("#fFeature", [...new Set(cs.map((c) => c.feature).filter(Boolean))], "전체 기능", S.filter.feature);
    $("#fReview").checked = S.filter.review;
  }

  function renderCases() {
    if (!S.project) return;
    renderStats();
    renderFilters();
    const list = filtered();
    const valid = new Set(S.project.testCases.map((c) => c.uid));
    [...S.selected].forEach((u) => { if (!valid.has(u)) S.selected.delete(u); });
    const body = $("#casesBody");
    const total = S.project.testCases.length;
    $("#casesEmpty").classList.toggle("hidden", !!list.length);
    $("#casesTable").classList.toggle("hidden", !list.length);
    if (!list.length) {
      $("#casesEmpty").innerHTML = total
        ? `<b>조건에 맞는 테스트 케이스가 없습니다.</b>필터를 변경해 보세요. <button class="btn btn-sm" id="btnResetFilter" style="margin-left:8px">필터 초기화</button>`
        : `<b>아직 테스트 케이스가 없습니다.</b>‘분석 자료’ 탭에서 자료를 입력하고 분석을 실행하거나, 직접 케이스를 추가하세요.`;
      const rb = $("#btnResetFilter");
      if (rb) rb.onclick = () => { S.filter = { q: "", status: "", category: "", priority: "", feature: "", review: false }; $("#caseSearch").value = ""; renderCases(); };
    }
    body.innerHTML = list.map((c) => {
      const tags = [];
      if (c.needsReview) tags.push(`<span class="tag review" title="${esc(c.reviewReason)}">확인 필요</span>`);
      if (c.origin === "manual") tags.push(`<span class="tag manual">수동 작성</span>`);
      else if (c.modified) tags.push(`<span class="tag mod" title="수정 항목: ${esc((c.modifiedFields || []).join(", "))}">개발자 수정</span>`);
      else tags.push(`<span class="tag">자동 생성</span>`);
      if (c.stale) tags.push(`<span class="tag stale" title="재분석 결과에 근거가 없습니다">근거 소실</span>`);
      return `<tr data-uid="${c.uid}" class="st-${esc(c.status)} ${S.selected.has(c.uid) ? "sel" : ""}">
        <td class="col-chk"><input type="checkbox" data-chk ${S.selected.has(c.uid) ? "checked" : ""}></td>
        <td><span class="tid">${esc(c.testId)}</span></td>
        <td class="feature-cell"><span class="feat">${esc(c.feature)}</span></td>
        <td><span class="cat ${catClass(c.category)}">${esc(c.category.replace(" 테스트", ""))}</span></td>
        <td><div class="scn">${esc(c.scenario)}</div><div class="scn-sub">${esc((c.expected || "").split("\n")[0])}</div><div class="tags">${tags.join("")}</div></td>
        <td><span class="pri pri-${esc(c.priority)}">${esc(c.priority)}</span></td>
        <td><select class="st-select s-${esc(c.status)}" data-status>${S.meta.statuses.map((s) => `<option ${s === c.status ? "selected" : ""}>${s}</option>`).join("")}</select></td>
        <td class="src-cell"><div class="src-chips">${srcChips(c)}</div></td>
      </tr>`;
    }).join("");
    $$("#casesTable th.sortable").forEach((th) => {
      th.classList.toggle("sort-asc", S.sort.key === th.dataset.sort && S.sort.dir === 1);
      th.classList.toggle("sort-desc", S.sort.key === th.dataset.sort && S.sort.dir === -1);
    });
    $("#chkAll").checked = list.length > 0 && list.every((c) => S.selected.has(c.uid));
    $("#tableFoot").innerHTML = `<span>${list.length === total ? `전체 ${total}건` : `${list.length}건 표시 / 전체 ${total}건`}</span><span>행을 클릭하면 상세 편집 · 상태는 목록에서 바로 변경할 수 있습니다</span>`;
    renderBulk();
    renderMeta();
  }

  function renderBulk() {
    const n = S.selected.size;
    $("#bulkbar").classList.toggle("hidden", !n);
    $("#bulkCount").textContent = `${n}건 선택`;
  }

  function replaceCase(c) {
    const i = S.project.testCases.findIndex((x) => x.uid === c.uid);
    if (i >= 0) S.project.testCases[i] = c; else S.project.testCases.push(c);
  }

  async function setStatus(uid, status) {
    const c = await api("PUT", `/api/projects/${S.project.id}/testcases/${uid}`, { status });
    replaceCase(c);
    renderCases();
    loadProjects();
  }

  async function bulk(action, value) {
    const uids = [...S.selected];
    if (!uids.length) return;
    if (action === "delete") {
      const ok = await confirmBox("선택 삭제", `선택한 테스트 케이스 ${uids.length}건을 삭제할까요?`, "삭제", true);
      if (!ok) return;
    }
    const r = await api("POST", `/api/projects/${S.project.id}/testcases/bulk`, { action, uids, value });
    S.project = await api("GET", `/api/projects/${S.project.id}`);
    if (action === "delete") S.selected.clear();
    renderCases();
    loadProjects();
    toast(`${r.affected}건 처리했습니다.`);
  }

  // ------------------------------------------------------------------ Export
  async function exportExcel(params = {}) {
    const p = S.project;
    if (S.dirty) await saveProject({ silent: true });
    const qs = new URLSearchParams(params).toString();
    let res;
    try { res = await fetch(`/api/projects/${p.id}/export.xlsx${qs ? "?" + qs : ""}`); }
    catch { throw new Error("서버에 연결할 수 없습니다."); }
    const ct = res.headers.get("Content-Type") || "";
    if (!res.ok || ct.includes("json")) {
      let msg = "Excel 다운로드 중 오류가 발생했습니다.";
      try { msg = (await res.json()).error || msg; } catch { /* ignore */ }
      throw new Error(msg);
    }
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename\*=UTF-8''([^;]+)/);
    const name = m ? decodeURIComponent(m[1]) : "testcases.xlsx";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    toast(`Excel 파일을 내려받았습니다: ${name}`);
  }

  // ------------------------------------------------------------------ Drawer
  const DF = { feature: "#dFeature", category: "#dCategory", scenario: "#dScenario", precondition: "#dPrecondition", inputData: "#dInputData", steps: "#dSteps", expected: "#dExpected", actual: "#dActual", failReason: "#dFailReason", note: "#dNote", tester: "#dTester", executedAt: "#dExecutedAt" };
  let dState = { priority: "중간", status: "미실행" };

  function segButtons(el, items, cur, cls = "") {
    el.innerHTML = items.map((i) => `<button type="button" data-v="${i}" class="${i === cur ? "on" : ""} ${cls ? cls + i : ""}">${i}</button>`).join("");
  }
  function autoGrow(t) { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight + 2, 420) + "px"; }

  function openDrawer(uid) {
    const c = uid ? S.project.testCases.find((x) => x.uid === uid) : null;
    S.drawer = c ? c.uid : "new";
    S.drawerDirty = false;
    const d = c || { testId: "", feature: S.project.analysis?.context?.feature || S.project.name, category: "정상 테스트", priority: "중간", status: "미실행", origin: "manual", sources: [] };
    $("#dTestId").value = d.testId || "";
    $("#dTestId").placeholder = "자동 부여";
    $("#dCategory").innerHTML = S.meta.categories.map((x) => `<option ${x === d.category ? "selected" : ""}>${x}</option>`).join("");
    Object.entries(DF).forEach(([k, sel]) => { if (k !== "category") $(sel).value = d[k] || ""; });
    dState = { priority: d.priority || "중간", status: d.status || "미실행" };
    segButtons($("#dPriority"), S.meta.priorities, dState.priority);
    segButtons($("#dStatus"), S.meta.statuses, dState.status, "v-");
    $("#dFailWrap").classList.toggle("hidden", dState.status !== "실패");
    const badges = [];
    if (!c) badges.push(`<span class="tag manual">새 케이스</span>`);
    else if (c.origin === "manual") badges.push(`<span class="tag manual">수동 작성</span>`);
    else badges.push(c.modified ? `<span class="tag mod">자동 생성 · 개발자 수정</span>` : `<span class="tag">자동 생성</span>`);
    if (c && c.stale) badges.push(`<span class="tag stale">근거 소실</span>`);
    $("#dBadges").innerHTML = badges.join("");
    const mod = new Set(c?.modifiedFields || []);
    Object.entries(DF).forEach(([k, sel]) => $(sel).closest(".field").classList.toggle("mod", mod.has(k)));
    $("#dReview").classList.toggle("hidden", !(c && c.needsReview));
    $("#dReviewReason").textContent = c?.reviewReason || "";
    $("#dResolve").checked = false;
    const srcs = c?.sources || [];
    $("#dSources").innerHTML = srcs.length ? srcs.map((s) => {
      const m = SRC_TYPE[s.type] || ["CHG", s.type];
      return `<li><span class="chip t-${m[0]}">${esc(m[1])}</span><div style="min-width:0"><div class="src-file">${esc(s.file)}${s.line ? ` <span class="muted">· L${s.line}</span>` : ""}</div>${s.detail ? `<div class="src-detail">${esc(s.detail)}</div>` : ""}</div></li>`;
    }).join("") : `<li><span class="muted">${c && c.sourceText ? esc(c.sourceText) : "직접 작성한 테스트 케이스입니다."}</span></li>`;
    $("#dDelete").classList.toggle("hidden", !c);
    $("#dCopy").classList.toggle("hidden", !c);
    $("#drawer").classList.add("open");
    $("#drawer").setAttribute("aria-hidden", "false");
    $("#drawerBackdrop").classList.remove("hidden");
    $("#drawerBody").scrollTop = 0;
    requestAnimationFrame(() => $$("#drawer textarea").forEach(autoGrow));
    setTimeout(() => (c ? $("#dScenario") : $("#dFeature")).focus(), 60);
  }

  async function closeDrawer(force = false) {
    if (!S.drawer) return;
    if (!force && S.drawerDirty) {
      const ok = await confirmBox("변경 사항 취소", "저장하지 않은 변경 사항이 있습니다. 닫을까요?", "닫기");
      if (!ok) return;
    }
    S.drawer = null;
    $("#drawer").classList.remove("open");
    $("#drawer").setAttribute("aria-hidden", "true");
    $("#drawerBackdrop").classList.add("hidden");
  }

  async function saveDrawer() {
    const body = { testId: $("#dTestId").value.trim(), priority: dState.priority, status: dState.status };
    Object.entries(DF).forEach(([k, sel]) => { body[k] = $(sel).value; });
    if (!body.scenario.trim()) { toast("테스트 시나리오를 입력해 주세요.", "err"); $("#dScenario").focus(); return; }
    if ($("#dResolve").checked) body.resolveReview = true;
    let c;
    if (S.drawer === "new") {
      if (!body.testId) delete body.testId;
      c = await api("POST", `/api/projects/${S.project.id}/testcases`, body);
      toast(`${c.testId} 테스트 케이스를 추가했습니다.`);
    } else {
      if (!body.testId) { toast("테스트 ID를 입력해 주세요.", "err"); $("#dTestId").focus(); return; }
      c = await api("PUT", `/api/projects/${S.project.id}/testcases/${S.drawer}`, body);
      toast(`${c.testId} 저장했습니다.`);
    }
    replaceCase(c);
    S.drawerDirty = false;
    renderCases();
    loadProjects();
    closeDrawer(true);
  }

  async function deleteDrawerCase() {
    const c = S.project.testCases.find((x) => x.uid === S.drawer);
    if (!c) return;
    const ok = await confirmBox("테스트 케이스 삭제", `<b>${esc(c.testId)}</b> ${esc(c.scenario)}<br>삭제할까요?`, "삭제", true);
    if (!ok) return;
    await api("DELETE", `/api/projects/${S.project.id}/testcases/${c.uid}`);
    S.project.testCases = S.project.testCases.filter((x) => x.uid !== c.uid);
    S.selected.delete(c.uid);
    closeDrawer(true);
    renderCases();
    loadProjects();
    toast(`${c.testId} 삭제했습니다.`);
  }

  async function copyDrawerCase() {
    const src = S.drawer;
    const c = await api("POST", `/api/projects/${S.project.id}/testcases/${src}/copy`);
    S.project = await api("GET", `/api/projects/${S.project.id}`);
    renderCases();
    toast(`${c.testId}(으)로 복사했습니다.`);
    S.drawerDirty = false;
    openDrawer(c.uid);
  }

  // ------------------------------------------------------------------ Report
  function renderReport() {
    const p = S.project;
    const a = p.analysis;
    const el = $("#reportBody");
    if (!a) {
      el.innerHTML = `<div class="card report-empty"><b>아직 분석 결과가 없습니다.</b><span class="muted">분석을 실행하면 파일별 분석 결과, 추출된 입력 항목, 오류 위치가 여기에 표시됩니다.</span></div>`;
      return;
    }
    const cs = p.testCases;
    const ctx = a.context || {};
    const catCounts = S.meta.categories.map((c) => [c, cs.filter((x) => x.category === c).length]).filter(([, n]) => n);
    const maxCat = Math.max(1, ...catCounts.map(([, n]) => n));
    const st = a.stats || {};
    const reqLabel = (r) => (r === true ? `<span class="bad-text">필수</span>` : r === false ? `<span class="muted">선택(동적 조건)</span>` : `<span class="muted">미확인</span>`);
    const typeName = { date: "날짜", code: "코드/선택", number: "숫자", text: "문자", check: "체크박스", radio: "라디오" };
    el.innerHTML = `
      <div class="report-grid">
        <div class="kpi"><div class="stat-label">최근 분석</div><div class="stat-num" style="font-size:17px">${esc(a.lastRunAt)}</div><div class="stat-sub">소요 ${a.durationSec}초</div></div>
        <div class="kpi"><div class="stat-label">생성된 초안</div><div class="stat-num">${a.generated}</div><div class="stat-sub">중복 제거 · 근거 통합 후</div></div>
        <div class="kpi"><div class="stat-label">병합 결과</div><div class="stat-num" style="font-size:17px">신규 ${st.added ?? 0} · 갱신 ${st.updated ?? 0}</div><div class="stat-sub">수정 보존 ${st.kept ?? 0} · 삭제 ${st.removed ?? 0} · 근거 소실 ${st.stale ?? 0}</div></div>
        <div class="kpi"><div class="stat-label">개발자 확인 필요</div><div class="stat-num" style="color:var(--warn)">${cs.filter((c) => c.needsReview).length}</div><div class="stat-sub">근거 불충분 · 업무 규칙 미확인</div></div>
      </div>
      <div class="report-cols">
        <div class="card">
          <div class="card-head"><h3>파일별 분석 결과</h3></div>
          <table class="rtable"><thead><tr><th>자료</th><th>결과</th><th>추출 내용</th></tr></thead><tbody>
          ${(a.files || []).map((f) => `<tr>
            <td><span class="chip t-${f.type === "REQ_TEXT" ? "REQ" : f.type}">${esc(f.type === "REQ_TEXT" ? "직접입력" : typeShort(f.type))}</span> <b>${esc(f.file)}</b></td>
            <td>${f.ok ? `<span class="ok-text">성공</span>` : `<span class="bad-text">오류</span>`}</td>
            <td class="sm">${f.ok ? summarize(f) : esc(f.error.message) + (f.error.line ? ` <span class="err-loc">(라인 ${f.error.line})</span>` : "")}</td></tr>`).join("")}
          </tbody></table>
          ${(a.warnings || []).length ? `<div class="section-title" style="margin-top:14px">경고 ${a.warnings.length}건</div><ul class="err-list">${a.warnings.slice(0, 20).map((w) => `<li class="warn">${ICON.warn}<div><b>${esc(w.file)}</b> ${w.line ? `<span class="err-loc">L${w.line}</span>` : ""}<div>${esc(w.message)}</div></div></li>`).join("")}</ul>` : ""}
        </div>
        <div class="card">
          <div class="card-head"><h3>테스트 분류별 건수</h3></div>
          <div class="bars">${catCounts.map(([c, n]) => `<div class="bar-row"><span>${esc(c)}</span><div class="bar-track"><div class="bar-fill ${catClass(c)}" style="width:${(n / maxCat) * 100}%;background:currentColor;opacity:.75"></div></div><span class="n">${n}</span></div>`).join("")}</div>
        </div>
      </div>
      <div class="card mt">
        <div class="card-head"><div><h3>통합 분석 — 추출된 화면 정보와 입력 항목</h3><p class="muted sm">요구사항 · XML · SQL 에서 같은 항목을 하나로 합쳐 테스트 케이스를 만들었습니다.</p></div></div>
        <div class="meta-line" style="margin-bottom:10px"><span>화면 <b>${esc(ctx.screen || "-")}</b></span><span>주 기능 <b>${esc(ctx.feature || "-")}</b></span><span>주 동작 <b>${esc(ctx.action || "-")}</b></span>${(ctx.ranges || []).map((r) => `<span>기간 <b>${esc(r)}</b></span>`).join("")}</div>
        ${(ctx.fields || []).length ? `<table class="rtable"><thead><tr><th>항목</th><th>유형</th><th>필수 여부</th><th>근거</th></tr></thead><tbody>
          ${ctx.fields.map((f) => `<tr><td><b>${esc(f.label)}</b></td><td>${typeName[f.type] || esc(f.type)}</td><td>${reqLabel(f.required)}</td><td><div class="src-chips">${f.sources.map((t) => { const m = SRC_TYPE[t] || ["CHG", t]; return `<span class="chip t-${m[0]}">${esc(m[1])}</span>`; }).join("")}</div></td></tr>`).join("")}
        </tbody></table>` : `<p class="muted">추출된 입력 항목이 없습니다.</p>`}
      </div>`;
  }
  function summarize(f) {
    const s = f.summary || {};
    const parts = [`분석 요소 ${f.facts}건`];
    if (s.functions && s.functions.length) parts.push(`기능: ${s.functions.join(", ")}`);
    if (s.fields && Array.isArray(s.fields) && s.fields.length) parts.push(`항목: ${s.fields.join(", ")}`);
    if (s.title) parts.push(`화면: ${s.title}`);
    if (typeof s.fields === "number") parts.push(`입력 ${s.fields} · 버튼 ${s.buttons} · 그리드 ${s.grids}`);
    if (s.types) parts.push(Object.entries(s.types).map(([k, v]) => `${k} ${v}`).join(" · "));
    if (s.class) parts.push(`클래스 ${s.class} · 메서드 ${s.methods.length} · 조건 ${s.conditions}`);
    if (s.encoding) parts.push(s.encoding.toUpperCase());
    if (f.warnings && f.warnings.length) parts.push(`경고 ${f.warnings.length}`);
    return esc(parts.join(" · "));
  }

  // ------------------------------------------------------------------ Theme
  function applyTheme(t) {
    document.documentElement.dataset.theme = t;
    store.set("tcgen.theme", t);
  }

  // ------------------------------------------------------------------ Events
  function bind() {
    $("#btnNewProject").onclick = guard(newProjectDialog);
    $("#btnWelcomeNew").onclick = guard(newProjectDialog);
    $("#btnWelcomeSample").onclick = guard(createSampleProject);
    $("#projectSearch").oninput = renderProjects;
    $("#projectList").onclick = guard(async (e) => { const b = e.target.closest(".proj-item"); if (b) await openProject(b.dataset.id); });
    $("#btnTheme").onclick = () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");

    ["#projName", "#projDesc", "#reqText"].forEach((s) => $(s).addEventListener("input", () => { setDirty(true); if (s === "#reqText") updateReqCount(); }));
    $("#btnSave").onclick = guard(() => saveProject());
    $("#btnExport").onclick = guard(() => exportExcel());
    $("#btnMore").onclick = (e) => { e.stopPropagation(); $("#moreMenu").classList.toggle("hidden"); };
    document.addEventListener("click", () => $("#moreMenu").classList.add("hidden"));
    $("#moreMenu").onclick = guard(async (e) => {
      const act = e.target.dataset.act;
      $("#moreMenu").classList.add("hidden");
      if (act === "delete") await deleteProject();
      if (act === "export-fail") {
        if (!S.project.testCases.some((c) => c.status === "실패")) { toast("실패 상태인 테스트 케이스가 없습니다.", "err"); return; }
        await exportExcel({ status: "실패" });
      }
      if (act === "samples") {
        const r = await api("POST", `/api/projects/${S.project.id}/samples`, {});
        S.project.files = r.files; renderFiles(); renderMeta(); toast(`샘플 파일 ${r.added.length}개를 추가했습니다.`);
      }
    });
    $("#tabs").onclick = (e) => { const t = e.target.closest(".tab"); if (t) switchTab(t.dataset.tab); };

    // inputs
    $("#btnExampleReq").onclick = () => {
      const t = $("#reqText");
      t.value = t.value.trim() ? t.value.trim() + "\n" + EXAMPLE_REQ : EXAMPLE_REQ;
      setDirty(true); updateReqCount();
    };
    $("#fileInput").onchange = guard(async (e) => { await uploadFiles(e.target.files); e.target.value = ""; });
    const dz = $("#dropzone");
    ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
    dz.addEventListener("drop", guard((e) => uploadFiles(e.dataTransfer.files)));
    $("#fileList").addEventListener("click", guard(async (e) => {
      const li = e.target.closest(".file-item");
      const btn = e.target.closest("[data-act]");
      if (!li || !btn) return;
      const fid = li.dataset.id;
      if (btn.dataset.act === "preview") await previewFile(fid);
      if (btn.dataset.act === "remove") {
        const f = S.project.files.find((x) => x.id === fid);
        const ok = await confirmBox("파일 삭제", `<b>${esc(f.name)}</b> 을(를) 목록에서 삭제할까요?<br><span class="muted sm">원본 파일은 영향을 받지 않습니다. 생성된 테스트 케이스는 다음 분석 때 정리됩니다.</span>`, "삭제", true);
        if (!ok) return;
        const r = await api("DELETE", `/api/projects/${S.project.id}/files/${fid}`);
        S.project.files = r.files; renderFiles(); renderMeta();
      }
    }));
    $("#fileList").addEventListener("change", guard(async (e) => {
      if (e.target.dataset.act !== "toggle") return;
      const fid = e.target.closest(".file-item").dataset.id;
      const f = await api("PATCH", `/api/projects/${S.project.id}/files/${fid}`, { enabled: e.target.checked });
      Object.assign(S.project.files.find((x) => x.id === fid), f);
      renderFiles(); renderMeta();
    }));
    const setAll = guard(async (on) => {
      for (const f of S.project.files.filter((x) => x.enabled !== on)) {
        Object.assign(f, await api("PATCH", `/api/projects/${S.project.id}/files/${f.id}`, { enabled: on }));
      }
      renderFiles(); renderMeta();
    });
    $("#btnAllOn").onclick = () => setAll(true);
    $("#btnAllOff").onclick = () => setAll(false);
    $("#btnAnalyze").onclick = guard(() => startAnalysis());
    $("#btnCancel").onclick = guard(async () => { if (S.job) { const j = await api("POST", `/api/jobs/${S.job.id}/cancel`); updateProgress(j); } });
    $("#analyzeResult").addEventListener("click", guard(async (e) => {
      const b = e.target.closest("[data-preview]");
      if (b) await previewFile(b.dataset.preview, parseInt(b.dataset.line, 10) || null);
    }));

    // cases
    let qTimer;
    $("#caseSearch").oninput = (e) => { clearTimeout(qTimer); qTimer = setTimeout(() => { S.filter.q = e.target.value; renderCases(); }, 150); };
    $("#statusSeg").onclick = (e) => { const b = e.target.closest("button"); if (b) { S.filter.status = b.dataset.v; renderCases(); } };
    $("#stats").onclick = (e) => { const s = e.target.closest(".stat[data-status]"); if (s) { S.filter.status = S.filter.status === s.dataset.status ? "" : s.dataset.status; renderCases(); } };
    $("#fCategory").onchange = (e) => { S.filter.category = e.target.value; renderCases(); };
    $("#fPriority").onchange = (e) => { S.filter.priority = e.target.value; renderCases(); };
    $("#fFeature").onchange = (e) => { S.filter.feature = e.target.value; renderCases(); };
    $("#fReview").onchange = (e) => { S.filter.review = e.target.checked; renderCases(); };
    $("#btnAddCase").onclick = () => openDrawer(null);
    $$("#casesTable th.sortable").forEach((th) => th.onclick = () => {
      const k = th.dataset.sort;
      if (S.sort.key === k) { if (S.sort.dir === 1) S.sort.dir = -1; else S.sort = { key: null, dir: 1 }; }
      else S.sort = { key: k, dir: 1 };
      renderCases();
    });
    $("#chkAll").onchange = (e) => { filtered().forEach((c) => (e.target.checked ? S.selected.add(c.uid) : S.selected.delete(c.uid))); renderCases(); };
    const tbody = $("#casesBody");
    tbody.addEventListener("click", (e) => {
      const tr = e.target.closest("tr");
      if (!tr) return;
      if (e.target.matches("[data-chk]") || e.target.closest(".col-chk")) {
        const uid = tr.dataset.uid;
        if (!e.target.matches("[data-chk]")) { const cb = tr.querySelector("[data-chk]"); cb.checked = !cb.checked; }
        tr.querySelector("[data-chk]").checked ? S.selected.add(uid) : S.selected.delete(uid);
        tr.classList.toggle("sel", S.selected.has(uid));
        renderBulk();
        $("#chkAll").checked = filtered().every((c) => S.selected.has(c.uid));
        return;
      }
      if (e.target.matches("[data-status]")) return;
      openDrawer(tr.dataset.uid);
    });
    tbody.addEventListener("change", guard(async (e) => {
      if (!e.target.matches("[data-status]")) return;
      await setStatus(e.target.closest("tr").dataset.uid, e.target.value);
    }));
    $("#bulkStatus").innerHTML = `<option value="">상태 변경…</option>` + "미실행 성공 실패 보류".split(" ").map((s) => `<option>${s}</option>`).join("");
    $("#bulkPriority").innerHTML = `<option value="">중요도 변경…</option>` + "높음 중간 낮음".split(" ").map((s) => `<option>${s}</option>`).join("");
    $("#bulkStatus").onchange = guard(async (e) => { if (e.target.value) await bulk("status", e.target.value); e.target.value = ""; });
    $("#bulkPriority").onchange = guard(async (e) => { if (e.target.value) await bulk("priority", e.target.value); e.target.value = ""; });
    $("#bulkDelete").onclick = guard(() => bulk("delete"));
    $("#bulkClear").onclick = () => { S.selected.clear(); renderCases(); };
    $("#bulkExport").onclick = guard(() => exportExcel({ uids: [...S.selected].join(",") }));

    // drawer
    $("#dClose").onclick = () => closeDrawer();
    $("#drawerBackdrop").onclick = () => closeDrawer();
    $("#dSave").onclick = guard(saveDrawer);
    $("#dDelete").onclick = guard(deleteDrawerCase);
    $("#dCopy").onclick = guard(copyDrawerCase);
    $("#drawer").addEventListener("input", (e) => { S.drawerDirty = true; if (e.target.tagName === "TEXTAREA") autoGrow(e.target); });
    $("#drawer").addEventListener("change", () => { S.drawerDirty = true; });
    $("#dPriority").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; dState.priority = b.dataset.v; segButtons($("#dPriority"), S.meta.priorities, dState.priority); S.drawerDirty = true; };
    $("#dStatus").onclick = (e) => {
      const b = e.target.closest("button"); if (!b) return;
      dState.status = b.dataset.v;
      segButtons($("#dStatus"), S.meta.statuses, dState.status, "v-");
      $("#dFailWrap").classList.toggle("hidden", dState.status !== "실패");
      if (["성공", "실패"].includes(dState.status) && !$("#dExecutedAt").value) $("#dExecutedAt").value = new Date().toISOString().slice(0, 10);
      if (dState.status === "실패") setTimeout(() => $("#dFailReason").focus(), 30);
      S.drawerDirty = true;
    };

    // modal
    $("#modalX").onclick = () => closeModal(null);
    $("#modal").addEventListener("mousedown", (e) => { if (e.target.id === "modal") closeModal(null); });

    // keyboard
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (!$("#modal").classList.contains("hidden")) return;
        if (S.drawer) guard(saveDrawer)(); else if (S.project) guard(() => saveProject())();
      }
      if (e.key === "Escape") {
        if (!$("#modal").classList.contains("hidden")) closeModal(null);
        else if (S.drawer) closeDrawer();
      }
    });
    window.addEventListener("beforeunload", (e) => { if (S.dirty || S.drawerDirty) { e.preventDefault(); e.returnValue = ""; } });
  }

  function updateReqCount() {
    const v = $("#reqText").value;
    const sentences = v.split(/\n|(?<=[.!?])\s+/).filter((s) => s.trim().length > 3).length;
    $("#reqCount").textContent = `${v.length.toLocaleString()}자 · 약 ${sentences}문장`;
  }

  // ------------------------------------------------------------------ Init
  async function init() {
    applyTheme(store.get("tcgen.theme", window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
    bind();
    try {
      S.meta = await api("GET", "/api/meta");
      await loadProjects();
      const last = store.get("tcgen.last", null);
      if (last && S.projects.some((p) => p.id === last)) await openProject(last, { force: true });
    } catch (e) {
      toast(e.message, "err");
    }
  }
  init();
})();
