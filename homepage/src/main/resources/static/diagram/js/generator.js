/*
 * 업무 도식화 도구 - Mermaid 코드 생성기
 * 동일한 업무 정보(info + steps)를 기반으로 고객 설명 모드 / 개발자 설명 모드의 도식을 만든다.
 */
(function (global) {
  'use strict';
  var M = global.FlowModel;

  var TYPE_NAMES = {
    process: '업무 처리 흐름도',
    role: '역할별 업무 흐름도',
    screen: '화면 이동 흐름도',
    compare: '변경 전·후 비교도',
    condition: '조건별 처리 결과 도식'
  };

  var STYLE = {
    customer: [
      'classDef start fill:#1f7a4d,stroke:#14583a,color:#ffffff,font-weight:bold',
      'classDef finish fill:#33415c,stroke:#1f2a3d,color:#ffffff,font-weight:bold',
      'classDef step fill:#eef4ff,stroke:#3b6fd8,color:#14213d',
      'classDef ask fill:#fff6db,stroke:#d99a00,color:#3d2e00',
      'classDef warn fill:#fdecec,stroke:#d14343,color:#5c1111',
      'classDef sys fill:#f1f3f5,stroke:#8a94a6,color:#3a4150,stroke-dasharray:4 3',
      'classDef scr fill:#eafaf1,stroke:#2e9e63,color:#0f3d26',
      'classDef added fill:#e3f6e9,stroke:#2e9e63,color:#0f3d26,font-weight:bold',
      'classDef removed fill:#f4f4f5,stroke:#a1a1aa,color:#71717a,stroke-dasharray:5 4',
      'classDef cont fill:#ffffff,stroke:#8a94a6,color:#3a4150,stroke-dasharray:3 3'
    ],
    developer: [
      'classDef start fill:#1f7a4d,stroke:#14583a,color:#ffffff',
      'classDef finish fill:#33415c,stroke:#1f2a3d,color:#ffffff',
      'classDef step fill:#ffffff,stroke:#3b6fd8,color:#14213d',
      'classDef ask fill:#fff6db,stroke:#d99a00,color:#3d2e00',
      'classDef auth fill:#f3e8ff,stroke:#8b5cf6,color:#2e1065',
      'classDef warn fill:#fdecec,stroke:#d14343,color:#5c1111',
      'classDef data fill:#e0f2fe,stroke:#0284c7,color:#0c2d48',
      'classDef integ fill:#fef3c7,stroke:#b45309,color:#3b1f02',
      'classDef sys fill:#f1f3f5,stroke:#8a94a6,color:#3a4150',
      'classDef scr fill:#eafaf1,stroke:#2e9e63,color:#0f3d26',
      'classDef added fill:#e3f6e9,stroke:#2e9e63,color:#0f3d26',
      'classDef removed fill:#f4f4f5,stroke:#a1a1aa,color:#71717a,stroke-dasharray:5 4',
      'classDef cont fill:#ffffff,stroke:#8a94a6,color:#3a4150,stroke-dasharray:3 3'
    ]
  };

  function header(dir) {
    return [
      '%%{init: {"theme": "base", "htmlLabels": false, "markdownAutoWrap": false, "flowchart": {"htmlLabels": false, "wrappingWidth": 600, "curve": "basis", "nodeSpacing": 40, "rankSpacing": 48, "padding": 14}, ' +
      '"themeVariables": {"fontFamily": "Malgun Gothic, Apple SD Gothic Neo, Noto Sans KR, sans-serif", "fontSize": "15px", "lineColor": "#55607a", "edgeLabelBackground": "#ffffff", "clusterBkg": "#f8fafc", "clusterBorder": "#cbd5e1"}}}%%',
      'flowchart ' + (dir || 'TD')
    ];
  }

  /** Mermaid 라벨용 이스케이프 + 줄바꿈 */
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/#/g, '#35;')
      .replace(/"/g, '#quot;')
      .replace(/</g, '#lt;')
      .replace(/>/g, '#gt;')
      .replace(/[\[\]{}|]/g, function (c) { return '#' + c.charCodeAt(0) + ';'; });
  }

  function wrap(text, perLine, maxLines) {
    var words = String(text || '').replace(/\s+/g, ' ').trim().split(' ');
    var lines = [], cur = '';
    words.forEach(function (w) {
      while (w.length > perLine) {           // 공백 없는 긴 단어는 강제 분할
        if (cur) { lines.push(cur); cur = ''; }
        lines.push(w.slice(0, perLine)); w = w.slice(perLine);
      }
      if (!cur) cur = w;
      else if ((cur + ' ' + w).length <= perLine) cur += ' ' + w;
      else { lines.push(cur); cur = w; }
    });
    if (cur) lines.push(cur);
    if (lines.length > maxLines) {
      lines = lines.slice(0, maxLines);
      lines[maxLines - 1] = lines[maxLines - 1].replace(/.{0,1}$/, '') + '…';
    }
    return lines;
  }

  function label(text, opt, extra) {
    var lines = wrap(text, opt.perLine, opt.maxLines).map(esc);
    if (extra) {
      wrap(extra, opt.perLine + 4, opt.devLines).forEach(function (l) { lines.push(esc(l)); });
    }
    return '"' + (lines.join('<br/>') || ' ') + '"';
  }

  function options(mode, settings) {
    settings = settings || {};
    var customer = mode === 'customer';
    return {
      mode: mode,
      customer: customer,
      perLine: customer ? (settings.perLine || 14) : Math.max(20, (settings.perLine || 14) + 6),
      maxLines: customer ? 3 : 4,
      devLines: 3,
      maxNodes: customer ? (settings.maxNodes || 10) : Math.max(18, settings.maxNodes || 0),
      summarizeSystem: settings.summarizeSystem !== false
    };
  }

  function isNegative(t) { return /(오류|에러|실패|불가|반려|거절|취소|중단|부족|없음|안내|예외|exception|error)/i.test(t || ''); }

  /** 모드에 맞는 문구 */
  function stepText(step, opt) {
    var t = step.text || '';
    if (!opt.customer) return t;
    if (step.type === 'error') return M.TECH_DETECT.test(t) || /(오류|에러|exception|error)/i.test(t) ? M.friendlyError(t) : M.customerizeText(t);
    if (step.type === 'auth') {
      var c = M.customerizeText(t);
      return M.TECH_DETECT.test(t) || !c ? '이용 권한이 있나요?' : c;
    }
    return M.customerizeText(t) || '시스템이 처리';
  }

  function branchText(t, opt) {
    if (!t) return '';
    if (!opt.customer) return t;
    if (/(오류|에러|exception|error|코드)/i.test(t)) return M.friendlyError(t);
    return M.customerizeText(t);
  }

  function question(t, opt) {
    t = String(t || '').trim();
    if (!t) return '확인되었나요?';
    if (opt.customer && !/\?$/.test(t)) t = t + '?';
    return t;
  }

  /**
   * 화면에 표시할 단계 목록을 만든다.
   * 고객 모드: 고객 표시 해제 단계 숨김, 연속된 시스템 내부 단계는 한 단계로 요약.
   * 반환: [{ step, idx(원본 1-based) }]
   */
  function visibleSteps(steps, opt) {
    var out = [];
    steps.forEach(function (s, i) {
      var item = { step: s, idx: i + 1 };
      if (!opt.customer) { out.push(item); return; }
      if (s.type === 'section') { out.push(item); return; }
      if (s.showCustomer) { out.push(item); return; }
      if (!opt.summarizeSystem) return;
      var prev = out[out.length - 1];
      if (prev && prev.summary) { prev.covers.push(i + 1); return; }
      out.push({ step: M.newStep({ type: 'process', role: '시스템', text: '시스템이 자동으로 처리' }), idx: i + 1, summary: true, covers: [i + 1] });
    });
    return out;
  }

  /** 섹션 또는 최대 노드 수 기준으로 페이지 분할 */
  function paginate(items, opt, baseTitle) {
    var pages = [], cur = { title: '', items: [] };
    var hasSection = items.some(function (it) { return it.step.type === 'section'; });
    items.forEach(function (it) {
      if (it.step.type === 'section') {
        if (cur.items.length || cur.title) pages.push(cur);
        cur = { title: it.step.text, items: [] };
        return;
      }
      cur.items.push(it);
    });
    if (cur.items.length || cur.title) pages.push(cur);
    if (!pages.length) pages.push({ title: '', items: [] });

    var out = [];
    pages.forEach(function (p) {
      if (p.items.length <= opt.maxNodes) { out.push(p); return; }
      // 조건 단계가 페이지 경계에 걸리지 않도록 자르기
      var chunk = [];
      p.items.forEach(function (it) {
        chunk.push(it);
        if (chunk.length >= opt.maxNodes) { out.push({ title: p.title, items: chunk }); chunk = []; }
      });
      if (chunk.length) out.push({ title: p.title, items: chunk });
    });
    var total = out.length;
    out.forEach(function (p, i) {
      p.no = i + 1; p.total = total;
      p.title = (p.title || baseTitle) + (total > 1 && !hasSection ? ' (' + (i + 1) + '/' + total + ')' : '');
    });
    return out;
  }

  function nodeDef(id, shape, lbl) {
    switch (shape) {
      case 'stadium': return id + '([' + lbl + '])';
      case 'diamond': return id + '{' + lbl + '}';
      case 'cyl': return id + '[(' + lbl + ')]';
      case 'sub': return id + '[[' + lbl + ']]';
      case 'para': return id + '[/' + lbl + '/]';
      case 'round': return id + '(' + lbl + ')';
      default: return id + '[' + lbl + ']';
    }
  }

  /** 단계 유형별 노드 모양/스타일 */
  function look(step, opt, summary) {
    if (summary) return { shape: 'rect', cls: 'sys' };
    var t = step.type;
    if (t === 'decision') return { shape: 'diamond', cls: 'ask' };
    if (t === 'auth') return { shape: 'diamond', cls: opt.customer ? 'ask' : 'auth' };
    if (t === 'error') return { shape: 'rect', cls: 'warn' };
    if (opt.customer) {
      if (t === 'data' || t === 'integration') return { shape: 'rect', cls: 'sys' };
      if (t === 'screen') return { shape: 'rect', cls: 'scr' };
      return { shape: 'rect', cls: 'step' };
    }
    if (t === 'data') return { shape: 'cyl', cls: 'data' };
    if (t === 'integration') return { shape: 'sub', cls: 'integ' };
    if (t === 'screen') return { shape: 'para', cls: 'scr' };
    return { shape: 'rect', cls: 'step' };
  }

  function devExtra(step, opt) {
    if (opt.customer) return '';
    var parts = [];
    if (step.screen) parts.push('화면: ' + step.screen);
    if (step.devText) parts.push('※ ' + step.devText);
    return parts.join(' / ');
  }

  /**
   * 업무 처리 흐름 / 역할별 흐름 공통 그래프 빌더
   * lanes=true 이면 담당자별 subgraph 로 영역을 나눈다.
   */
  function buildFlow(info, steps, mode, settings, lanes) {
    var opt = options(mode, settings);
    var base = (info.title || '업무') + ' ' + (lanes ? TYPE_NAMES.role : TYPE_NAMES.process);
    var pages = paginate(visibleSteps(steps, opt), opt, base);

    return pages.map(function (page) {
      var lines = header('TD');
      var defs = [];            // { lane, def, cls }
      var edges = [];
      var gotos = [];
      var idOf = {};            // 원본 idx → node id
      var startLbl = page.no === 1
        ? (info.startCond ? '시작: ' + branchText(info.startCond, opt) : '시작')
        : '이전 장에서 계속';
      var endLbl = page.no === page.total
        ? (info.endCond ? '종료: ' + branchText(info.endCond, opt) : '종료')
        : '다음 장으로 계속';
      defs.push({ lane: null, def: nodeDef('START', 'stadium', label(startLbl, opt)), cls: page.no === 1 ? 'start' : 'cont' });
      var endUsed = false;
      var pending = [{ from: 'START', lbl: '' }];
      var n = 0;

      var lastLane = null;
      function laneOf(step, summary) {
        if (!lanes) return null;
        var ln;
        if (summary || step.type === 'data' || step.type === 'integration') ln = step.role || '시스템';
        else ln = step.role || lastLane || M.splitList(info.owners)[0] || '담당자';
        lastLane = ln;
        return ln;
      }
      function link(from, to, lbl, dotted) {
        var arrow = dotted ? '-.->' : '-->';
        edges.push('  ' + from + ' ' + (lbl ? arrow + '|' + esc(lbl) + '| ' : arrow + ' ') + to);
      }
      function flowTo(from, lbl, flow, nextPending) {
        if (flow === 'end') { link(from, 'END', lbl); endUsed = true; }
        else if (flow && flow.indexOf('goto:') === 0) gotos.push({ from: from, lbl: lbl, target: parseInt(flow.slice(5), 10) });
        else nextPending.push({ from: from, lbl: lbl });
      }

      page.items.forEach(function (it) {
        n += 1;
        var s = it.step;
        var id = 'N' + n;
        (it.covers || [it.idx]).forEach(function (k) { idOf[k] = id; });
        var lk = look(s, opt, it.summary);
        var isAsk = s.type === 'decision' || s.type === 'auth';
        var text = isAsk ? question(stepText(s, opt), opt) : stepText(s, opt);
        var lane = laneOf(s, it.summary);
        defs.push({ lane: lane, def: nodeDef(id, lk.shape, label(text, opt, devExtra(s, opt))), cls: lk.cls });
        pending.forEach(function (p) { link(p.from, id, p.lbl); });
        pending = [];

        if (!isAsk) { pending.push({ from: id, lbl: '' }); return; }

        var yes = branchText(s.yesText, opt);
        var no = branchText(s.noText, opt);
        var next = [];
        if (yes) {
          var yid = id + 'Y';
          defs.push({ lane: lane, def: nodeDef(yid, 'rect', label(yes, opt)), cls: s.yesFlow === 'end' && isNegative(s.yesText) ? 'warn' : 'step' });
          link(id, yid, '예');
          flowTo(yid, '', s.yesFlow, next);
        } else flowTo(id, '예', s.yesFlow, next);
        if (no) {
          var nid = id + 'N';
          defs.push({ lane: lane, def: nodeDef(nid, 'rect', label(no, opt)), cls: isNegative(s.noText) || s.noFlow !== 'continue' ? 'warn' : 'step' });
          link(id, nid, '아니오');
          flowTo(nid, '', s.noFlow, next);
        } else flowTo(id, '아니오', s.noFlow, next);
        pending = next;
      });

      gotos.forEach(function (g) {
        var target = idOf[g.target];
        if (!target) {
          // 숨김/다른 장의 단계이면 가장 가까운 다음 단계, 없으면 종료로 연결
          for (var k = g.target; k <= steps.length && !target; k++) target = idOf[k];
        }
        if (target) link(g.from, target, g.lbl || '다시 진행', true);
        else { link(g.from, 'END', g.lbl); endUsed = true; }
      });
      pending.forEach(function (p) { link(p.from, 'END', p.lbl); endUsed = true; });
      if (endUsed || !page.items.length) {
        defs.push({ lane: null, def: nodeDef('END', 'stadium', label(endLbl, opt)), cls: page.no === page.total ? 'finish' : 'cont' });
        if (!page.items.length) link('START', 'END', '');
      }

      // 노드 정의 출력 (역할별이면 subgraph)
      if (lanes) {
        var order = [], byLane = {};
        defs.forEach(function (d) {
          if (d.lane == null) return;
          if (!byLane[d.lane]) { byLane[d.lane] = []; order.push(d.lane); }
          byLane[d.lane].push(d);
        });
        defs.filter(function (d) { return d.lane == null && d.def.indexOf('START') === 0; }).forEach(function (d) { lines.push('  ' + d.def); });
        order.forEach(function (ln, i) {
          lines.push('  subgraph L' + (i + 1) + '["' + esc(ln) + '"]');
          lines.push('    direction TB');
          byLane[ln].forEach(function (d) { lines.push('    ' + d.def); });
          lines.push('  end');
        });
        defs.filter(function (d) { return d.lane == null && d.def.indexOf('START') !== 0; }).forEach(function (d) { lines.push('  ' + d.def); });
      } else {
        defs.forEach(function (d) { lines.push('  ' + d.def); });
      }
      lines = lines.concat(edges);
      lines = lines.concat(classLines(defs, opt));
      return { title: page.title, code: lines.join('\n') };
    });
  }

  function classLines(defs, opt) {
    var out = STYLE[opt.customer ? 'customer' : 'developer'].map(function (l) { return '  ' + l; });
    var by = {};
    defs.forEach(function (d) {
      var id = d.def.match(/^[A-Za-z0-9_]+/)[0];
      (by[d.cls] = by[d.cls] || []).push(id);
    });
    Object.keys(by).forEach(function (c) { out.push('  class ' + by[c].join(',') + ' ' + c); });
    return out;
  }

  /** 화면 이동 흐름도 */
  function buildScreen(info, steps, mode, settings) {
    var opt = options(mode, settings);
    var known = M.splitList(info.screens);
    var screenCount = {};
    steps.forEach(function (s) { if (s.screen) screenCount[s.screen] = 1; });
    known.forEach(function (k) { screenCount[k] = 1; });
    var lines = header(Object.keys(screenCount).length > 3 ? 'TD' : 'LR');
    var defs = [], edges = [], ids = {}, n = 0;
    function sid(name) {
      if (!ids[name]) { n += 1; ids[name] = 'S' + n; defs.push({ def: nodeDef(ids[name], 'rect', label(name, opt)), cls: 'scr' }); }
      return ids[name];
    }
    var startLbl = info.startCond ? '시작: ' + branchText(info.startCond, opt) : '시작';
    defs.push({ def: nodeDef('START', 'stadium', label(startLbl, opt)), cls: 'start' });
    var cur = null, seen = {};
    steps.forEach(function (s) {
      if (s.type === 'section' || !s.screen) return;
      var to = sid(s.screen);
      var act = s.type === 'decision' || s.type === 'auth' ? (branchText(s.yesText, opt) || '예') : stepText(s, opt);
      if (!opt.customer && s.devText) act += ' (' + s.devText + ')';
      act = wrap(act, opt.perLine + 4, 2).join('\n');
      var key = (cur || 'START') + '>' + to;
      if (cur !== to && !seen[key]) { edges.push('  ' + (cur || 'START') + ' -->|' + act.split('\n').map(esc).join('<br/>') + '| ' + to); seen[key] = 1; }
      cur = to;
      if ((s.type === 'decision' || s.type === 'auth') && s.noText) {
        var target = null;
        known.concat(Object.keys(ids)).forEach(function (k) { if (!target && k && s.noText.indexOf(k) >= 0) target = k; });
        var nlabel = '아니오: ' + wrap(branchText(s.noText, opt), opt.perLine + 6, 1)[0];
        if (target) edges.push('  ' + to + ' -.->|' + esc(nlabel) + '| ' + sid(target));
        else {
          var mid = to + 'M';
          defs.push({ def: nodeDef(mid, 'round', label(branchText(s.noText, opt), opt)), cls: 'warn' });
          edges.push('  ' + to + ' -.->|아니오| ' + mid);
        }
      }
    });
    if (!cur) {
      // 단계에 화면 정보가 없으면 관련 화면명 순서대로 연결
      known.forEach(function (k) { var t = sid(k); edges.push('  ' + (cur || 'START') + ' --> ' + t); cur = t; });
    }
    var endLbl = info.endCond ? '종료: ' + branchText(info.endCond, opt) : '종료';
    defs.push({ def: nodeDef('END', 'stadium', label(endLbl, opt)), cls: 'finish' });
    edges.push('  ' + (cur || 'START') + ' --> END');
    defs.forEach(function (d) { lines.push('  ' + d.def); });
    lines = lines.concat(edges, classLines(defs, opt));
    return [{ title: (info.title || '업무') + ' ' + TYPE_NAMES.screen, code: lines.join('\n') }];
  }

  function norm(t) { return String(t || '').replace(/[\s.,·]/g, '').replace(/(한다|합니다|함|됨)$/, ''); }

  /** 변경 전·후 비교도 */
  function buildCompare(info, steps, mode, settings) {
    var opt = options(mode, settings);
    var before = M.parseSimpleSteps(info.before);
    var after = M.parseSimpleSteps(info.after);
    var bn = before.map(norm), an = after.map(norm);
    var lines = header('LR');
    var defs = [], edges = [];
    function txt(t) { return opt.customer ? (M.customerizeText(t) || t) : t; }

    lines.push('  subgraph BEFORE["변경 전"]');
    lines.push('    direction TB');
    before.forEach(function (t, i) {
      var removed = an.indexOf(bn[i]) < 0;
      var d = { def: nodeDef('B' + (i + 1), 'rect', label((removed ? '(없어짐) ' : '') + txt(t), opt)), cls: removed ? 'removed' : 'step' };
      defs.push(d); lines.push('    ' + d.def);
      if (i) edges.push('  B' + i + ' --> B' + (i + 1));
    });
    if (!before.length) { defs.push({ def: 'B0["변경 전 업무 방식을 입력하세요"]', cls: 'cont' }); lines.push('    B0["변경 전 업무 방식을 입력하세요"]'); }
    lines.push('  end');
    lines.push('  subgraph AFTER["변경 후"]');
    lines.push('    direction TB');
    after.forEach(function (t, i) {
      var added = bn.indexOf(an[i]) < 0;
      var d = { def: nodeDef('A' + (i + 1), 'rect', label((added ? '(새로 추가) ' : '') + txt(t), opt)), cls: added ? 'added' : 'step' };
      defs.push(d); lines.push('    ' + d.def);
      if (i) edges.push('  A' + i + ' --> A' + (i + 1));
    });
    if (!after.length) { defs.push({ def: 'A0["변경 후 업무 방식을 입력하세요"]', cls: 'cont' }); lines.push('    A0["변경 후 업무 방식을 입력하세요"]'); }
    lines.push('  end');
    edges.push('  BEFORE ==>|바뀌는 점| AFTER');
    lines = lines.concat(edges, classLines(defs, opt));
    lines.push('  style BEFORE fill:#f8fafc,stroke:#a1a1aa');
    lines.push('  style AFTER fill:#f0fbf4,stroke:#2e9e63');
    return [{ title: (info.title || '업무') + ' ' + TYPE_NAMES.compare, code: lines.join('\n') }];
  }

  /** 조건별 처리 결과 도식 */
  function buildCondition(info, steps, mode, settings) {
    var opt = options(mode, settings);
    var conds = M.parseConditions(info.conditions);
    var lines = header('TD');
    if (!conds.length) {
      steps.forEach(function (s) {
        if (s.type === 'decision' || s.type === 'auth') conds.push({ cond: s.text, result: s.noText || '', yes: s.yesText, dev: s.devText, asked: true });
      });
    }
    var defs = [], edges = [];
    var startLbl = info.startCond ? branchText(info.startCond, opt) : '업무 요청';
    defs.push({ def: nodeDef('START', 'stadium', label(startLbl, opt)), cls: 'start' });
    var prev = 'START', prevLbl = '';
    conds.forEach(function (c, i) {
      var id = 'C' + (i + 1);
      var q = c.asked ? (opt.customer ? stepText({ type: 'decision', text: c.cond }, opt) : c.cond) : M.toQuestion(c.cond);
      if (opt.customer) q = question(M.customerizeText(q) || q, opt);
      defs.push({ def: nodeDef(id, 'diamond', label(q, opt, opt.customer ? '' : (c.dev || ''))), cls: 'ask' });
      edges.push('  ' + prev + ' -->' + (prevLbl ? '|' + prevLbl + '| ' : ' ') + id);
      // 조건 목록(조건 → 결과)은 "예"일 때 결과, 단계에서 가져온 조건은 "아니오"일 때 결과
      var res = c.result;
      if (res || !c.asked) {
        var rid = id + 'R';
        defs.push({ def: nodeDef(rid, 'rect', label(branchText(res, opt) || '별도 처리', opt)), cls: isNegative(res) ? 'warn' : 'step' });
        edges.push('  ' + id + ' -->|' + (c.asked ? '아니오' : '예') + '| ' + rid);
      }
      prev = id; prevLbl = c.asked ? '예' : '아니오';
    });
    var endLbl = info.endCond ? branchText(info.endCond, opt) : '정상 처리 완료';
    defs.push({ def: nodeDef('END', 'stadium', label(endLbl, opt)), cls: 'finish' });
    edges.push('  ' + prev + ' -->' + (prevLbl ? '|' + prevLbl + '| ' : ' ') + 'END');
    defs.forEach(function (d) { lines.push('  ' + d.def); });
    lines = lines.concat(edges, classLines(defs, opt));
    return [{ title: (info.title || '업무') + ' ' + TYPE_NAMES.condition, code: lines.join('\n') }];
  }

  /**
   * 진입점: 도식 유형 + 모드 → [{ title, code }]
   */
  function generate(kind, info, steps, mode, settings) {
    switch (kind) {
      case 'role': return buildFlow(info, steps, mode, settings, true);
      case 'screen': return buildScreen(info, steps, mode, settings);
      case 'compare': return buildCompare(info, steps, mode, settings);
      case 'condition': return buildCondition(info, steps, mode, settings);
      default: return buildFlow(info, steps, mode, settings, false);
    }
  }

  global.FlowGenerator = { generate: generate, TYPE_NAMES: TYPE_NAMES, wrap: wrap, esc: esc };
})(window);
