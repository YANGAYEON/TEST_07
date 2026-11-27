/*
 * 업무 도식화 도구 - 데이터 모델 / 규칙 기반 단계 추출
 * 외부 AI API, 인터넷 연결 없이 브라우저 안에서만 동작한다.
 */
(function (global) {
  'use strict';

  /** 단계 유형 정의 */
  var STEP_TYPES = {
    process:     { label: '업무 처리',   customer: true  },
    decision:    { label: '조건 판단',   customer: true  },
    screen:      { label: '화면 이동',   customer: true  },
    data:        { label: '데이터 조회·저장', customer: false },
    auth:        { label: '권한 확인',   customer: true  },
    integration: { label: '시스템 연계', customer: false },
    error:       { label: '예외 처리',   customer: true  },
    section:     { label: '업무 단위 구분', customer: true }
  };

  var DEFAULT_ROLES = ['고객', '신청자', '사용자', '회원', '담당자', '관리자', '팀장', '승인자', '부서장', '심사자', '시스템', '상담원', '직원'];

  /** 고객 설명 모드에서 숨기거나 쉬운 말로 바꾸는 기술 용어 */
  var TECH_TERMS = [
    [/\b(java|jsp|spring|servlet|javascript|js)\b/gi, ''],
    [/\b(sql|query)\b/gi, ''],
    [/쿼리/g, ''],
    [/\b(select)\b/gi, '확인'],
    [/\b(insert|update|merge)\b/gi, '저장'],
    [/\b(delete)\b/gi, '삭제'],
    [/\b(db|database|rdb|oracle|mysql|mssql|postgres(ql)?|tibero)\b/gi, '시스템'],
    [/데이터베이스/g, '시스템'],
    [/테이블/g, '정보'],
    [/\b(rest\s*)?api\b/gi, '연계 시스템'],
    [/\bi\/f\b|인터페이스/gi, '연계'],
    [/\b(was|web\s*server|서버)\b/gi, '시스템'],
    [/서버/g, '시스템'],
    [/\bbatch\b|배치/gi, '자동 처리'],
    [/\bsession\b|세션/gi, '로그인 상태'],
    [/\btoken\b|토큰/gi, '인증 정보'],
    [/트랜잭션|\btransaction\b|롤백|\brollback\b|커밋|\bcommit\b/gi, ''],
    [/\bjson\b|\bxml\b/gi, '정보'],
    [/\bcrud\b/gi, '등록·수정'],
    [/\b(ui|화면\s*id)\b/gi, '화면'],
    [/\bpk\b|\bfk\b|\bseq\b|시퀀스|인덱스|\bindex\b/gi, ''],
    [/\blog\b|로그를?\s*(남긴다|기록)/gi, '기록'],
    [/\bnull\b/gi, '빈 값'],
    [/\bflag\b|플래그/gi, '표시'],
    [/\bcode\s*\d+|코드값/gi, '구분값']
  ];

  var TECH_DETECT = /(java|jsp|spring|sql|쿼리|select|insert|update|delete|\bdb\b|데이터베이스|테이블|api|i\/f|인터페이스|서버|배치|batch|세션|토큰|트랜잭션|롤백|json|xml|pk|fk|시퀀스|인덱스|exception|null|컬럼|column|프로시저|procedure|캐시|cache)/i;

  /** 오류 메시지 → 고객 안내 문구 변환 규칙 */
  var ERROR_RULES = [
    [/(timeout|time\s*out|타임아웃|시간\s*초과|응답\s*없)/i, '“잠시 후 다시 시도해 주세요” 안내'],
    [/(권한|unauthori[sz]ed|forbidden|401|403|접근\s*거부)/i, '“이용 권한이 없습니다” 안내'],
    [/(로그인|인증|세션|session)/i, '“다시 로그인해 주세요” 안내'],
    [/(필수|누락|미입력|빈\s*값|null|입력\s*오류|형식|validation|유효성)/i, '“입력 내용을 확인해 주세요” 안내'],
    [/(중복|duplicate|이미\s*(등록|존재))/i, '“이미 등록된 내용입니다” 안내'],
    [/(재고|품절)/i, '“현재 재고가 없습니다” 안내'],
    [/(잔액|한도|초과|부족)/i, '“이용 가능 범위를 넘었습니다” 안내'],
    [/(연계|api|i\/f|인터페이스|외부\s*시스템|통신)/i, '“잠시 후 다시 시도해 주세요” 안내'],
    [/(exception|error|에러|오류|실패|fail|500|장애)/i, '“처리 중 문제가 발생했습니다” 안내']
  ];


  var uid = 0;
  function newId() { uid += 1; return 's' + Date.now().toString(36) + uid; }

  function newStep(over) {
    var s = {
      id: newId(),
      type: 'process',
      role: '',
      text: '',          // 고객/업무 관점 문구
      devText: '',       // 개발자 상세 (DB, 권한, 연계 등)
      screen: '',
      showCustomer: true,
      yesText: '',       // 조건: 예 일 때 처리
      noText: '',        // 조건: 아니오 일 때 처리
      yesFlow: 'continue', // continue | end | goto:<번호>
      noFlow: 'continue'   // continue | end | goto:<번호>
    };
    if (over) { for (var k in over) { if (Object.prototype.hasOwnProperty.call(over, k)) s[k] = over[k]; } }
    return s;
  }

  function trim(s) { return (s == null ? '' : String(s)).replace(/\s+/g, ' ').trim(); }

  function splitList(s) {
    return trim(s) ? String(s).split(/[,\n、·\/]/).map(trim).filter(Boolean) : [];
  }

  /** 자유 텍스트를 문장 단위로 분리 */
  function splitSentences(text) {
    if (!text) return [];
    var lines = String(text).replace(/\r/g, '').split(/\n|→|->|=>|▶|►/);
    var out = [];
    lines.forEach(function (line) {
      line = line.replace(/^\s*([-*•·○●▪■□]|\(?\d+[.)]|[①-⑳]|[가-하][.)])\s*/, '');
      line.split(/(?<=[다요음함됨임])\s*\.\s+|(?<=[다요음함됨임])\.\s*$|;\s*/).forEach(function (p) {
        p = trim(p).replace(/[.。]+$/, '');
        if (p) out.push(p);
      });
    });
    return out;
  }

  /** "X하면" / "X인 경우" 같은 조건절을 "X했나요?" 같은 질문형으로 변환 */
  function toQuestion(clause) {
    var c = trim(clause).replace(/[,，]$/, '');
    var rules = [
      [/(.*)하지\s*않(으면|은\s*경우|는\s*경우)$/, '$1하지 않았나요?'],
      [/(.*)되지\s*않(으면|은\s*경우|는\s*경우)$/, '$1되지 않았나요?'],
      [/(.*)이\s*아니(면|라면|ㄴ\s*경우)$/, '$1이 아닌가요?'],
      [/(.*)아닌\s*경우$/, '$1아닌가요?'],
      [/(.*)(있음)$/, '$1있나요?'],
      [/(.*)(없음)$/, '$1없나요?'],
      [/(.*)됨$/, '$1되었나요?'],
      [/(.*)함$/, '$1했나요?'],
      [/(.*)(완료|누락)$/, '$1$2되었나요?'],
      [/(.*)(실패|성공|초과|미달)$/, '$1$2했나요?'],
      [/(.*)(이면|이라면|인\s*경우|일\s*경우)$/, '$1인가요?'],
      [/(.*)(가능하면|가능한\s*경우|가능할\s*경우)$/, '$1가능한가요?'],
      [/(.*)(있으면|있는\s*경우|있을\s*경우)$/, '$1있나요?'],
      [/(.*)(없으면|없는\s*경우|없을\s*경우)$/, '$1없나요?'],
      [/(.*)(되면|된\s*경우|될\s*경우|되었으면|됐으면)$/, '$1되었나요?'],
      [/(.*)(하면|한\s*경우|할\s*경우|했으면|하였으면)$/, '$1했나요?'],
      [/(.*)(하는\s*경우)$/, '$1하나요?'],
      [/(.*)(으면|은\s*경우|는\s*경우)$/, '$1나요?'],
      [/(.*)(라면)$/, '$1인가요?'],
      [/(.*)면$/, '$1인가요?'],
      [/(.*)\s*경우$/, '$1인가요?'],
      [/(.*)\s*(여부|확인)$/, '$1인가요?']
    ];
    for (var i = 0; i < rules.length; i++) {
      if (rules[i][0].test(c)) return trim(c.replace(rules[i][0], rules[i][1]));
    }
    return /\?$/.test(c) ? c : c + '인가요?';
  }

  var COND_SPLIT = /^(.*?(?:하지\s*않으면|되지\s*않으면|아니면|아니라면|이면|이라면|가능하면|있으면|없으면|되면|하면|했으면|으면|라면|(?:인|일|한|할|된|될|하는|는|은|없는|있는|아닌)\s*경우(?:에는|에)?))[,\s]+(.+)$/;
  var NEGATIVE_START = /^(아니면|아니라면|그렇지\s*않으면|그렇지\s*않은\s*경우|아닌\s*경우|반대(로|의\s*경우)|실패\s*시|불가\s*시|미충족\s*시|아니오(면|일\s*때)?)[,\s:]*/;
  var NEGATIVE_WORD = /(아니|않|없|실패|불가|미충족|반려|거절|오류|부족|초과)/;

  function detectRole(sentence, roles) {
    var m = sentence.match(/^(\S+?)(이|가|은|는|께서|에서)\s+/);
    var cand = m ? m[1] : '';
    var all = roles.concat(DEFAULT_ROLES);
    for (var i = 0; i < all.length; i++) {
      var r = all[i];
      if (!r) continue;
      if (cand && cand.length <= r.length + 4 && cand.slice(-r.length) === r) {
        return { role: cand, rest: trim(sentence.slice(m[0].length)) };
      }
    }
    return { role: '', rest: sentence };
  }

  function detectType(text) {
    var t = text;
    if (/(로그인|권한|인증|본인\s*확인)/.test(t) && /(확인|검사|체크|여부)/.test(t)) return 'auth';
    if (/(오류|에러|예외|실패|exception)/i.test(t)) return 'error';
    if (/(api|i\/f|인터페이스|연계|외부\s*시스템|erp|sms|문자\s*발송|메일\s*발송|알림톡)/i.test(t)) return 'integration';
    if (/(\bdb\b|테이블|sql|쿼리|insert|update|select|데이터베이스|저장한다|저장됨|조회한다)/i.test(t)) return 'data';
    if (/(화면|페이지|팝업|창)(으로|에서|을|를|이|로)?\s*(이동|열|표시|띄)/.test(t)) return 'screen';
    return 'process';
  }

  function detectScreen(text, screens) {
    for (var i = 0; i < screens.length; i++) {
      if (screens[i] && text.indexOf(screens[i]) >= 0) return screens[i];
    }
    var m = text.match(/([가-힣A-Za-z0-9]+(?:\s?[가-힣A-Za-z0-9]+)?\s?(?:화면|페이지|팝업))/);
    return m ? trim(m[1]) : '';
  }

  /**
   * 고객 요구사항 + 업무 단계 텍스트에서 단계 목록을 추출한다.
   * 업무 단계(steps) 입력이 있으면 우선 사용하고, 없으면 고객 요구사항을 사용한다.
   */
  function extractSteps(info) {
    var roles = splitList(info.roles).concat(splitList(info.owners));
    var screens = splitList(info.screens);
    var source = trim(info.steps) ? info.steps : info.requirement;
    var sentences = splitSentences(source);
    var steps = [];
    var lastDecision = null;

    sentences.forEach(function (raw) {
      var sec = raw.match(/^\s*(#{1,3}|\[업무\]|업무\s*단위\s*:)\s*(.+)$/);
      if (sec) { steps.push(newStep({ type: 'section', text: trim(sec[2]) })); lastDecision = null; return; }

      var neg = raw.match(NEGATIVE_START);
      if (neg && lastDecision) {
        var body = trim(raw.slice(neg[0].length));
        lastDecision.noText = body;
        if (/(종료|중단|취소|마침|끝)/.test(body)) lastDecision.noFlow = 'end';
        var back = body.match(/(\d+)\s*(단계|번)\s*(으로|로)/);
        var bi = back ? rawIndex(steps, parseInt(back[1], 10)) : -1;
        if (bi >= 0) lastDecision.noFlow = 'goto:' + (bi + 1);
        else if (/(다시|재)\s*(입력|작성|시도|요청|제출)|돌아/.test(body)) {
          var target = findBackTarget(steps, body);
          if (target) lastDecision.noFlow = 'goto:' + target;
        }
        lastDecision = null;
        return;
      }

      var rr = detectRole(raw, roles);
      var role = rr.role;
      var sentence = rr.rest;

      // "X가 Y하면 Z한다" 형태의 조건 분기
      var cm = sentence.match(COND_SPLIT);
      if (cm && !/^(로그인하면|접속하면)$/.test(trim(cm[1]))) {
        var cond = trim(cm[1]).replace(/(에는|에)$/, '');
        var action = trim(cm[2]);
        var condRole = detectRole(action, roles);
        var d = newStep({
          type: /(권한|로그인|인증)/.test(cond) ? 'auth' : 'decision',
          role: role,
          text: toQuestion(cond),
          yesText: condRole.rest,
          screen: detectScreen(raw, screens)
        });
        // "재고가 없으면 품절 안내 후 종료" → 예 쪽이 예외 흐름
        if (NEGATIVE_WORD.test(cond) && /(종료|중단|취소|마침)/.test(action)) d.yesFlow = 'end';
        steps.push(d);
        lastDecision = d;
        return;
      }

      var type = detectType(sentence);
      var s = newStep({
        type: type,
        role: role,
        text: sentence,
        screen: detectScreen(raw, screens),
        showCustomer: STEP_TYPES[type].customer
      });
      if (type === 'data' || type === 'integration') { s.devText = sentence; s.text = customerizeText(sentence) || '시스템이 자동으로 처리합니다'; }
      steps.push(s);
      lastDecision = null;
    });

    attachDevNotes(steps, info.devNotes);
    return steps;
  }

  function findBackTarget(steps, body) {
    var words = keywords(body);
    for (var i = steps.length - 1; i >= 0; i--) {
      if (steps[i].type === 'decision' || steps[i].type === 'section') continue;
      var w = keywords(steps[i].text);
      for (var j = 0; j < words.length; j++) if (w.indexOf(words[j]) >= 0) return i + 1;
    }
    return null;
  }

  var STOP = ['한다', '합니다', '하고', '해서', '시스템', '고객', '사용자', '담당자', '처리', '진행', '확인', '경우', '있는', '없는', '하는', '그리고', '이후', '다음', '내용', '정보', '단계', '시', '및', '또는', '때'];
  function keywords(text) {
    return (String(text || '').match(/[가-힣A-Za-z0-9]{2,}/g) || [])
      .map(function (w) { return w.replace(/(을|를|이|가|은|는|에서|에게|으로|로|와|과|의|도|만|에|하여|하고|한다|합니다|해야|하면)$/, ''); })
      .filter(function (w) { return w.length >= 2 && STOP.indexOf(w) < 0; });
  }

  /** 개발자 고려사항 분류 */
  var DEV_CATEGORIES = [
    { key: 'data',   label: '데이터 조회 및 저장', re: /(\bdb\b|테이블|sql|쿼리|조회|저장|insert|update|select|delete|이력|데이터)/i },
    { key: 'auth',   label: '권한 확인',           re: /(권한|로그인|인증|role|세션|접근)/i },
    { key: 'error',  label: '예외 처리',           re: /(예외|오류|에러|실패|exception|timeout|롤백|재시도|검증|유효성|validation)/i },
    { key: 'integ',  label: '시스템 간 연계',      re: /(api|연계|인터페이스|i\/f|외부|erp|sms|메일|알림|배치|batch)/i },
    { key: 'etc',    label: '개발 시 고려사항',    re: /.*/ }
  ];

  function categorizeDevNotes(devNotes) {
    var groups = DEV_CATEGORIES.map(function (c) { return { key: c.key, label: c.label, items: [] }; });
    splitSentences(devNotes).forEach(function (line) {
      var clean = line.replace(/^\[\s*\d+\s*\]\s*|^\d+\s*(단계|번)\s*[:：]\s*/, '');
      for (var i = 0; i < DEV_CATEGORIES.length; i++) {
        if (DEV_CATEGORIES[i].re.test(clean)) { groups[i].items.push(clean); break; }
      }
    });
    return groups.filter(function (g) { return g.items.length; });
  }

  /** 개발자 고려사항을 관련 단계의 개발자 상세에 연결 ("[3] ..." 또는 "3단계: ..." 또는 키워드 일치) */
  var AFFINITY = { data: 'data', integ: 'integration', auth: 'auth', error: 'error' };
  function attachDevNotes(steps, devNotes) {
    // 다른 고려사항이 붙기 전의 원래 문구로 비교 (먼저 붙은 내용에 끌려가지 않도록)
    var base = steps.map(function (s) { return keywords(s.text + ' ' + s.yesText + ' ' + s.noText + ' ' + s.devText + ' ' + s.screen); });
    var adds = [];
    splitSentences(devNotes).forEach(function (line) {
      var m = line.match(/^\[\s*(\d+)\s*\]\s*(.+)$|^(\d+)\s*(?:단계|번)\s*[:：]\s*(.+)$/);
      var idx = -1, text = line;
      if (m) { idx = rawIndex(steps, parseInt(m[1] || m[3], 10)); text = trim(m[2] || m[4]); }
      else {
        var kw = keywords(line), best = 0;
        var cats = [];
        for (var c = 0; c < DEV_CATEGORIES.length - 1; c++) if (DEV_CATEGORIES[c].re.test(line)) cats.push(AFFINITY[DEV_CATEGORIES[c].key]);
        steps.forEach(function (s, i) {
          if (s.type === 'section') return;
          var score = kw.filter(function (w) { return base[i].indexOf(w) >= 0; }).length;
          if (!score) return;
          if (cats.indexOf(s.type) >= 0) score += 1.5;
          if (score > best) { best = score; idx = i; }
        });
        if (best < 1) idx = -1;
      }
      if (idx >= 0 && steps[idx]) adds.push([idx, text]);
    });
    adds.forEach(function (a) {
      var s = steps[a[0]];
      s.devText = s.devText ? s.devText + ' / ' + a[1] : a[1];
    });
  }

  /** 화면에 보이는 단계 번호(업무 단위 구분 제외, 1부터) → 배열 위치 */
  function rawIndex(steps, no) {
    var c = 0;
    for (var i = 0; i < steps.length; i++) {
      if (steps[i].type === 'section') continue;
      c += 1; if (c === no) return i;
    }
    return -1;
  }
  /** 배열 위치 → 화면 단계 번호 */
  function stepNo(steps, idx) {
    var c = 0;
    for (var i = 0; i <= idx && i < steps.length; i++) if (steps[i].type !== 'section') c += 1;
    return c;
  }

  /** 고객 설명 모드용 문구 정리: 기술 용어 제거, 짧은 문장 */
  function customerizeText(text) {
    var t = String(text || '');
    if (/(exception|stack\s*trace|error\s*code|에러\s*코드|오류\s*코드|[A-Z]{2,}-?\d{2,})/i.test(t) && /(오류|에러|실패|exception|error)/i.test(t)) {
      return friendlyError(t);
    }
    TECH_TERMS.forEach(function (r) { t = t.replace(r[0], r[1]); });
    t = t.replace(/\([^)]*\)/g, function (m) { return TECH_DETECT.test(m) ? '' : m; });
    t = t.replace(/\s{2,}/g, ' ').replace(/\s+([,.)])/g, '$1').replace(/^[,\s]+|[,\s]+$/g, '');
    t = t.replace(/(시스템\s*){2,}/g, '시스템 ').replace(/(에서|을|를)\s*(을|를)/g, '$1');
    // 문장 끝 정리: "~한다" → "~" 형태의 짧은 표현
    t = t.replace(/(합니다|한다|하였다|했다)$/, '').replace(/(됩니다|된다)$/, '됨').replace(/(입니다|이다)$/, '')
      .replace(/간다$/, '감').replace(/온다$/, '옴').replace(/보낸다$/, '보냄').replace(/누른다$/, '누름')
      .replace(/받는다$/, '받음').replace(/있다$/, '있음').replace(/없다$/, '없음').replace(/선택한다$/, '선택');
    // 바뀐 용어 뒤 조사 보정 (받침 있는 '시스템', '정보 없음' 등)
    t = t.replace(/(시스템|연계)(로|를|가|는|와)(?=\s|$)/g, function (m, w, j) {
      if (w === '연계') return m;
      return w + ({ '로': '으로', '를': '을', '가': '이', '는': '은', '와': '과' })[j];
    });
    t = t.replace(/(을|를)\s*$/, '').trim();
    return trim(t);
  }

  function friendlyError(text) {
    for (var i = 0; i < ERROR_RULES.length; i++) {
      if (ERROR_RULES[i][0].test(text)) return ERROR_RULES[i][1];
    }
    return '처리 중 문제가 발생했습니다. 담당자에게 문의해 주세요.';
  }

  /** 변경 전/후 텍스트를 단계 목록으로 */
  function parseSimpleSteps(text) { return splitSentences(text); }

  /** 조건 및 예외사항 "조건 → 결과" / "조건: 결과" / "조건이면 결과" 파싱 */
  function parseConditions(text) {
    var out = [];
    String(text || '').replace(/\r/g, '').split('\n').forEach(function (line) {
      line = trim(line.replace(/^\s*([-*•·]|\d+[.)])\s*/, ''));
      if (!line) return;
      var m = line.match(/^(.+?)\s*(?:→|->|=>|:|：)\s*(.+)$/);
      if (m) { out.push({ cond: trim(m[1]), result: trim(m[2]) }); return; }
      var c = line.match(COND_SPLIT);
      if (c) { out.push({ cond: trim(c[1]), result: trim(c[2]) }); return; }
      out.push({ cond: line, result: '' });
    });
    return out;
  }

  global.FlowModel = {
    STEP_TYPES: STEP_TYPES,
    TECH_DETECT: TECH_DETECT,
    newStep: newStep,
    splitList: splitList,
    splitSentences: splitSentences,
    toQuestion: toQuestion,
    extractSteps: extractSteps,
    categorizeDevNotes: categorizeDevNotes,
    customerizeText: customerizeText,
    friendlyError: friendlyError,
    parseSimpleSteps: parseSimpleSteps,
    parseConditions: parseConditions,
    keywords: keywords,
    rawIndex: rawIndex,
    stepNo: stepNo
  };
})(window);
