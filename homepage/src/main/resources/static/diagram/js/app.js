/*
 * 업무 도식화 도구 - 화면 동작
 */
(function () {
  'use strict';
  var M = window.FlowModel, G = window.FlowGenerator, X = window.FlowExport;
  var STORE_KEY = 'flowdiagram.v1';

  var INFO_FIELDS = ['title', 'requirement', 'devNotes', 'owners', 'roles', 'screens', 'startCond', 'endCond', 'steps', 'conditions', 'before', 'after'];

  var state = {
    info: {},
    steps: [],
    kind: 'process',
    mode: 'customer',
    settings: { perLine: 14, maxNodes: 10, summarizeSystem: true },
    overrides: {}
  };

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  function h(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function toast(msg, isErr) {
    var t = $('#toast');
    t.textContent = msg; t.className = 'toast show' + (isErr ? ' err' : '');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(function () { t.className = 'toast'; }, 2600);
  }

  /* ------------------------------------------------------------------ 저장/복원 */
  function persist() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) { /* 저장 불가 환경 무시 */ }
  }
  function restore() {
    try {
      var raw = localStorage.getItem(STORE_KEY);
      if (!raw) return false;
      applyProject(JSON.parse(raw));
      return true;
    } catch (e) { return false; }
  }
  function applyProject(p) {
    state.info = p.info || {};
    state.steps = (p.steps || []).map(function (s) { return M.newStep(s); });
    state.kind = p.kind || 'process';
    state.mode = p.mode || 'customer';
    state.settings = Object.assign({ perLine: 14, maxNodes: 10, summarizeSystem: true }, p.settings || {});
    state.overrides = p.overrides || {};
    syncForm();
  }

  function syncForm() {
    INFO_FIELDS.forEach(function (f) { var el = $('[data-info="' + f + '"]'); if (el) el.value = state.info[f] || ''; });
    $$('#kindSeg button').forEach(function (b) { b.classList.toggle('on', b.dataset.kind === state.kind); });
    $$('#modeSeg button').forEach(function (b) { b.classList.toggle('on', b.dataset.mode === state.mode); });
    $('#optPerLine').value = state.settings.perLine;
    $('#optMaxNodes').value = state.settings.maxNodes;
    $('#optSummarize').checked = state.settings.summarizeSystem !== false;
    if (state.info.owners || state.info.roles || state.info.screens || state.info.before || state.info.conditions) $('#moreInfo').open = true;
    renderSteps();
  }

  /* ------------------------------------------------------------------ 단계 편집 */
  function flowOptions(val, selfIdx) {
    var opts = [['continue', '다음 단계로'], ['end', '업무 종료']];
    state.steps.forEach(function (s, i) {
      if (i !== selfIdx && s.type !== 'section') opts.push(['goto:' + (i + 1), M.stepNo(state.steps, i) + '단계로 이동']);
    });
    return opts.map(function (o) { return '<option value="' + o[0] + '"' + (o[0] === val ? ' selected' : '') + '>' + h(o[1]) + '</option>'; }).join('');
  }

  function custPreview(s) {
    if (s.type === 'section') return '';
    if (!s.showCustomer) return '고객 화면: 숨김' + (state.settings.summarizeSystem ? ' (“시스템이 자동으로 처리”로 요약)' : '');
    var opt = { customer: true };
    var t = s.text || '';
    var c = s.type === 'error' && /(오류|에러|exception|error)/i.test(t) ? M.friendlyError(t) : M.customerizeText(t);
    if (s.type === 'auth' && (M.TECH_DETECT.test(t) || !c)) c = '이용 권한이 있나요?';
    return c && c !== t ? '고객 화면 표현: ' + c : '';
  }

  function renderSteps() {
    var list = $('#stepList');
    var typeOpts = Object.keys(M.STEP_TYPES).map(function (k) { return [k, M.STEP_TYPES[k].label]; });
    list.innerHTML = state.steps.map(function (s, i) {
      var ask = s.type === 'decision' || s.type === 'auth';
      var sel = '<select data-f="type" aria-label="유형">' + typeOpts.map(function (o) {
        return '<option value="' + o[0] + '"' + (o[0] === s.type ? ' selected' : '') + '>' + o[1] + '</option>';
      }).join('') + '</select>';
      var tools = '<span class="tools">' +
        '<button type="button" data-act="up" title="위로">↑</button>' +
        '<button type="button" data-act="down" title="아래로">↓</button>' +
        '<button type="button" data-act="insert" title="아래에 단계 추가">＋</button>' +
        '<button type="button" data-act="del" title="삭제">✕</button></span>';
      if (s.type === 'section') {
        return '<li class="step-card type-section" data-i="' + i + '"><div class="row1"><span class="num">§</span>' + sel + tools + '</div>' +
          '<input data-f="text" class="w" value="' + h(s.text) + '" placeholder="업무 단위 이름 (예: 반품 심사)"></li>';
      }
      return '<li class="step-card type-' + s.type + '" data-i="' + i + '">' +
        '<div class="row1"><span class="num">' + M.stepNo(state.steps, i) + '</span>' + sel +
        '<input data-f="role" class="role" value="' + h(s.role) + '" placeholder="담당">' +
        '<label class="chk" title="고객 설명 모드에 표시"><input type="checkbox" data-f="showCustomer"' + (s.showCustomer ? ' checked' : '') + '>고객 표시</label>' + tools + '</div>' +
        '<input data-f="text" class="w" value="' + h(s.text) + '" placeholder="' + (ask ? '조건 질문 (예: 필수 항목이 입력되었나요?)' : '업무 단계 (짧은 문장)') + '">' +
        '<div class="cust-preview" data-preview>' + h(custPreview(s)) + '</div>' +
        '<div class="row2"><input data-f="devText" value="' + h(s.devText) + '" placeholder="개발자 상세 (DB·권한·연계·예외 등)">' +
        '<input data-f="screen" class="scr" value="' + h(s.screen) + '" placeholder="관련 화면"></div>' +
        (ask ? '<div class="branch"><span class="yes">예</span><input data-f="yesText" value="' + h(s.yesText) + '" placeholder="예일 때 처리 (선택)"><select data-f="yesFlow">' + flowOptions(s.yesFlow, i) + '</select></div>' +
          '<div class="branch"><span class="no">아니오</span><input data-f="noText" value="' + h(s.noText) + '" placeholder="아니오일 때 처리 / 안내 문구"><select data-f="noFlow">' + flowOptions(s.noFlow, i) + '</select></div>' : '') +
        '</li>';
    }).join('');
    $('#stepCount').textContent = state.steps.length ? '(' + state.steps.length + '개)' : '';
    if (!state.steps.length) list.innerHTML = '<li class="empty">고객 요구사항을 입력하고 “단계 자동 정리”를 누르거나, “+ 단계 추가”로 직접 만드세요.</li>';
  }

  function onStepInput(e) {
    var card = e.target.closest('.step-card'); if (!card) return;
    var f = e.target.dataset.f; if (!f) return;
    var s = state.steps[+card.dataset.i];
    var v = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    s[f] = v;
    if (f === 'type') {
      s.showCustomer = M.STEP_TYPES[v].customer;
      renderSteps();
    } else {
      var p = card.querySelector('[data-preview]'); if (p) p.textContent = custPreview(s);
    }
    changed();
  }

  function remapFlows(fn) {
    // 단계 순서가 바뀌면 "N단계로 이동" 참조를 함께 보정
    state.steps.forEach(function (s) {
      ['yesFlow', 'noFlow'].forEach(function (k) {
        if (s[k] && s[k].indexOf('goto:') === 0) {
          var n = fn(parseInt(s[k].slice(5), 10));
          s[k] = n ? 'goto:' + n : 'continue';
        }
      });
    });
  }

  function onStepAction(e) {
    var btn = e.target.closest('button[data-act]'); if (!btn) return;
    var i = +btn.closest('.step-card').dataset.i;
    var act = btn.dataset.act, st = state.steps;
    if (act === 'del') {
      st.splice(i, 1);
      remapFlows(function (n) { return n === i + 1 ? null : (n > i + 1 ? n - 1 : n); });
    } else if (act === 'insert') {
      st.splice(i + 1, 0, M.newStep());
      remapFlows(function (n) { return n > i + 1 ? n + 1 : n; });
    } else if (act === 'up' && i > 0) {
      var t = st[i - 1]; st[i - 1] = st[i]; st[i] = t;
      remapFlows(function (n) { return n === i + 1 ? i : (n === i ? i + 1 : n); });
    } else if (act === 'down' && i < st.length - 1) {
      var t2 = st[i + 1]; st[i + 1] = st[i]; st[i] = t2;
      remapFlows(function (n) { return n === i + 1 ? i + 2 : (n === i + 2 ? i + 1 : n); });
    } else return;
    renderSteps(); changed();
  }

  /* ------------------------------------------------------------------ 도식 출력 */
  var renderTimer = null, renderToken = 0, mmdSeq = 0;
  function changed() {
    persist();
    clearTimeout(renderTimer);
    renderTimer = setTimeout(renderOutput, 250);
  }

  function hasContent() {
    if (state.kind === 'compare') return !!(state.info.before || state.info.after);
    if (state.kind === 'condition') return !!(state.info.conditions || state.steps.some(function (s) { return s.type === 'decision' || s.type === 'auth'; }));
    if (state.kind === 'screen') return state.steps.some(function (s) { return s.screen; }) || !!state.info.screens;
    return state.steps.length > 0;
  }

  function sheetHtml(mode) {
    var customer = mode === 'customer';
    var info = state.info;
    var today = new Date();
    var date = today.getFullYear() + '. ' + (today.getMonth() + 1) + '. ' + today.getDate() + '.';
    var pages = G.generate(state.kind, info, state.steps, mode, state.settings);
    var typeName = G.TYPE_NAMES[state.kind];
    var html = '<article class="sheet ' + (customer ? 'mode-customer' : 'mode-developer') + '" data-mode="' + mode + '">';
    html += '<header class="sheet-head"><div class="kicker">' + (customer ? '고객 설명 자료' : '개발자 검토 자료') + '</div>' +
      '<h1>' + h(info.title || '업무') + ' · ' + h(typeName) + '</h1>' +
      '<div class="meta"><span>작성일 ' + date + '</span>' +
      (info.owners ? '<span>업무 담당: ' + h(info.owners) + '</span>' : '') +
      (info.roles ? '<span>사용자: ' + h(info.roles) + '</span>' : '') + '</div></header>';

    if (info.startCond || info.endCond) {
      html += '<dl class="overview">' +
        (info.startCond ? '<div><dt>시작 조건</dt><dd>' + h(customer ? M.customerizeText(info.startCond) : info.startCond) + '</dd></div>' : '') +
        (info.endCond ? '<div><dt>종료 조건</dt><dd>' + h(customer ? M.customerizeText(info.endCond) : info.endCond) + '</dd></div>' : '') + '</dl>';
    }

    if (!hasContent()) {
      html += '<div class="placeholder">' + placeholderText() + '</div></article>';
      return { html: html, pages: [] };
    }

    pages.forEach(function (p, i) {
      var key = state.kind + '|' + mode + '|' + i;
      var code = state.overrides[key] || p.code;
      p.key = key; p.finalCode = code; p.edited = !!state.overrides[key];
      html += '<figure class="page" data-key="' + key + '">' +
        (pages.length > 1 || p.title ? '<figcaption>' + h(p.title) + '</figcaption>' : '') +
        '<div class="diagram" id="dg-' + mode + '-' + i + '"><div class="loading">도식을 그리는 중…</div></div>' +
        (p.edited ? '<div class="edited no-print">직접 수정한 코드가 적용된 도식입니다. 입력 내용을 바꿔도 이 도식은 바뀌지 않습니다. <button type="button" data-pact="revert">자동 생성으로 되돌리기</button></div>' : '') +
        '<div class="page-tools no-print">' +
        '<button type="button" data-pact="code">Mermaid 코드 보기·수정</button>' +
        '<button type="button" data-pact="copy">코드 복사</button>' +
        '<button type="button" data-pact="mmd">Mermaid 파일</button>' +
        '<button type="button" data-pact="svg">SVG</button>' +
        '<button type="button" data-pact="png">PNG</button></div>' +
        '<div class="code-box no-print" hidden><textarea spellcheck="false">' + h(code) + '</textarea>' +
        '<div class="code-actions"><button type="button" class="primary" data-pact="apply">수정한 코드로 다시 그리기</button>' +
        '<span class="hint">노드 문구·연결·색상 등을 직접 고칠 수 있습니다.</span></div></div>' +
        '</figure>';
    });

    html += legendHtml(customer);
    html += customer ? customerNotesHtml() : developerNotesHtml();
    html += '</article>';
    return { html: html, pages: pages };
  }

  function placeholderText() {
    switch (state.kind) {
      case 'compare': return '추가 정보의 “변경 전 업무 방식”과 “변경 후 업무 방식”을 입력하면 비교도가 만들어집니다.';
      case 'condition': return '추가 정보의 “조건 및 예외사항”을 입력하거나, 단계에 조건 판단을 추가하세요.';
      case 'screen': return '단계별 “관련 화면” 또는 추가 정보의 “관련 화면명”을 입력하세요.';
      default: return '왼쪽에 고객 요구사항을 입력하고 “단계 자동 정리 → 도식 생성”을 눌러 주세요.';
    }
  }

  function legendHtml(customer) {
    var items = [
      ['lg-start', '시작 / 종료'], ['lg-step', '업무 단계'], ['lg-ask', '확인·판단 (예 / 아니오)'], ['lg-warn', '안내·예외']
    ];
    if (state.kind === 'compare') items = [['lg-step', '유지되는 단계'], ['lg-added', '새로 추가'], ['lg-removed', '없어지는 단계']];
    else if (customer) items.push(['lg-sys', '시스템 자동 처리']);
    else items = items.concat([['lg-data', '데이터 조회·저장'], ['lg-integ', '시스템 연계'], ['lg-auth', '권한 확인'], ['lg-scr', '화면']]);
    return '<div class="legend">' + items.map(function (it) { return '<span><i class="' + it[0] + '"></i>' + it[1] + '</span>'; }).join('') + '</div>';
  }

  function customerNotesHtml() {
    var rows = [];
    state.steps.forEach(function (s) {
      if (s.type === 'decision' || s.type === 'auth') {
        var q = s.type === 'auth' && M.TECH_DETECT.test(s.text) ? '이용 권한이 있나요?' : M.customerizeText(s.text);
        if (s.noText) rows.push([q, '아니오', /(오류|에러|exception|error|코드)/i.test(s.noText) ? M.friendlyError(s.noText) : M.customerizeText(s.noText)]);
      } else if (s.type === 'error' && s.showCustomer) {
        rows.push(['처리 중 문제 발생', '-', M.friendlyError(s.text)]);
      }
    });
    if (!rows.length) return '';
    return '<section class="notes"><h2>이런 경우에는 이렇게 안내됩니다</h2><table><thead><tr><th>확인 내용</th><th>결과</th><th>안내</th></tr></thead><tbody>' +
      rows.map(function (r) { return '<tr><td>' + h(r[0]) + '</td><td>' + h(r[1]) + '</td><td>' + h(r[2]) + '</td></tr>'; }).join('') + '</tbody></table></section>';
  }

  function developerNotesHtml() {
    var html = '';
    var groups = M.categorizeDevNotes(state.info.devNotes);
    if (groups.length) {
      html += '<section class="notes"><h2>개발 시 고려사항</h2><div class="dev-groups">' + groups.map(function (g) {
        return '<div class="dev-group g-' + g.key + '"><h3>' + h(g.label) + '</h3><ul>' + g.items.map(function (it) { return '<li>' + h(it) + '</li>'; }).join('') + '</ul></div>';
      }).join('') + '</div></section>';
    }
    if (state.steps.length && state.mode !== 'both') {
      html += '<section class="notes"><h2>단계 상세</h2><table class="detail"><thead><tr><th>#</th><th>유형</th><th>담당</th><th>업무 내용</th><th>개발 상세</th><th>화면</th></tr></thead><tbody>' +
        state.steps.map(function (s, i) {
          if (s.type === 'section') return '<tr class="sec"><td colspan="6">' + h(s.text) + '</td></tr>';
          var br = '';
          if (s.type === 'decision' || s.type === 'auth') {
            br = '<div class="br">예: ' + h(s.yesText || '다음 단계') + ' → ' + h(flowName(s.yesFlow)) + '<br>아니오: ' + h(s.noText || '다음 단계') + ' → ' + h(flowName(s.noFlow)) + '</div>';
          }
          return '<tr><td>' + M.stepNo(state.steps, i) + '</td><td>' + h(M.STEP_TYPES[s.type].label) + '</td><td>' + h(s.role) + '</td><td>' + h(s.text) + br + '</td><td>' + h(s.devText) + '</td><td>' + h(s.screen) + '</td></tr>';
        }).join('') + '</tbody></table></section>';
    }
    return html;
  }

  function flowName(f) {
    if (f === 'end') return '업무 종료';
    if (f && f.indexOf('goto:') === 0) return M.stepNo(state.steps, parseInt(f.slice(5), 10) - 1) + '단계로 이동';
    return '다음 단계';
  }

  function compareHtml() {
    var rows = state.steps.map(function (s, i) {
      if (s.type === 'section') return '';
      var cust = s.showCustomer ? custPreview(s).replace(/^고객 화면 표현: /, '') || s.text : (state.settings.summarizeSystem ? '“시스템이 자동으로 처리”로 요약' : '표시 안 함');
      var changedCls = !s.showCustomer ? 'hidden-row' : (cust !== s.text ? 'diff-row' : '');
      return '<tr class="' + changedCls + '"><td>' + M.stepNo(state.steps, i) + '</td><td>' + h(M.STEP_TYPES[s.type].label) + '</td><td>' + h(s.text) + (s.devText ? '<div class="dev">※ ' + h(s.devText) + '</div>' : '') + '</td><td>' + h(cust) + '</td></tr>';
    }).join('');
    if (!rows) return '';
    var hidden = state.steps.filter(function (s) { return s.type !== 'section' && !s.showCustomer; }).length;
    return '<section class="sheet compare-table"><h2>고객 설명 모드 · 개발자 설명 모드 표현 비교</h2>' +
      '<p class="hint">같은 업무 정보에서 만든 두 도식의 차이입니다. 고객 모드에서 숨겨진 내부 처리 단계: <b>' + hidden + '개</b></p>' +
      '<table><thead><tr><th>#</th><th>유형</th><th>개발자 설명 모드</th><th>고객 설명 모드</th></tr></thead><tbody>' + rows + '</tbody></table></section>';
  }

  var rendered = []; // { key, title, code, el, mode }

  function renderOutput() {
    var token = ++renderToken;
    var modes = state.mode === 'both' ? ['customer', 'developer'] : [state.mode];
    var wrap = $('#sheets');
    var built = modes.map(sheetHtml);
    wrap.className = 'sheets' + (modes.length > 1 ? ' two' : '');
    wrap.innerHTML = '<div class="sheet-row">' + built.map(function (b) { return b.html; }).join('') + '</div>' + (modes.length > 1 ? compareHtml() : '');
    rendered = [];
    var jobs = [];
    built.forEach(function (b, mi) {
      b.pages.forEach(function (p, i) {
        jobs.push({ mode: modes[mi], i: i, page: p });
      });
    });
    (function next(k) {
      if (token !== renderToken || k >= jobs.length) return;
      var j = jobs[k];
      var holder = document.getElementById('dg-' + j.mode + '-' + j.i);
      var id = 'mmd' + (++mmdSeq);
      var entry = { key: j.page.key, title: j.page.title, code: j.page.finalCode, mode: j.mode, el: holder };
      rendered.push(entry);
      Promise.resolve().then(function () { return mermaid.render(id, j.page.finalCode); }).then(function (res) {
        if (token !== renderToken) return;
        holder.innerHTML = res.svg;
        var svg = holder.querySelector('svg');
        if (svg) { svg.removeAttribute('height'); svg.style.maxWidth = '100%'; }
      }).catch(function (err) {
        if (token !== renderToken) return;
        var leftover = document.getElementById('d' + id); if (leftover) leftover.remove();
        holder.innerHTML = '<div class="render-error">도식을 그리지 못했습니다. Mermaid 코드를 확인해 주세요.<pre>' + h(String(err && err.message || err).slice(0, 400)) + '</pre></div>';
      }).then(function () { next(k + 1); });
    })(0);
  }

  function entryFor(fig) {
    var key = fig.dataset.key;
    for (var i = 0; i < rendered.length; i++) if (rendered[i].key === key) return rendered[i];
    return null;
  }

  function fileBase(e) {
    var modeName = e.mode === 'customer' ? '고객용' : '개발자용';
    return (e.title || state.info.title || '도식') + '_' + modeName;
  }

  function onPageAction(ev) {
    var btn = ev.target.closest('button[data-pact]'); if (!btn) return;
    var fig = btn.closest('.page'); if (!fig) return;
    var e = entryFor(fig); if (!e) return;
    var svg = fig.querySelector('.diagram svg');
    var act = btn.dataset.pact;
    if (act === 'code') { var box = fig.querySelector('.code-box'); box.hidden = !box.hidden; return; }
    if (act === 'copy') { X.copyText(e.code).then(function () { toast('Mermaid 코드를 복사했습니다.'); }, function () { toast('복사하지 못했습니다. 코드 보기에서 직접 선택해 주세요.', true); }); return; }
    if (act === 'mmd') { X.saveMmd(e.code, fileBase(e)); return; }
    if (act === 'svg') { if (!svg) return toast('저장할 도식이 없습니다.', true); X.saveSvg(svg, e.title, fileBase(e)); return; }
    if (act === 'png') { if (!svg) return toast('저장할 도식이 없습니다.', true); X.savePng(svg, e.title, fileBase(e)).catch(function (er) { toast(er.message, true); }); return; }
    if (act === 'apply') {
      state.overrides[e.key] = fig.querySelector('.code-box textarea').value;
      persist(); renderOutput(); toast('수정한 코드로 다시 그렸습니다.'); return;
    }
    if (act === 'revert') { delete state.overrides[e.key]; persist(); renderOutput(); }
  }

  function eachRendered(fn) {
    var n = 0;
    rendered.forEach(function (e) { var svg = e.el && e.el.querySelector('svg'); if (svg) { fn(e, svg, n); n++; } });
    if (!n) toast('먼저 도식을 생성해 주세요.', true);
    return n;
  }

  /* ------------------------------------------------------------------ 이벤트 */
  function bind() {
    INFO_FIELDS.forEach(function (f) {
      var el = $('[data-info="' + f + '"]');
      if (el) el.addEventListener('input', function () { state.info[f] = el.value; changed(); });
    });

    $('#btnExtract').addEventListener('click', function () {
      if (!(state.info.requirement || '').trim() && !(state.info.steps || '').trim()) {
        toast('고객 요구사항을 먼저 입력해 주세요.', true); $('#requirement').focus(); return;
      }
      if (state.steps.length && !confirm('지금 편집 중인 단계를 입력 내용으로 새로 정리할까요?\n(직접 고친 단계 내용은 바뀝니다)')) return;
      state.steps = M.extractSteps(state.info);
      state.overrides = {};
      renderSteps(); changed();
      var asks = state.steps.filter(function (s) { return s.type === 'decision' || s.type === 'auth'; }).length;
      $('#extractMsg').textContent = '단계 ' + state.steps.length + '개 (조건 ' + asks + '개)로 정리했습니다.';
    });

    $('#btnAddStep').addEventListener('click', function () { state.steps.push(M.newStep()); renderSteps(); changed(); var c = $$('.step-card'); if (c.length) c[c.length - 1].querySelector('[data-f="text"]').focus(); });
    $('#stepList').addEventListener('input', onStepInput);
    $('#stepList').addEventListener('change', function (e) { if (e.target.tagName === 'SELECT' || e.target.type === 'checkbox') onStepInput(e); });
    $('#stepList').addEventListener('click', onStepAction);

    $('#kindSeg').addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) return;
      state.kind = b.dataset.kind; syncSeg(); changed();
    });
    $('#modeSeg').addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) return;
      state.mode = b.dataset.mode; syncSeg(); changed();
    });
    $('#optPerLine').addEventListener('change', function () { state.settings.perLine = clamp(+this.value, 8, 40, 14); changed(); });
    $('#optMaxNodes').addEventListener('change', function () { state.settings.maxNodes = clamp(+this.value, 3, 40, 10); changed(); });
    $('#optSummarize').addEventListener('change', function () { state.settings.summarizeSystem = this.checked; renderSteps(); changed(); });

    $('#sheets').addEventListener('click', onPageAction);

    $('#btnSvgAll').addEventListener('click', function () { eachRendered(function (e, svg) { X.saveSvg(svg, e.title, fileBase(e)); }); });
    $('#btnPngAll').addEventListener('click', function () {
      var chain = Promise.resolve();
      eachRendered(function (e, svg) { chain = chain.then(function () { return X.savePng(svg, e.title, fileBase(e)); }); });
      chain.catch(function (er) { toast(er.message, true); });
    });
    $('#btnMmdAll').addEventListener('click', function () { eachRendered(function (e) { X.saveMmd(e.code, fileBase(e)); }); });
    $('#btnCopyAll').addEventListener('click', function () {
      var parts = [];
      eachRendered(function (e) { parts.push('%% ' + e.title + ' (' + (e.mode === 'customer' ? '고객 설명' : '개발자 설명') + ')\n' + e.code); });
      if (parts.length) X.copyText(parts.join('\n\n')).then(function () { toast('Mermaid 코드를 복사했습니다.'); }, function () { toast('복사하지 못했습니다.', true); });
    });
    $('#btnPrint').addEventListener('click', function () { window.print(); });

    $('#btnSample').addEventListener('click', function () {
      if ((state.info.requirement || state.steps.length) && !confirm('지금 입력한 내용을 예시로 바꿀까요?')) return;
      applyProject(window.FLOW_SAMPLE());
      state.steps = M.extractSteps(state.info);
      renderSteps(); changed();
      toast('예시 업무(반품 신청)를 불러왔습니다.');
    });
    $('#btnNew').addEventListener('click', function () {
      if (!confirm('입력한 내용을 모두 지우고 새로 작성할까요?')) return;
      applyProject({}); changed();
    });
    $('#btnSaveProject').addEventListener('click', function () {
      X.saveJson({ format: 'flowdiagram', version: 1, info: state.info, steps: state.steps, kind: state.kind, mode: state.mode, settings: state.settings, overrides: state.overrides }, (state.info.title || '업무도식') + '_작업파일');
    });
    $('#fileProject').addEventListener('change', function () {
      var f = this.files && this.files[0]; if (!f) return;
      var r = new FileReader();
      r.onload = function () {
        try { applyProject(JSON.parse(r.result)); changed(); toast('작업 파일을 열었습니다.'); }
        catch (e) { toast('작업 파일 형식이 올바르지 않습니다.', true); }
      };
      r.readAsText(f, 'utf-8');
      this.value = '';
    });
  }

  function syncSeg() {
    $$('#kindSeg button').forEach(function (b) { b.classList.toggle('on', b.dataset.kind === state.kind); });
    $$('#modeSeg button').forEach(function (b) { b.classList.toggle('on', b.dataset.mode === state.mode); });
  }

  function clamp(v, a, b, d) { return isNaN(v) ? d : Math.max(a, Math.min(b, v)); }

  /* ------------------------------------------------------------------ 시작 */
  window.FLOW_SAMPLE = function () {
    return {
      kind: 'process', mode: 'customer',
      info: {
        title: '반품 신청 처리',
        requirement: [
          '# 반품 신청',
          '고객이 주문내역 화면에서 반품 신청 버튼을 누른다.',
          '로그인이 되어 있지 않으면 로그인 화면으로 이동한다.',
          '고객이 반품 신청 화면에서 반품 사유와 수거 희망일을 입력한다.',
          '필수 항목이 모두 입력되었으면 반품 신청을 접수한다.',
          '아니면 입력 내용을 다시 확인하도록 안내하고 반품 사유 입력으로 돌아간다.',
          '시스템이 주문 테이블에서 배송 완료일을 조회한다.',
          '시스템이 반품 신청 정보를 DB에 저장한다.',
          '# 반품 심사',
          '담당자가 반품 심사 화면에서 신청 내용을 검토한다.',
          '담당자는 배송 완료 후 7일 이내이면 반품을 승인한다.',
          '아니면 반품 불가 안내를 보내고 종료한다.',
          '시스템이 택배사 API로 수거 요청을 전송한다.',
          '고객에게 반품 접수 완료 알림이 발송된다.'
        ].join('\n'),
        devNotes: [
          '[1] 주문내역은 로그인한 회원 본인 주문만 조회되도록 회원ID 조건 필수',
          '로그인 세션 만료 시 로그인 화면으로 이동 후 원래 화면으로 복귀',
          '반품 신청 저장 시 RETURN_REQ 테이블 INSERT 와 주문 상태 UPDATE 를 하나의 트랜잭션으로 처리',
          '택배사 API 호출 실패 시 3회 재시도 후 실패 이력 저장, 담당자에게 알림',
          '반품 기간은 배송 완료일 기준 달력일 7일로 계산',
          '반품 심사 화면은 CS 권한(ROLE_CS) 보유자만 접근 가능'
        ].join('\n'),
        owners: '고객, 담당자, 시스템',
        roles: '회원, CS 담당자',
        screens: '주문내역 화면, 로그인 화면, 반품 신청 화면, 반품 심사 화면',
        startCond: '배송 완료된 주문이 있음',
        endCond: '반품 접수 완료 안내',
        steps: '',
        conditions: [
          '배송 완료 후 7일 이내 → 반품 접수',
          '배송 완료 후 7일 초과 → 반품 불가 안내',
          '상품 훼손이 확인됨 → 담당자 확인 후 부분 환불',
          '택배사 수거 요청 실패 → 담당자가 직접 수거 접수'
        ].join('\n'),
        before: [
          '고객이 고객센터에 전화로 반품 요청',
          '상담원이 주문 정보를 직접 찾아 확인',
          '상담원이 택배사에 전화로 수거 요청',
          '처리 결과를 고객에게 다시 전화로 안내'
        ].join('\n'),
        after: [
          '고객이 마이페이지에서 반품 신청',
          '주문 정보를 자동으로 확인',
          '담당자가 화면에서 승인',
          '택배사에 수거를 자동 요청',
          '처리 결과를 알림으로 자동 안내'
        ].join('\n')
      },
      settings: { perLine: 14, maxNodes: 10, summarizeSystem: true }
    };
  };

  function init() {
    if (!window.mermaid) {
      $('#sheets').innerHTML = '<div class="render-error">도식 엔진(lib/mermaid.min.js)을 불러오지 못했습니다. 프로그램 폴더 구성을 확인해 주세요.</div>';
      return;
    }
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'base',
      htmlLabels: false,
      markdownAutoWrap: false,
      flowchart: { htmlLabels: false, useMaxWidth: true, wrappingWidth: 600 },
      fontFamily: 'Malgun Gothic, Apple SD Gothic Neo, Noto Sans KR, sans-serif'
    });
    bind();
    if (!restore()) syncForm();
    renderOutput();
  }

  init();
})();
