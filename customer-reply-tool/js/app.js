/* 화면 동작 — 입력 → 분류 → 답변 정리 → 미리보기 → 복사
 * 입력 내용은 메모리에만 있고, 어떤 저장소나 서버에도 저장/전송하지 않습니다. */
(function () {
  'use strict';
  var E = window.ReplyEngine;
  var $ = function (id) { return document.getElementById(id); };

  var el = {
    input: $('input'), customerName: $('customerName'), sender: $('sender'),
    optApology: $('optApology'), optPlain: $('optPlain'),
    generate: $('generateBtn'), sample: $('sampleBtn'), clear: $('clearBtn'),
    summary: $('summary'), items: $('items'), itemsEmpty: $('itemsEmpty'),
    seg: $('formatSeg'), notices: $('notices'), stale: $('staleBar'), regen: $('regenBtn'),
    preview: $('preview'), count: $('count'), copy: $('copyBtn'), toast: $('toast')
  };

  var state = {
    items: [],
    overrides: {},   // 문장 원문 → { category, include } (사용자가 직접 바꾼 값 유지)
    format: 'polite',
    dirty: false     // 미리보기를 직접 수정했는지
  };

  var SAMPLE = [
    '고객이 엑셀 다운로드 버튼을 누르면 파일이 안 받아진다고 문의함.',
    '로그 확인해보니 다운로드 요청 시 파일 생성 단계에서 타임아웃이 발생하고 있었음.',
    '조회 기간이 1년 이상이면 데이터가 많아서 처리 시간이 길어지는 것 같음.',
    '임시로 서버 타임아웃 설정을 60초에서 180초로 늘려서 배포함.',
    '고객에게 조회 기간을 6개월 이하로 나눠서 다운로드하라고 안내 필요'
  ].join('\n');

  /* ---------- 분석 ---------- */
  function analyze() {
    var items = E.analyze(el.input.value);
    items.forEach(function (it) {
      var o = state.overrides[it.text];
      if (o) { it.category = o.category; it.include = o.include; }
    });
    state.items = items;
    renderItems();
  }

  function opts() {
    return {
      format: state.format,
      customerName: el.customerName.value,
      sender: el.sender.value,
      apology: el.optApology.checked,
      plainTerms: el.optPlain.checked
    };
  }

  /* ---------- 분류 목록 ---------- */
  function renderItems() {
    var items = state.items;
    el.itemsEmpty.hidden = items.length > 0;
    el.items.innerHTML = '';

    items.forEach(function (it) {
      var li = document.createElement('li');
      li.className = 'item' + (it.include ? '' : ' off');
      li.style.setProperty('--cat', 'var(--c-' + it.category + ')');

      var sel = document.createElement('select');
      sel.setAttribute('aria-label', '분류 항목');
      E.CATEGORIES.forEach(function (c) {
        var op = document.createElement('option');
        op.value = c.id; op.textContent = c.label;
        if (c.id === it.category) op.selected = true;
        sel.appendChild(op);
      });
      sel.addEventListener('change', function () {
        it.category = sel.value;
        saveOverride(it);
        renderItems();
        refreshReply();
      });

      var body = document.createElement('div');
      var txt = document.createElement('div');
      txt.className = 'txt';
      txt.textContent = it.text;
      body.appendChild(txt);
      var badges = [];
      if (it.uncertain) badges.push(['uncertain', '추정 표현 → 확정 표현으로 쓰지 않음']);
      if (it.internal) badges.push(['internal', '내부 정보일 수 있음 · 전달 여부 확인']);
      if (it.confidence === 'low' && it.category === it.autoCategory) badges.push(['low', '자동 분류 불확실']);
      if (it.category !== it.autoCategory) badges.push(['', '직접 지정']);
      if (badges.length) {
        var b = document.createElement('div');
        b.className = 'badges';
        badges.forEach(function (x) {
          var s = document.createElement('span');
          s.className = 'badge ' + x[0];
          s.textContent = x[1];
          b.appendChild(s);
        });
        body.appendChild(b);
      }

      var incl = document.createElement('label');
      incl.className = 'incl';
      incl.title = '답변에 포함';
      var cb = document.createElement('input');
      cb.type = 'checkbox'; cb.checked = it.include;
      cb.setAttribute('aria-label', '답변에 포함');
      cb.addEventListener('change', function () {
        it.include = cb.checked;
        saveOverride(it);
        renderItems();
        refreshReply();
      });
      incl.appendChild(cb);

      li.appendChild(sel); li.appendChild(body); li.appendChild(incl);
      el.items.appendChild(li);
    });

    renderSummary();
  }

  function saveOverride(it) {
    state.overrides[it.text] = { category: it.category, include: it.include };
  }

  function renderSummary() {
    var counts = {};
    E.CATEGORIES.forEach(function (c) { counts[c.id] = 0; });
    state.items.forEach(function (it) { if (it.include) counts[it.category]++; });
    var has = state.items.length > 0;
    el.summary.innerHTML = '';
    E.CATEGORIES.forEach(function (c) {
      var n = counts[c.id];
      var d = document.createElement('div');
      var cls = 'sum';
      var val;
      if (n) val = n + '문장';
      else if (!has) val = '–';
      else if (c.required) { val = '추가 확인 필요'; cls += ' need'; }
      else { val = '없음 (선택)'; cls += ' opt'; }
      d.className = cls;
      d.innerHTML = '<div class="name"><i style="background:var(--c-' + c.id + ')"></i></div><div class="val"></div>';
      d.querySelector('.name').appendChild(document.createTextNode(c.label));
      d.querySelector('.val').textContent = val;
      el.summary.appendChild(d);
    });
  }

  /* ---------- 답변 ---------- */
  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function toHtml(text) {
    return escapeHtml(text)
      .replace(/\[추가 확인 필요:[^\]]*\]/g, '<span class="need">$&</span>')
      .replace(/([^\n.]*?(?:것으로 (?:보입니다|추정됩니다)|가능성이 있습니다)\.)/g, '<span class="est">$1</span>');
  }

  function renderReply() {
    var notices = [];
    if (!state.items.length) {
      el.preview.innerHTML = '';
      el.notices.innerHTML = '';
      updateCount();
      return;
    }
    var r = E.buildReply(state.items, opts());
    el.preview.innerHTML = toHtml(r.text);
    state.dirty = false;
    el.stale.hidden = true;

    if (r.missing.length) notices.push(['', '<b>추가 확인 필요</b> · ' + escapeHtml(r.missing.join(', ')) + ' 항목이 입력에 없습니다. 노란 표시 부분을 채우거나 지운 뒤 보내 주세요.']);
    if (r.uncertainCount) notices.push(['info', '추정 표현 ' + r.uncertainCount + '건은 확정적으로 쓰지 않고 “~로 보입니다 / 추정됩니다”로 정리했습니다.']);
    if (r.internalCount) notices.push(['', '내부 정보로 보이는 문장 ' + r.internalCount + '건이 포함되어 있습니다. 고객에게 전달해도 되는지 확인해 주세요.']);
    el.notices.innerHTML = notices.map(function (n) {
      return '<div class="notice ' + n[0] + '">' + n[1] + '</div>';
    }).join('');
    updateCount();
  }

  // 입력/옵션 변경 시: 직접 수정한 미리보기는 덮어쓰지 않음
  function refreshReply() {
    if (state.dirty) { el.stale.hidden = false; return; }
    renderReply();
  }

  function updateCount() {
    var t = previewText();
    el.count.textContent = t.length.toLocaleString() + '자';
    el.copy.disabled = !t.trim();
  }

  function previewText() {
    return (el.preview.innerText || '').replace(/ /g, ' ').replace(/\n{3,}/g, '\n\n').trim();
  }

  /* ---------- 복사 ---------- */
  function copy() { copyText(previewText()); }
  function copyText(text) {
    if (!text) return;
    var done = function () { toast('답변이 복사되었습니다'); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text) ? done() : toast('복사하지 못했습니다. 직접 선택해 복사해 주세요'); });
    } else {
      fallbackCopy(text) ? done() : toast('복사하지 못했습니다. 직접 선택해 복사해 주세요');
    }
  }
  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    return ok;
  }

  var toastTimer;
  function toast(msg) {
    el.toast.textContent = msg;
    el.toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.toast.classList.remove('show'); }, 1800);
  }

  window.UIUtil = { copyText: copyText, toast: toast, escapeHtml: escapeHtml };

  /* ---------- 이벤트 ---------- */
  var timer;
  el.input.addEventListener('input', function () {
    clearTimeout(timer);
    timer = setTimeout(function () { analyze(); refreshReply(); }, 350);
  });
  [el.customerName, el.sender].forEach(function (x) {
    x.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(refreshReply, 250); });
  });
  [el.optApology, el.optPlain].forEach(function (x) { x.addEventListener('change', refreshReply); });

  function generate() {
    clearTimeout(timer);
    if (!el.input.value.trim()) { el.input.focus(); toast('먼저 확인 결과와 조치 내용을 입력해 주세요'); return; }
    if (state.dirty && !confirm('직접 수정한 미리보기 내용이 새로 생성된 답변으로 바뀝니다. 계속할까요?')) return;
    state.dirty = false;
    analyze();
    renderReply();
  }
  el.generate.addEventListener('click', generate);
  el.regen.addEventListener('click', function () { state.dirty = false; renderReply(); });
  el.input.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); generate(); }
  });

  el.seg.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-format]');
    if (!b) return;
    if (state.dirty && !confirm('직접 수정한 내용이 선택한 형식의 답변으로 바뀝니다. 계속할까요?')) return;
    state.format = b.getAttribute('data-format');
    Array.prototype.forEach.call(el.seg.querySelectorAll('button'), function (x) {
      x.setAttribute('aria-checked', String(x === b));
    });
    state.dirty = false;
    renderReply();
  });

  el.preview.addEventListener('input', function () {
    state.dirty = true;
    updateCount();
  });
  // 붙여넣기는 서식 없이 텍스트로
  el.preview.addEventListener('paste', function (e) {
    e.preventDefault();
    var t = (e.clipboardData || window.clipboardData).getData('text');
    document.execCommand('insertText', false, t);
  });

  el.copy.addEventListener('click', copy);

  el.sample.addEventListener('click', function () {
    el.input.value = SAMPLE;
    state.overrides = {};
    state.dirty = false;
    analyze(); renderReply();
  });
  el.clear.addEventListener('click', function () {
    if (el.input.value && !confirm('입력 내용과 미리보기를 모두 지울까요?')) return;
    el.input.value = ''; el.customerName.value = ''; el.sender.value = '';
    state.overrides = {}; state.dirty = false;
    analyze(); renderReply();
    el.input.focus();
  });

  renderSummary();
  updateCount();
})();
