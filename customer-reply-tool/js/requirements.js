/*!
 * 고객 요구사항 요약·정리 엔진 (규칙 기반)
 * - 고객이 보낸 서술형 요청을 개발자가 보기 쉬운 형태(요약 / 세부 요구사항 / 확인 필요 사항)로 정리합니다.
 * - 고객이 말하지 않은 요구사항은 만들지 않습니다. 모호한 부분은 '확인 필요 사항'으로 질문 형태로만 남깁니다.
 * - 외부 API / 네트워크 / 저장소를 사용하지 않습니다.
 */
(function (global) {
  'use strict';

  /* ---------- 한글 유틸 ---------- */
  function jong(ch) {
    var c = (ch || '').charCodeAt(0) - 0xac00;
    if (c < 0 || c > 11171) return -1;
    return c % 28;
  }
  // 받침에 맞는 조사 선택: pp(word, '을', '를')
  function pp(word, withJong, noJong) {
    var j = jong(word.slice(-1));
    if (j < 0) return /[0-9LMNRlmnr]$/.test(word) ? withJong : noJong;
    return j ? withJong : noJong;
  }
  function stripParticle(w) {
    return w.replace(/(?:에서는|에서|으로|로는|에는|에|은|는|이|가|을|를|의|도|만)$/, '');
  }

  /* ---------- 분리 ---------- */
  var SEP = '\u0001';
  var LEAD_CONJ = /^(?:그리고|또한|또|추가로|아울러|그리고\s*나서|그 다음|마지막으로|참고로|혹시)\s*,?\s*/;

  function splitClauses(text) {
    if (!text) return [];
    var t = String(text).replace(/\r/g, '').replace(/[“”"]/g, '');
    var out = [];
    t.split(/\n+/).forEach(function (line) {
      line = line
        .replace(/([.!?。])\s+/g, '$1' + SEP)
        .replace(/(니다|세요|어요|아요|해요|돼요|네요|군요)\s+(?=[가-힣A-Za-z0-9])/g, '$1' + SEP)
        // "~처리하고, 취소한 건은 ~" 처럼 요청이 이어지는 경우 분리
        .replace(/((?:하|되|처리하|해주시|해 주시)고),\s*/g, '$1' + SEP)
        .replace(/,?\s*그리고\s+/g, SEP)
        .replace(/,?\s*또한\s+/g, SEP);
      line.split(SEP).forEach(function (p) {
        p = p.replace(/^\s*(?:[-*•·▶▷○●■□◆◇※>]+|\d{1,2}[.)](?=\s)|[①-⑳])\s*/, '')
          .replace(LEAD_CONJ, '').trim();
        if (p.replace(/[\s.。!?~]/g, '').length >= 2) out.push(p);
      });
    });
    return out;
  }

  /* ---------- 문장 유형 ---------- */
  var REQUEST_RE = /(해\s?주|해\s?줬|해\s?주시|되도록|하도록|없도록|있도록|않도록|좋겠|원합니다|원해요|바랍니다|부탁|필요|했으면|됐으면|되었으면|하게\s|게\s?해|처리하고|처리해|추가해|변경해|바꿔|가능하게|면 좋|주세요|않게|못하게|요청드|해야\s?(?:합니다|해요|할 것))/;
  var QUESTION_RE = /(\?|가능한가요|가능할까요|되나요|있나요|있을까요|인가요|궁금|어떻게\s?(?:하|되)나요|알려\s?주세요)/;
  var BACKGROUND_RE = /(현재|지금|기존|불편|번거|매번|일일이|힘들|어렵|헷갈|오래\s?걸|하고\s?있는데|있는데|인데|느려|느리|안\s?돼|안\s?되|오류가|에러가|문제가)/;

  function kindOf(s) {
    if (QUESTION_RE.test(s) && !/(해\s?주세요|좋겠)/.test(s)) return 'question';
    if (REQUEST_RE.test(s)) return 'request';
    if (BACKGROUND_RE.test(s)) return 'background';
    return 'request';
  }

  /* ---------- 문맥 정보 ---------- */
  var STOP_DOMAIN = /^(?:현재|지금|이|그|저|해당|처음|모든|각|이번|다음|기존|새|메인|첫)$/;

  function context(text) {
    var ctx = { domain: '', screen: '', manualFields: [] };
    var re = /((?:[가-힣A-Za-z0-9]+\s)?[가-힣A-Za-z0-9]+)\s?(화면|페이지|메뉴|팝업|창|탭)(?=[^가-힣]|에|에서|의|은|는|을|를|이|가|$)/g, m;
    while ((m = re.exec(text))) {
      var words = m[1].split(' ');
      if (words.length > 1 && (STOP_DOMAIN.test(words[0]) || /(?:에서|에|을|를|은|는|도|의|이|가|고|서|데)$/.test(words[0]))) words.shift();
      var w = words.join(' ');
      if (STOP_DOMAIN.test(w) || /(?:에서|에|을|를|은|는|도|의)$/.test(w)) continue;
      ctx.domain = w; ctx.screen = m[2];
      break;
    }
    var fr = /([가-힣A-Za-z0-9]+?)(?:을|를)\s*(?:매번\s*)?(?:직접|수동으로|일일이|손으로|매번)\s*(?:입력|선택|작성)/g;
    while ((m = fr.exec(text))) ctx.manualFields.push(m[1]);
    return ctx;
  }

  /* ---------- 대상(주제어) 추출 ---------- */
  var STATUS = '완료|취소|승인|반려|접수|삭제|마감|만료|보류|진행|처리|확정|종료|대기|임시저장|저장';
  var ADVERB = /^(?:이미|그리고|또|또한|현재|지금|혹시|만약|만일|특히|그냥|일단|기존에|이전에|예전에)$/;

  function topicPhrase(clause) {
    var tokens = clause.split(/\s+/);
    for (var i = 0; i < tokens.length; i++) {
      var tk = tokens[i];
      if (tk.length < 2 || !/(?:은|는)$/.test(tk)) continue;
      if (/^(?:저는|제가|저희는|우리는|지금은|현재는|요즘은|이번에는|앞으로는)$/.test(tk)) continue;
      var start = Math.max(0, i - 3);
      var parts = tokens.slice(start, i + 1);
      while (parts.length && ADVERB.test(parts[0])) parts.shift();
      // 앞쪽에 다른 절이 섞이면 잘라냄 (쉼표, 종결어미)
      for (var k = parts.length - 2; k >= 0; k--) {
        if (/[,.]$|(?:고|며|서|데)$/.test(parts[k])) { parts = parts.slice(k + 1); break; }
      }
      var raw = parts.join(' ');
      return { raw: raw, phrase: raw.replace(/(?:은|는)$/, '') };
    }
    return null;
  }

  // "신청이 완료된 건" → { title: '완료된 신청 건', desc: '신청 상태가 완료인 데이터' }
  function normalizeTarget(phrase, ctx) {
    if (!phrase) return null;
    var re = new RegExp('^(?:(\\S+?)(?:이|가)\\s)?(' + STATUS + ')(?:된|한|처리된|된\\s?상태의?|상태인|상태의)\\s?(건|데이터|항목|내역|목록|것|글|게시글|신청서)$');
    var m = phrase.match(re);
    if (m) {
      var noun = m[1] || '';
      var unit = m[3] === '것' ? '건' : m[3];
      var titleNoun = noun || ctx.domain;
      return {
        title: m[2] + '된 ' + (titleNoun ? titleNoun + ' ' : '') + unit,
        desc: noun ? noun + ' 상태가 ' + m[2] + '인 데이터' : m[2] + ' 상태인 데이터',
        status: true
      };
    }
    return { title: phrase, desc: phrase, status: false };
  }

  function objectPhrase(clause) {
    var m = clause.match(/((?:[가-힣A-Za-z0-9]+\s)?[가-힣A-Za-z0-9]+?)(?:을|를)\s/);
    if (m) return stripParticle(m[1].replace(/^(?:이미|현재|지금|그리고)\s/, ''));
    m = clause.match(/((?:[가-힣A-Za-z0-9]+\s)?[가-힣A-Za-z0-9]+?)(?:이|가)\s/);
    if (m) return m[1].replace(/^(?:이미|현재|지금|그리고)\s/, '');
    return '';
  }

  /* ---------- 요구사항 유형 ---------- */
  var TYPES = [
    { id: 'auto', test: function (s) { return /(자동|기본값|디폴트|default|미리)/i.test(s) && /(입력|들어가|들어와|채워|세팅|설정|표시|선택)/.test(s); },
      summary: '입력 편의성 개선', check: '기본값이 들어간 뒤 사용자가 값을 직접 변경할 수 있어야 하는지' },
    { id: 'restrict', test: function (s) { return /(수정|삭제|변경|편집|입력|저장|취소)\S*\s*(?:할\s?수\s?없|하지\s?못|못\s?하|불가|안\s?되|막|제한|비활성|잠금|잠가)/.test(s) || /(?:수정|삭제|편집)\s?(?:불가|금지|제한)/.test(s); },
      summary: '수정 제한', check: '제한 범위(수정 외 삭제 포함 여부)와 관리자 등 예외 권한이 필요한지' },
    { id: 'hide', test: function (s) { return /(안\s?보이|보이지\s?않|숨기|숨김|노출되지|노출 안|빼\s?주|제외)/.test(s); },
      summary: '화면 표시 개선', check: '숨김 처리 시 조회·집계 대상에서도 제외해야 하는지' },
    { id: 'display', test: function (s) { return /(색|색상|색깔|강조|굵게|하이라이트|아이콘|배지|뱃지)/.test(s) || /(구분|따로|별도)\S*\s*(?:표시|보이|보여)/.test(s); },
      summary: '화면 표시 개선', check: '구분 표시 방식(색상, 아이콘 등)을 고객이 지정하는지' },
    { id: 'search', test: function (s) { return /(검색|조회\s?조건|필터|정렬|찾기)/.test(s); },
      summary: '조회 기능 개선', check: '조회 조건의 기본값과 정렬 기준' },
    { id: 'export', test: function (s) { return /(엑셀|다운로드|출력|인쇄|프린트|PDF)/i.test(s); },
      summary: '출력 기능 추가', check: '출력 항목과 파일 형식' },
    { id: 'validate', test: function (s) { return /(필수|검증|체크|경고|확인\s?메시지|알림창|막아|입력\s?못)/.test(s); },
      summary: '입력값 검증 강화', check: '검증 실패 시 표시할 메시지 문구' },
    { id: 'notify', test: function (s) { return /(알림|메일|문자|SMS|카톡|푸시|통보)/i.test(s); },
      summary: '알림 기능 추가', check: '알림 대상자와 발송 시점' },
    { id: 'perf', test: function (s) { return /(느리|느려|속도|오래\s?걸|빨리|빠르게)/.test(s); },
      summary: '성능 개선', check: '목표 처리 시간 기준' },
    { id: 'bug', test: function (s) { return /(오류|에러|안\s?되|안되|작동하지|동작하지|먹통|깨져|틀리)/.test(s); },
      summary: '오류 수정', check: '오류 재현 조건(발생 화면, 시점, 데이터)' },
    { id: 'add', test: function (s) { return /(추가|넣어|생기|만들어|신설|새로)/.test(s); },
      summary: '기능 추가', check: '추가 항목의 위치와 입력 형식' },
    { id: 'change', test: function (s) { return /(변경|바꿔|바꾸|수정해|고쳐)/.test(s); },
      summary: '기능 변경', check: '변경 전·후 기준' }
  ];

  function typeOf(s) {
    for (var i = 0; i < TYPES.length; i++) if (TYPES[i].test(s)) return TYPES[i];
    return { id: 'etc', summary: '요구사항 반영', check: '' };
  }

  var VAGUE = ['적당히', '알아서', '보기 좋게', '깔끔하게', '편하게', '예쁘게', '좀 더', '조금 더', '빠르게', '최대한', '웬만하면', '가능하면', '눈에 띄게', '다른 색'];

  /* ---------- 개발자용 문장으로 변환 ---------- */
  var PHRASE = [
    [/화면에\s*처음\s*(?:들어왔을|들어갔을|들어올|들어가면|진입했을|진입할|열었을|열)\s*때/g, '화면 최초 진입 시'],
    [/처음\s*(?:들어왔을|들어갔을|들어올|진입했을|진입할|열었을|열)\s*때/g, '최초 진입 시'],
    [/처음\s*(?:들어오면|들어가면|열면)/g, '최초 진입 시'],
    [/([가-힣]{2,})(?:할|했을|될|하실|되었을)\s*때/g, '$1 시'],
    [/([가-힣]{2,})하면(?=\s)/g, '$1 시'],
    [/다른\s*색(?:깔|상)?으로/g, '다른 색상으로'],
    [/(^|\s)좀\s+/g, '$1'],
    [/(^|\s)이미\s+/g, '$1'],
    [/\s{2,}/g, ' ']
  ];

  function toDevSentence(clause, target, ctx) {
    var s = clause.replace(LEAD_CONJ, '').replace(/[.!~…\s]+$/, '').trim();
    s = s.replace(/^(?:현재|지금|이미|좀)\s+/, '');
    if (target && target.raw && target.norm && target.norm.status) {
      s = s.replace(target.raw, target.norm.desc + pp(target.norm.desc, '은', '는'));
    }
    PHRASE.forEach(function (r) { s = s.replace(r[0], r[1]); });

    // "X가 자동으로 들어가도록" → "X를 기본값으로 설정"
    s = s.replace(/([가-힣A-Za-z0-9]+)(?:이|가)\s*자동으로\s*(?:들어가|들어오|입력되|채워지|세팅되|설정되|표시되|선택되)(?:도록|게)/,
      function (m, w) { return w + pp(w, '을', '를') + ' 기본값으로 설정'; });
    s = s.replace(/자동으로\s*(?:들어가|입력되|채워지|세팅되)(?:도록|게)/, '자동 입력되도록');
    // "다른 색상으로 표시되면" → "다른 색상으로 구분하여 표시되면"
    s = s.replace(/다른 색상으로\s*(?=표시|보이|나오)/, '다른 색상으로 구분하여 ');
    s = s.replace(/구분하여\s*(?:보이|나오)/, '구분하여 표시되');

    // 종결 표현 → "~한다"
    var END = [
      [/(?:안\s?보이게|보이지\s?않게|노출되지\s?않게|안\s?나오게)\s*(?:해\s?(?:주세요|주시기\s?바랍니다|주시면\s?좋겠습니다)|하면\s?좋겠습니다)$/, '표시하지 않는다'],
      [/\s*(?:처리)?해\s?(?:주시면|주셨으면)\s*(?:좋겠습니다|좋겠어요|합니다|해요|감사하겠습니다)$/, 'H'],
      [/\s*해\s?(?:주세요|줘요|주십시오|주시기\s?바랍니다|주실\s?수\s?있을까요|주시겠어요|달라)$/, 'H'],
      [/\s*처리해\s?(?:주세요|주시기\s?바랍니다)$/, ' 처리한다'],
      [/(?:하|해)면\s*좋겠(?:습니다|어요|다)$/, 'H'],
      [/했으면\s*(?:좋겠습니다|좋겠어요|합니다|해요)$/, 'H'],
      [/(?:되|돼)면\s*좋겠(?:습니다|어요|다)$/, 'D'],
      [/(?:되었|됐)으면\s*(?:좋겠습니다|좋겠어요|합니다|해요)$/, 'D'],
      [/(?:하|되)?게\s*해\s?(?:주세요|주시기\s?바랍니다)$/, '게 한다'],
      [/처리하고$/, '처리한다'],
      [/(?:하|되)고$/, '한다'],
      [/\s*부탁(?:드립니다|드려요|합니다|해요)$/, ' 처리한다'],
      [/(?:을|를)?\s*원(?:합니다|해요)$/, ' 기능을 제공한다'],
      [/필요(?:합니다|해요)$/, '필요하다'],
      [/주세요$/, '준다'],
      [/합니다$/, '한다'], [/됩니다$/, '된다'], [/입니다$/, '이다'], [/습니다$/, '다'], [/해요$/, '한다']
    ];
    // "X 기능이 있었으면 좋겠어요" → "X 기능을 제공한다"
    var have = s.match(/^(.*?)([가-힣A-Za-z0-9]+)(?:이|가)\s*(?:있었|있)으면\s*(?:좋겠(?:습니다|어요|다)|합니다|해요)$/);
    if (have) return have[1] + have[2] + pp(have[2], '을', '를') + ' 제공한다.';
    for (var i = 0; i < END.length; i++) {
      var re = END[i][0];
      if (!re.test(s)) continue;
      var rep = END[i][1];
      if (rep === 'H') {
        s = s.replace(re, '');
        s += /(?:도록|게)$/.test(s) ? ' 한다' : (/[가-힣A-Za-z0-9]$/.test(s) && !/다$/.test(s) ? '한다' : '');
      } else if (rep === 'D') {
        s = s.replace(re, '');
        // "표시되면 좋겠습니다" → "표시한다", "보이면" 계열은 "되도록 한다"
        s = /(?:구분하여 표시|표시|처리|변경|저장|반영)$/.test(s) ? s + '한다' : s + '되도록 한다';
      } else {
        s = s.replace(re, rep);
      }
      break;
    }
    s = s.replace(/\s{2,}/g, ' ').trim();
    return s ? s + '.' : s;
  }

  function toBackground(clause) {
    var s = clause.replace(/[.!~…\s]+$/, '').trim().replace(/^(?:현재|지금)\s+/, '');
    s = s.replace(/(하|되)고\s?있는데\s*/g, '$1고 있으며 ')
      .replace(/있는데\s*/g, '있으며 ')
      .replace(/인데\s*/g, '이며 ')
      .replace(/합니다$/, '함').replace(/됩니다$/, '됨').replace(/입니다$/, '임')
      .replace(/있습니다$/, '있음').replace(/없습니다$/, '없음').replace(/습니다$/, '음')
      .replace(/해요$/, '함').replace(/려요$/, '림').replace(/어요$/, '음').replace(/아요$/, '음').replace(/네요$/, '음');
    return s;
  }

  /* ---------- 제목 ---------- */
  function makeTitle(clause, type, target, ctx) {
    var t = target && target.norm ? target.norm.title : '';
    var obj = objectPhrase(clause);
    var base = t || obj || (ctx.domain ? ctx.domain : '');
    var m;
    switch (type.id) {
      case 'auto': {
        var field = ctx.manualFields[0];
        if (!field) {
          m = clause.match(/((?:[가-힣A-Za-z0-9]+\s)?[가-힣A-Za-z0-9]+?)(?:이|가|을|를)\s*(?:자동|기본)/);
          field = m ? m[1] : base;
        }
        return (field ? field + ' ' : '') + '자동 입력';
      }
      case 'restrict': {
        m = clause.match(/(수정|삭제|변경|편집|입력|저장|취소)/);
        return (t || base) + ' ' + (m ? m[1] : '수정') + ' 제한';
      }
      case 'display': return (t || base) + ' 별도 표시';
      case 'hide': return (t || base) + ' 숨김 처리';
      case 'search':
        m = clause.match(/(검색|필터|정렬)/);
        return (base ? base + ' ' : '') + (m ? m[1] : '조회') + ' 기능';
      case 'export':
        m = clause.match(/(엑셀\s?다운로드|엑셀|다운로드|출력|인쇄|프린트|PDF)/i);
        return (m ? m[1] : '출력') + ' 기능';
      case 'validate': return (base ? base + ' ' : '') + '입력값 검증';
      case 'notify':
        m = clause.match(/(알림|메일|문자|SMS|카톡|푸시)/i);
        return (m ? m[1] : '알림') + ' 발송 기능';
      case 'perf': return (base ? base + ' ' : '') + '처리 속도 개선';
      case 'bug': return (base ? base + ' ' : '') + '오류 수정';
      case 'add': return (base ? base + ' ' : '') + '추가';
      case 'change': return (base ? base + ' ' : '') + '변경';
      default: {
        var short = clause.replace(/[.!?~]+$/, '');
        return short.length > 24 ? short.slice(0, 24) + '…' : short;
      }
    }
  }

  /* ---------- 요약 ---------- */
  function joinKo(arr) {
    if (arr.length <= 1) return arr.join('');
    return arr.slice(0, -1).join(', ') + ' 및 ' + arr[arr.length - 1];
  }

  function makeSummary(reqs, ctx) {
    var phrases = [];
    var statusTypes = reqs.filter(function (r) { return r.status && /restrict|display|hide/.test(r.type); });
    reqs.forEach(function (r) {
      var p = r.summary;
      if (r.status && /restrict|display|hide/.test(r.type) && statusTypes.length) {
        p = (ctx.domain ? ctx.domain + ' ' : '') + '상태별 처리 기능 추가';
      }
      if (phrases.indexOf(p) < 0) phrases.push(p);
    });
    if (!phrases.length) return '';
    var head = ctx.domain ? ctx.domain + ' ' + ctx.screen + pp(ctx.screen, '의', '의') + ' ' : '';
    return head + joinKo(phrases);
  }

  /* ---------- 분석 ---------- */
  function analyze(text) {
    var ctx = context(text || '');
    var clauses = splitClauses(text).map(function (c, i) {
      return { id: 'c' + i, text: c, kind: kindOf(c), autoKind: null };
    });
    clauses.forEach(function (c) { c.autoKind = c.kind; });
    return { ctx: ctx, clauses: clauses };
  }

  function build(analysis, opts) {
    opts = opts || {};
    var ctx = analysis.ctx;
    var cl = analysis.clauses.filter(function (c) { return c.kind !== 'exclude'; });
    var bg = cl.filter(function (c) { return c.kind === 'background'; });
    var qs = cl.filter(function (c) { return c.kind === 'question'; });
    var rq = cl.filter(function (c) { return c.kind === 'request'; });

    var reqs = rq.map(function (c) {
      var type = typeOf(c.text);
      var tp = topicPhrase(c.text);
      var target = tp ? { raw: tp.raw, norm: normalizeTarget(tp.phrase, ctx) } : null;
      var title = makeTitle(c.text, type, target, ctx).replace(/\s{2,}/g, ' ').trim();
      var vague = VAGUE.filter(function (v) { return c.text.indexOf(v) >= 0; });
      return {
        title: title,
        desc: (type.id === 'perf' && !objectPhrase(c.text))
          ? (ctx.domain ? ctx.domain + ' ' + ctx.screen + '의 ' : '') + '처리 속도를 개선한다.'
          : toDevSentence(c.text, target, ctx),
        type: type.id,
        summary: type.summary,
        check: type.check,
        vague: vague,
        status: !!(target && target.norm && target.norm.status),
        source: c.text
      };
    });

    var summary = makeSummary(reqs, ctx);
    var lines = [];
    lines.push('[요구사항 요약]');
    lines.push(summary || '[추가 확인 필요: 요구사항이 명확하지 않습니다]');

    if (opts.background !== false && bg.length) {
      lines.push('', '[현재 상황]');
      bg.forEach(function (c) { lines.push('- ' + toBackground(c.text)); });
    }

    lines.push('', '[세부 요구사항]');
    if (!reqs.length) lines.push('[추가 확인 필요: 요청 내용을 찾지 못했습니다]');
    reqs.forEach(function (r, i) {
      lines.push((i + 1) + '. ' + r.title);
      lines.push('    * ' + r.desc);
      if (opts.source) lines.push('    * 원문: “' + r.source.replace(/[.\s]+$/, '') + '”');
    });

    if (qs.length) {
      lines.push('', '[고객 문의 사항]');
      qs.forEach(function (c) { lines.push('- ' + c.text.replace(/\s+$/, '')); });
    }

    if (opts.checks !== false) {
      var checks = [];
      reqs.forEach(function (r, i) {
        if (r.check) checks.push('- (' + (i + 1) + '번) ' + r.check);
        r.vague.forEach(function (v) {
          checks.push('- (' + (i + 1) + '번) ‘' + v + '’의 구체적인 기준');
        });
      });
      if (checks.length) {
        lines.push('', '[확인 필요 사항]');
        lines = lines.concat(checks);
      }
    }

    return {
      text: lines.join('\n'),
      summary: summary,
      requirements: reqs,
      counts: { request: rq.length, background: bg.length, question: qs.length }
    };
  }

  var api = {
    KINDS: [
      { id: 'request', label: '요구사항' },
      { id: 'background', label: '현재 상황' },
      { id: 'question', label: '문의' },
      { id: 'exclude', label: '제외' }
    ],
    splitClauses: splitClauses,
    analyze: analyze,
    build: build
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else global.RequirementEngine = api;
})(typeof window !== 'undefined' ? window : this);
