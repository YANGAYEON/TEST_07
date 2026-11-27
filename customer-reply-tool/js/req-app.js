/* 요구사항 정리 화면 + 탭 전환
 * 입력 내용은 메모리에만 있고, 저장하거나 전송하지 않습니다. */
(function () {
  'use strict';
  var R = window.RequirementEngine;
  var U = window.UIUtil;
  var $ = function (id) { return document.getElementById(id); };

  /* ---------- 탭 ---------- */
  var TAGLINE = {
    reply: '확인 결과와 조치 내용을 편하게 적으면, 고객에게 보낼 답변으로 정리합니다.',
    req: '고객이 메신저로 보낸 요청을 붙여넣으면, 개발자가 보기 쉬운 요구사항으로 정리합니다.'
  };
  var tabs = { reply: $('tab-reply'), req: $('tab-req') };
  var views = { reply: $('view-reply'), req: $('view-req') };

  function showTab(name) {
    Object.keys(tabs).forEach(function (k) {
      var on = k === name;
      tabs[k].setAttribute('aria-selected', String(on));
      tabs[k].tabIndex = on ? 0 : -1;
      views[k].hidden = !on;
    });
    $('tagline').textContent = TAGLINE[name];
    if (location.hash !== '#' + name) history.replaceState(null, '', '#' + name);
  }
  tabs.reply.addEventListener('click', function () { showTab('reply'); });
  tabs.req.addEventListener('click', function () { showTab('req'); });
  document.querySelector('.tabs').addEventListener('keydown', function (e) {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    var next = tabs.reply.getAttribute('aria-selected') === 'true' ? 'req' : 'reply';
    showTab(next); tabs[next].focus();
  });

  /* ---------- 요구사항 정리 ---------- */
  var el = {
    input: $('reqInput'), sample: $('reqSampleBtn'), clear: $('reqClearBtn'),
    optBg: $('reqOptBg'), optCheck: $('reqOptCheck'), optSrc: $('reqOptSrc'),
    generate: $('reqGenerateBtn'), summary: $('reqSummary'),
    items: $('reqItems'), itemsEmpty: $('reqItemsEmpty'),
    notices: $('reqNotices'), stale: $('reqStaleBar'), regen: $('reqRegenBtn'),
    preview: $('reqPreview'), count: $('reqCount'), copy: $('reqCopyBtn')
  };

  var SAMPLE = '현재 신청 화면에서 신청일자를 직접 입력하고 있는데 매번 입력하기 불편합니다. ' +
    '화면에 처음 들어왔을 때 오늘 날짜가 자동으로 들어가도록 해주세요. ' +
    '그리고 이미 신청이 완료된 건은 수정할 수 없도록 처리하고, 취소한 건은 조회할 때 다른 색으로 표시되면 좋겠습니다.';

  var KIND_COLOR = { request: 'var(--c-action)', background: 'var(--c-result)', question: 'var(--c-inquiry)', exclude: 'var(--text-3)' };
  var state = { analysis: null, overrides: {}, dirty: false, last: null };

  function analyze() {
    var a = R.analyze(el.input.value);
    a.clauses.forEach(function (c) {
      if (state.overrides[c.text]) c.kind = state.overrides[c.text];
    });
    state.analysis = a;
    renderItems();
  }

  function renderItems() {
    var cl = state.analysis ? state.analysis.clauses : [];
    el.itemsEmpty.hidden = cl.length > 0;
    el.items.innerHTML = '';
    cl.forEach(function (c) {
      var li = document.createElement('li');
      li.className = 'item req' + (c.kind === 'exclude' ? ' off' : '');
      li.style.setProperty('--cat', KIND_COLOR[c.kind]);
      var sel = document.createElement('select');
      sel.setAttribute('aria-label', '문장 구분');
      R.KINDS.forEach(function (k) {
        var op = document.createElement('option');
        op.value = k.id; op.textContent = k.label;
        if (k.id === c.kind) op.selected = true;
        sel.appendChild(op);
      });
      sel.addEventListener('change', function () {
        c.kind = sel.value;
        state.overrides[c.text] = c.kind;
        renderItems();
        refresh();
      });
      var body = document.createElement('div');
      var txt = document.createElement('div');
      txt.className = 'txt';
      txt.textContent = c.text;
      body.appendChild(txt);
      if (c.kind !== c.autoKind) {
        var b = document.createElement('div');
        b.className = 'badges';
        b.innerHTML = '<span class="badge">직접 지정</span>';
        body.appendChild(b);
      }
      li.appendChild(sel); li.appendChild(body);
      el.items.appendChild(li);
    });
    renderSummary();
  }

  function renderSummary() {
    var cl = state.analysis ? state.analysis.clauses : [];
    var n = { request: 0, background: 0, question: 0 };
    cl.forEach(function (c) { if (n[c.kind] !== undefined) n[c.kind]++; });
    var defs = [['request', '요구사항'], ['background', '현재 상황'], ['question', '문의']];
    el.summary.innerHTML = '';
    defs.forEach(function (d) {
      var box = document.createElement('div');
      var empty = cl.length && !n[d[0]];
      box.className = 'sum' + (empty ? (d[0] === 'request' ? ' need' : ' opt') : '');
      box.innerHTML = '<div class="name"><i style="background:' + KIND_COLOR[d[0]] + '"></i></div><div class="val"></div>';
      box.querySelector('.name').appendChild(document.createTextNode(d[1]));
      box.querySelector('.val').textContent = !cl.length ? '–'
        : n[d[0]] ? n[d[0]] + '문장'
          : d[0] === 'request' ? '추가 확인 필요' : '없음';
      el.summary.appendChild(box);
    });
  }

  function toHtml(text) {
    return U.escapeHtml(text).split('\n').map(function (line) {
      if (/^\[[^\]]+\]$/.test(line) && !/^\[추가 확인 필요/.test(line)) return '<span class="sec">' + line + '</span>';
      line = line.replace(/\[추가 확인 필요:[^\]]*\]/g, '<span class="need">$&</span>');
      return line.replace(/^(\d+\.\s.*)$/, '<span class="num">$1</span>');
    }).join('\n');
  }

  function render() {
    var a = state.analysis;
    if (!a || !a.clauses.length) {
      el.preview.innerHTML = ''; el.notices.innerHTML = '';
      el.count.textContent = '요구사항 0건';
      el.copy.disabled = true;
      return;
    }
    var r = R.build(a, { background: el.optBg.checked, checks: el.optCheck.checked, source: el.optSrc.checked });
    state.last = r;
    el.preview.innerHTML = toHtml(r.text);
    state.dirty = false;
    el.stale.hidden = true;
    el.count.textContent = '요구사항 ' + r.requirements.length + '건';
    el.copy.disabled = false;

    var notes = [];
    if (!r.requirements.length) notes.push(['', '<b>요구사항을 찾지 못했습니다</b> · 왼쪽 문장 구분에서 요구사항 문장을 지정해 주세요.']);
    if (r.counts.question) notes.push(['info', '고객이 질문한 내용 ' + r.counts.question + '건은 [고객 문의 사항]에 따로 모았습니다. 답변이 필요합니다.']);
    if (el.optCheck.checked && r.requirements.length) notes.push(['info', '[확인 필요 사항]은 원문에 없는 내용을 정하지 않고, 고객에게 확인할 질문으로만 남긴 것입니다.']);
    el.notices.innerHTML = notes.map(function (n) { return '<div class="notice ' + n[0] + '">' + n[1] + '</div>'; }).join('');
  }

  function refresh() {
    if (state.dirty) { el.stale.hidden = false; return; }
    render();
  }

  function generate() {
    if (!el.input.value.trim()) { el.input.focus(); U.toast('고객 요청 내용을 먼저 입력해 주세요'); return; }
    if (state.dirty && !confirm('직접 수정한 결과가 새로 정리된 내용으로 바뀝니다. 계속할까요?')) return;
    state.dirty = false;
    analyze(); render();
  }

  var timer;
  el.input.addEventListener('input', function () {
    clearTimeout(timer);
    timer = setTimeout(function () { analyze(); refresh(); }, 350);
  });
  el.input.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); generate(); }
  });
  [el.optBg, el.optCheck, el.optSrc].forEach(function (x) { x.addEventListener('change', refresh); });
  el.generate.addEventListener('click', generate);
  el.regen.addEventListener('click', function () { state.dirty = false; render(); });
  el.preview.addEventListener('input', function () { state.dirty = true; });
  el.preview.addEventListener('paste', function (e) {
    e.preventDefault();
    document.execCommand('insertText', false, (e.clipboardData || window.clipboardData).getData('text'));
  });
  el.copy.addEventListener('click', function () {
    U.copyText((el.preview.innerText || '').replace(/ /g, ' ').replace(/\n{3,}/g, '\n\n').trim());
  });
  el.sample.addEventListener('click', function () {
    el.input.value = SAMPLE; state.overrides = {}; state.dirty = false;
    analyze(); render();
  });
  el.clear.addEventListener('click', function () {
    if (el.input.value && !confirm('입력 내용과 정리 결과를 모두 지울까요?')) return;
    el.input.value = ''; state.overrides = {}; state.dirty = false;
    analyze(); render(); el.input.focus();
  });

  renderSummary();
  showTab(location.hash === '#req' ? 'req' : 'reply');
})();
