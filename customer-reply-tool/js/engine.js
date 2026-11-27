/*!
 * 고객 답변 초안 정리 엔진 (규칙 기반)
 * - 외부 API / 네트워크 / 저장소를 사용하지 않습니다.
 * - 입력에 없는 원인·조치·사실을 만들어내지 않습니다.
 *   (정리 과정에서는 문장 어미·표현만 바꾸고, 빠진 항목은 '추가 확인 필요'로 표시합니다.)
 */
(function (global) {
  'use strict';

  /* ------------------------------------------------------------------ */
  /* 분류 항목                                                           */
  /* ------------------------------------------------------------------ */
  var CATEGORIES = [
    { id: 'inquiry', label: '문의 내용', required: false },
    { id: 'result', label: '확인 결과', required: true },
    { id: 'cause', label: '원인', required: true },
    { id: 'action', label: '조치 내용', required: true },
    { id: 'guide', label: '고객 안내사항', required: false }
  ];
  var LABEL = {};
  CATEGORIES.forEach(function (c) { LABEL[c.id] = c.label; });

  var NEED = function (name) { return '[추가 확인 필요: ' + name + ']'; };

  /* ------------------------------------------------------------------ */
  /* 한글 음절 유틸                                                       */
  /* ------------------------------------------------------------------ */
  var JONG = { NONE: 0, N: 4, M: 16, B: 17, SS: 20 };

  function dec(ch) {
    if (!ch) return null;
    var c = ch.charCodeAt(0) - 0xac00;
    if (c < 0 || c > 11171) return null;
    return { cho: Math.floor(c / 588), jung: Math.floor((c % 588) / 28), jong: c % 28 };
  }
  function com(cho, jung, jong) {
    return String.fromCharCode(0xac00 + cho * 588 + jung * 28 + jong);
  }
  function setJong(ch, jong) {
    var d = dec(ch);
    return d ? com(d.cho, d.jung, jong) : ch;
  }
  function hasJong(ch) {
    var d = dec(ch);
    return !!(d && d.jong);
  }

  /* ------------------------------------------------------------------ */
  /* 분류 규칙                                                           */
  /* ------------------------------------------------------------------ */
  var RULES = {
    inquiry: [
      /문의/, /접수/, /요청(?:하|했|함|이|을|주|하셨|하심)/,
      /(?:라|다)고\s*(?:하|함|했|연락|말|전화|메일)/,
      /고객(?:님|사)?\s*(?:이|가|께서|분이|측에서|쪽에서)\s/,
      /불편(?:하다|하다고|을\s*호소|함)/, /불만|항의/,
      /(?:안|못)\s?(?:된다고|되었다고|됐다고|한다고)/
    ],
    result: [
      /확인\s?(?:해\s?보니|해\s?본|결과|했|함|됨|하였|하니|한\s?결과|됐|완료)/,
      /재현/, /점검/, /조회/, /분석/, /로그/, /살펴/, /테스트/, /모니터링/,
      /정상(?:적으로)?\s*(?:동작|작동|처리|출력|표시)/
    ],
    cause: [
      /원인/, /때문/, /(?:으)?로\s*인(?:해|한)/, /탓/,
      /(?:문제|오류|버그|결함|이슈|에러|장애)\s*(?:였|이었|인\s?것|로\s?보|로\s?추정|가\s?있었|가\s?있음|일|가\s?발생)/,
      /누락/, /충돌/, /만료/, /잘못/, /가능성/, /과부하|부하/, /지연/,
      /설정\s*(?:오류|누락|문제|이상)/
    ],
    action: [
      /수정(?:했|함|하였|완료|됨|하여|해서|후|해\s?두|해\s?놓)/, /조치/, /배포/, /반영(?:했|함|하였|완료|됨|할)/,
      /패치/, /재시작|재기동|리부팅|재부팅/, /복구/, /초기화(?:했|함|하였|완료)/,
      /변경(?:했|함|하였|완료)/, /처리(?:했|함|하였|완료)/, /해결/, /롤백/, /핫\s?픽스/,
      /업데이트(?:했|함|하였|완료)/, /추가(?:했|함|하였)/, /삭제(?:했|함|하였)/,
      /적용(?:했|함|하였|완료)/, /예정/, /재처리|재발송|재전송/
    ],
    guide: [
      /안내/, /부탁/, /바랍니다/, /해\s?(?:주시|주세요|달라)/, /(?:하|해|으)(?:라고|도록)/,
      /(?:시도|재접속|재로그인|새로고침|재설치|업데이트)\s*(?:해|하)\s*(?:보|주|면)/,
      /권장/, /주의/, /이용\s*(?:가능|하시)/, /(?:하|으)?면\s*(?:된다|됨|됩니다|돼요)/,
      /고객(?:님)?(?:에게|께|한테)/
    ]
  };
  // 점수가 같으면 앞쪽 항목 우선 (구체적인 항목 우선)
  var PRIORITY = ['cause', 'action', 'guide', 'inquiry', 'result'];
  // 원인·조치 표현은 '확인' 같은 일반 표현보다 구체적이므로 가중치를 높게 둠
  var WEIGHT = { cause: 1.5, action: 1.5, guide: 1.2, inquiry: 1.2, result: 1 };

  var UNCERTAIN_RE = /(것\s?같|듯(?:하|함|합|싶|$|\s)|추정|아마|보인다|보임|보입니다|보여|가능성|수도\s?있|예상(?:됨|된다|함|합니다|되)|짐작|확실하지|확실치|미확인|확인\s?중|파악\s?중|분석\s?중|조사\s?중|불확실|정확하지\s?않|모르겠|불명)/;

  var INTERNAL_RE = /(소스\s?코드|코드\s?상|쿼리|커밋|브랜치|스택\s?트레이스|exception|NPE|null\s?pointer|레포|깃허브|\bgit\b|jira|지라|티켓|개발팀|내부\s?(?:확인|논의|이슈|사정|정책)|TODO|IP\s?주소|\b\d{1,3}(?:\.\d{1,3}){3}\b|포트|운영\s?DB|DB\s?직접|SQL|테이블|컬럼)/i;

  function classify(s) {
    var best = null, bestScore = 0, second = 0;
    PRIORITY.forEach(function (c) {
      var sc = 0;
      RULES[c].forEach(function (r) { if (r.test(s)) sc += WEIGHT[c]; });
      if (sc > bestScore) { second = bestScore; best = c; bestScore = sc; }
      else if (sc > second) { second = sc; }
    });
    if (!best) {
      // 단서가 없는 추정 문장은 대개 원인에 대한 추측
      return { category: UNCERTAIN_RE.test(s) ? 'cause' : 'result', confidence: 'low' };
    }
    // '확인' 단서만 있는 추정 문장은 원인에 대한 추측으로 봄
    if (best === 'result' && UNCERTAIN_RE.test(s)) return { category: 'cause', confidence: 'mid' };
    return { category: best, confidence: bestScore > second ? 'high' : 'mid' };
  }

  /* ------------------------------------------------------------------ */
  /* 문장 분리                                                           */
  /* ------------------------------------------------------------------ */
  var BULLET_RE = /^\s*(?:[-*•·▶▷○●■□◆◇※>]+|\d{1,2}[.)](?=\s)|[①-⑳]|[가-하][.)](?=\s))\s*/;
  var SEP = '\u0001';

  function splitSentences(text) {
    if (!text) return [];
    var t = String(text).replace(/\r/g, '');
    // "~했고, ~" / "~였으며, ~" 형태의 연결 문장은 나눔
    t = t.replace(/(었|였|았|했|됐|겼|졌)(고|으며),\s*/g, function (m, a) { return a + '다.\n'; });
    var out = [];
    t.split(/\n+/).forEach(function (line) {
      line = line
        .replace(/([.!?。])\s+/g, '$1' + SEP)
        .replace(/(니다|했다|였다|었다|았다|됐다|된다|한다|이다|있다|없다|했음|였음|었음|있음|없음|함|됨|어요|해요|돼요|에요|예요|세요)\s+(?=[가-힣A-Za-z0-9"'(\[])/g, '$1' + SEP);
      line.split(SEP).forEach(function (p) {
        p = p.replace(BULLET_RE, '').trim();
        if (p.replace(/[\s.。!?~]/g, '').length >= 2) out.push(p);
      });
    });
    return out;
  }

  /* ------------------------------------------------------------------ */
  /* 표현 정리                                                           */
  /* ------------------------------------------------------------------ */
  var CASUAL = [
    [/[ㅋㅎㅠㅜ]+/g, ''],
    [/\^\^|;;+/g, ''],
    [/근데/g, '그런데'],
    [/그래서\s*/g, '이에 따라 '],
    [/일단\s*/g, '우선 '],
    [/(^|\s)좀\s+/g, '$1'],
    [/(엄청|되게|완전)\s+/g, '매우 '],
    [/안(된|되|돼|됨|됐)/g, '안 $1'],
    [/못(했|함|함)/g, '못 $1'],
    [/([가-힣])\s?거\s?같/g, '$1 것 같'],
    [/알고\s?보니\s*/g, '확인 결과 '],
    [/로그\s(?=확인|조회|분석)/g, '로그를 '],
    [/확인\s?해\s?보니(?:까)?\s*,?\s*/g, '확인한 결과, '],
    [/(?:봤|보았)더니\s*,?\s*/g, '확인한 결과, '],
    [/(\S)\s보니(?:까)?\s*,?\s*/g, '$1 확인한 결과, '],
    [/([가-힣]{2})해서(?=\s)/g, '$1하여'],
    [/했는데\s*,?/g, '했으나'],
    [/\s{2,}/g, ' ']
  ];

  var JARGON = [
    [/핫\s?픽스/g, '긴급 수정'],
    [/롤백/g, '이전 버전으로 복구'],
    [/디플로이/gi, '반영'],
    [/재배포/g, '재반영'],
    [/배포/g, '반영'],
    [/리부팅|재부팅|재기동|리스타트/g, '재시작'],
    [/\bDB\b/g, '데이터베이스'],
    [/디비/g, '데이터베이스'],
    [/버그/g, '오류'],
    [/에러/g, '오류'],
    [/이슈/g, '문제'],
    [/픽스/g, '수정'],
    [/캐쉬/g, '캐시'],
    [/서버\s?다운/g, '서버 장애']
  ];

  function applyList(s, list) {
    list.forEach(function (r) { s = s.replace(r[0], r[1]); });
    return s;
  }

  function stripEnd(s) {
    return s.replace(/[\s.。!~…]+$/, '').trim();
  }

  // 문장 끝을 합쇼체(-습니다/-ㅂ니다)로 정리
  function toFormal(s) {
    s = stripEnd(s);
    if (!s) return s;
    if (/\?$/.test(s)) return s;
    if (/주세요$/.test(s)) return s.replace(/주세요$/, '주시기 바랍니다');
    if (/(?:니다|바랍니다|십시오)$/.test(s)) return s;

    var YO = [
      [/(?:이에요|예요|에요)$/, '입니다'],
      [/됐어요$/, '되었습니다'],
      [/했어요$/, '했습니다'],
      [/해요$/, '합니다'],
      [/돼요$/, '됩니다'],
      [/있어요$/, '있습니다'],
      [/없어요$/, '없습니다'],
      [/같아요$/, '같습니다'],
      [/([었았였])어요$/, '$1습니다']
    ];
    for (var i = 0; i < YO.length; i++) {
      if (YO[i][0].test(s)) return fix(s.replace(YO[i][0], YO[i][1]));
    }

    // 안 됨 / 못 함
    if (/\s?안\s?(?:됨|됐음|됐다|되었음|되었다)$/.test(s)) return s.replace(/\s?안\s?(?:됨|됐음|됐다|되었음|되었다)$/, '되지 않았습니다');
    if (/\s?못\s?(?:함|했음|했다)$/.test(s)) return s.replace(/\s?못\s?(?:함|했음|했다)$/, '하지 못했습니다');

    // 면 됨 / 면 된다
    if (/면\s*(?:됨|된다)$/.test(s)) return s.replace(/(?:됨|된다)$/, '됩니다');

    // ~다
    var m = s.match(/([가-힣])다$/);
    if (m) {
      var prev = m[1];
      var base = s.slice(0, -2);
      var d = dec(prev);
      if (prev === '는') return base + '습니다';                 // 먹는다 → 먹습니다
      if (prev === '이') return base + '입니다';                 // 때문이다 → 때문입니다
      if (d && d.jong === JONG.N) return base + setJong(prev, JONG.B) + '니다'; // 된다 → 됩니다
      if (d && d.jong) return fix(base + prev + '습니다');       // 했다 → 했습니다
      if ('하되리르쁘프크지치기주보오가나내서'.indexOf(prev) >= 0) return base + setJong(prev, JONG.B) + '니다';
      return base + prev + '입니다';                            // 문제다 → 문제입니다
    }

    // ~함 / ~됨 / ~음 / ~임
    var last = s.slice(-1);
    var before = s.slice(0, -1);
    if (last === '함') {
      if (/고$/.test(before)) return before + '합니다';         // ~다고 함 → ~다고 합니다
      if (/(?:필요|가능|불가|불가능|동일|유사|상이|정상|원활|존재)\s*$/.test(before)) return before + '합니다';
      return before + '했습니다';                                // 수정함 → 수정했습니다
    }
    if (last === '됨') {
      if (/(?:예상|추정|판단|생각|우려|필요)\s*$/.test(before)) return before + '됩니다';
      return before + '되었습니다';                              // 완료됨 → 완료되었습니다
    }
    if (last === '음') {
      var p = before.slice(-1);
      if (hasJong(p)) return fix(before + '습니다');            // 있음 → 있습니다
      return s;
    }
    if (last === '임') return before + '입니다';
    if (last === '짐') return before + '졌습니다';
    if (last === '김') return before + '겼습니다';

    // 명사형 종결
    var NOUN_END = [
      [/(필요|가능|불가|불가능)$/, '$1합니다'],
      [/(완료)$/, '$1되었습니다'],
      [/(예정|상태|중|정상|상황|단계)$/, '$1입니다'],
      [/(확인|수정|조치|반영|처리|적용|변경|복구|삭제|추가|재시작|초기화|요청|전달|점검|테스트|등록|해제|교체|업데이트)$/, '$1했습니다']
    ];
    for (var j = 0; j < NOUN_END.length; j++) {
      if (NOUN_END[j][0].test(s)) return s.replace(NOUN_END[j][0], NOUN_END[j][1]);
    }
    return s;
  }

  function fix(s) {
    return s.replace(/됐습니다$/, '되었습니다').replace(/됐었습니다$/, '되었었습니다');
  }

  // 확인되지 않은 내용은 확정적으로 쓰지 않음
  function soften(s, uncertain) {
    s = s
      .replace(/(인|한|된|던)\s?것\s?같습니다$/, '$1 것으로 보입니다')
      .replace(/것\s?같습니다$/, '것으로 보입니다')
      .replace(/(일|할|될)\s?수도\s?있습니다$/, '$1 가능성이 있습니다')
      .replace(/(인|한)\s?듯(?:합니다|싶습니다)$/, '$1 것으로 보입니다')
      .replace(/(\S)\s?듯(?:합니다|싶습니다)$/, '$1 것으로 보입니다')
      .replace(/(^|\s)아마(?:도)?\s+/g, '$1');
    if (!uncertain) return s;
    if (/(추정|보입니다|가능성|확인\s?중|파악\s?중|분석\s?중|조사\s?중|예상|판단됩니다|필요합니다|않습니다)/.test(s)) return s;
    if (/입니다$/.test(s)) return s.replace(/입니다$/, '인 것으로 추정됩니다');
    if (/했습니다$/.test(s)) return s.replace(/했습니다$/, '한 것으로 추정됩니다');
    if (/되었습니다$/.test(s)) return s.replace(/되었습니다$/, '된 것으로 추정됩니다');
    if (/([가-힣])습니다$/.test(s)) return s.replace(/습니다$/, '는 것으로 추정됩니다');
    var m = s.match(/([가-힣])니다$/);
    if (m) {
      var d = dec(m[1]);
      if (d && d.jong === JONG.B) return s.slice(0, -3) + com(d.cho, d.jung, 0) + '는 것으로 추정됩니다';
    }
    return s;
  }

  function finalize(s) {
    s = s.replace(/\s{2,}/g, ' ').replace(/\s+([,.])/g, '$1').trim();
    if (!s) return s;
    if (!/[.!?]$/.test(s)) s += '.';
    return s;
  }

  function baseClean(raw, opts) {
    var s = String(raw).replace(BULLET_RE, '');
    s = applyList(s, CASUAL);
    if (opts.plainTerms) s = applyList(s, JARGON);
    s = s.replace(/고객(?!님|사|센터|정보|번호|명)/g, '고객님');
    return stripEnd(s.trim());
  }

  function polishSentence(item, opts) {
    var s = baseClean(item.text, opts);
    if (item.category === 'guide') s = toGuide(s);
    else s = toFormal(s);
    s = soften(s, item.uncertain);
    return finalize(s);
  }

  // 안내사항: "고객에게 ~하라고 안내 필요" → "~하시기 바랍니다"
  function toGuide(s) {
    s = s.replace(/^고객님?\s*(?:에게|께|한테|측에|쪽에)\s*/, '');
    var marked = false;
    s = s.replace(/\s*(?:안내|요청|전달|공지|말씀)\s*(?:를|을)?\s*(?:필요|해야\s*(?:함|한다|합니다|할\s*듯)|요망|바람|부탁|드림|드리기|함|했음|하기|해\s*주세요|해야\s*됨|예정|드려야\s*함|드리면\s*됨)?\s*$/, function () {
      marked = true; return '';
    });
    s = s.trim();
    if (!marked && /\s*(?:부탁(?:함|드림)?|요망|바람)$/.test(s)) {
      return s.replace(/\s*(?:부탁(?:함|드림)?|요망|바람)$/, ' 부탁드립니다');
    }
    if (marked) {
      if (/해\s?달라고$/.test(s)) return s.replace(/해\s?달라고$/, '해 주시기 바랍니다');
      if (/(?:하|해)\s?보라고$/.test(s)) return s.replace(/(?:하|해)\s?보라고$/, '해 보시기 바랍니다');
      if (/시도록$/.test(s)) return s.replace(/시도록$/, '시기 바랍니다');
      if (/(?:으)?라고$|도록$/.test(s)) return s.replace(/라고$|도록$/, '시기 바랍니다');
      if (/(?:하면|으면|면)\s*(?:된다고|된다는|됨을|된다)$/.test(s)) return s.replace(/(?:된다고|된다는|됨을|된다)$/, '됩니다').replace(/하면\s/, '하시면 ');
      if (/[가-힣A-Za-z0-9)]$/.test(s) && !/다$/.test(s)) return s + ' 부탁드립니다';
      return toFormal(s);
    }
    s = toFormal(s);
    s = s.replace(/하면\s(됩니다)$/, '하시면 $1');
    return s;
  }

  /* ------------------------------------------------------------------ */
  /* 문의 내용 → 주제 구                                                   */
  /* ------------------------------------------------------------------ */
  function inquiryTopic(raw, opts) {
    var s = baseClean(raw, opts);
    s = s.replace(/^(?:오늘|어제|금일|방금|아까|오전에|오후에)?\s*(?:고객님?|고객사|사용자|이용자|업체|거래처)\s*(?:이|가|께서|측에서|쪽에서|분이|분께서|측|쪽)?\s+/, '');
    var quoted = false;
    var t = s.replace(/\s*(?:이)?(?:라)?고\s*(?:(?:고객님?|사용자|이용자|고객사)\s*(?:이|가|께서|측에서)?\s*)?(?:문의|요청|연락|말씀|전화|메일|하심|하셨|함|했|합니다|옴|왔|접수|불만|항의|얘기|이야기).*$/, function () {
      quoted = true; return '';
    });
    if (!quoted) {
      t = t.replace(/\s*(?:관련|에\s?대해|에\s?대한|에\s?관한)?\s*(?:문의|요청|접수|불만|항의|연락)\s*(?:가|를|이|을)?\s*(?:함|했|하셨|하심|옴|들어옴|들어왔|됨|됐|있었|있음|있다|왔|주셨|드림|건|있습니다|주셨습니다)?\s*$/, '');
    }
    t = t.trim();
    if (!t || t.length > 60) return null;
    if (/다$/.test(t)) {
      var stem = t.slice(0, -1);
      var last = stem.slice(-1);
      var d = dec(last);
      if (last === '는') return stem + ' 현상';
      if (last === '이') return null;
      if (last === '있' || last === '없') return stem + '는 현상';
      if (d && d.jong === JONG.N) return stem.slice(0, -1) + setJong(last, 0) + '는 현상'; // 된다 → 되는
      if (d && !d.jong && '리르쁘프크'.indexOf(last) >= 0) return stem.slice(0, -1) + setJong(last, JONG.N) + ' 현상'; // 느리다 → 느린
      return t.replace(/됐다$/, '되었다') + '는 내용';
    }
    // 명사형(-ㅁ) 종결: 느림 → 느린 현상, 안 됨 → 안 되는 현상
    var tl = t.slice(-1), tb = t.slice(0, -1), td = dec(tl);
    if (tl === '함') return tb + '하는 현상';
    if (tl === '됨') return tb + '되는 현상';
    if (/(?:있|없)음$/.test(t)) return t.slice(0, -1) + '는 현상';
    if (tl !== '음' && td && td.jong === JONG.M && tb.length) return tb + setJong(tl, JONG.N) + ' 현상';
    if (!quoted && /[가-힣A-Za-z0-9)]$/.test(t) && !/(?:함|됨|음|요|임)$/.test(t)) return t + ' 건';
    return null;
  }

  /* ------------------------------------------------------------------ */
  /* 분석                                                                */
  /* ------------------------------------------------------------------ */
  function analyze(text) {
    return splitSentences(text).map(function (s, i) {
      var c = classify(s);
      return {
        id: 's' + i,
        text: s,
        category: c.category,
        autoCategory: c.category,
        confidence: c.confidence,
        uncertain: UNCERTAIN_RE.test(s),
        internal: INTERNAL_RE.test(s),
        include: true
      };
    });
  }

  /* ------------------------------------------------------------------ */
  /* 답변 생성                                                           */
  /* ------------------------------------------------------------------ */
  function group(items, opts) {
    var g = { inquiry: [], result: [], cause: [], action: [], guide: [] };
    items.forEach(function (it) {
      if (!it.include) return;
      g[it.category].push({ item: it, text: polishSentence(it, opts) });
    });
    return g;
  }

  function texts(arr) { return arr.map(function (x) { return x.text; }); }
  function anyUncertain(arr) { return arr.some(function (x) { return x.item.uncertain; }); }

  function topicOf(g, opts) {
    for (var i = 0; i < g.inquiry.length; i++) {
      var t = inquiryTopic(g.inquiry[i].item.text, opts);
      if (t) return t;
    }
    return null;
  }

  function prefixFirst(arr, prefix, skipRe) {
    if (!arr.length) return arr;
    var out = arr.slice();
    if (!skipRe.test(out[0])) out[0] = prefix + out[0];
    return out;
  }

  function greeting(opts) {
    var name = (opts.customerName || '').trim();
    return '안녕하세요, ' + (name ? name.replace(/\s*님$/, '') + '님' : '고객님') + '.';
  }
  function signature(opts) {
    var s = (opts.sender || '').trim();
    return s ? s + ' 드림' : '';
  }

  var UNCERTAIN_NOTE = '※ 위 원인은 현재까지 확인된 내용을 바탕으로 한 추정이며, 추가 확인이 필요합니다.';

  function buildConcise(g, opts) {
    var topic = topicOf(g, opts);
    var lines = [greeting(opts)];
    lines.push('문의하신 ' + (topic || '내용') + '에 대해 안내드립니다.');
    lines.push('');
    var body = [];
    if (!g.cause.length && !g.action.length) body = body.concat(texts(g.result));
    body = body.concat(g.cause.length ? texts(g.cause) : [NEED('원인')]);
    body = body.concat(g.action.length ? texts(g.action) : [NEED('조치 내용')]);
    lines.push(body.join(' '));
    if (g.guide.length) lines.push(texts(g.guide).join(' '));
    lines.push('');
    lines.push('감사합니다.');
    var sig = signature(opts);
    if (sig) lines.push(sig);
    return lines.join('\n');
  }

  function buildPolite(g, opts) {
    var topic = topicOf(g, opts);
    var p = [];
    var head = [greeting(opts)];
    if (opts.apology) head.push('먼저 이용에 불편을 드려 죄송합니다.');
    head.push('문의하신 ' + (topic || '내용') + '에 대해 확인한 내용을 안내드립니다.');
    p.push(head.join('\n'));

    var r = texts(g.result);
    r = prefixFirst(r, '확인 결과, ', /^(?:확인|점검|조회|분석|로그|테스트|살펴|재현)/);
    p.push(r.length ? r.join(' ') : NEED('확인 결과'));

    var c = texts(g.cause);
    var causePara = c.length ? c.join(' ') : NEED('원인');
    if (c.length && anyUncertain(g.cause)) causePara += '\n' + UNCERTAIN_NOTE;
    p.push(causePara);

    var a = texts(g.action);
    a = prefixFirst(a, '이에 ', /^(?:이에|현재|우선|해당|따라서|그래서|이에 따라|조치|금일|오늘|내일|추후)/);
    p.push(a.length ? a.join(' ') : NEED('조치 내용'));

    if (g.guide.length) {
      var gd = texts(g.guide);
      if (/(?:바랍니다|부탁드립니다)\.$/.test(gd[0])) {
        gd = prefixFirst(gd, '번거로우시겠지만 ', /^(?:번거|혹시|만약|만일|참고|추가로|또한)/);
      }
      p.push(gd.join(' '));
    }

    var tail = ['추가로 궁금하신 점이 있으시면 언제든지 문의해 주시기 바랍니다.', '감사합니다.'];
    var sig = signature(opts);
    if (sig) tail.push(sig);
    p.push(tail.join('\n'));
    return p.join('\n\n');
  }

  function bullets(arr, need) {
    if (!arr.length) return '- ' + NEED(need);
    return arr.map(function (t) { return '- ' + t; }).join('\n');
  }

  function buildDetailed(g, opts) {
    var topic = topicOf(g, opts);
    var p = [];
    var head = [greeting(opts)];
    if (opts.apology) head.push('이용에 불편을 드려 죄송합니다.');
    head.push('문의하신 내용에 대해 확인한 결과를 아래와 같이 안내드립니다.');
    p.push(head.join('\n'));

    var inq = topic ? ['- ' + topic.replace(/\s건$/, '') + (/(현상|내용)$/.test(topic) ? '' : ' 관련 문의')] : null;
    p.push('■ 문의 내용\n' + (inq ? inq.join('\n') : bullets(texts(g.inquiry), '문의 내용')));
    p.push('■ 확인 결과\n' + bullets(texts(g.result), '확인 결과'));
    var cause = '■ 원인\n' + bullets(texts(g.cause), '원인');
    if (g.cause.length && anyUncertain(g.cause)) cause += '\n' + UNCERTAIN_NOTE;
    p.push(cause);
    p.push('■ 조치 내용\n' + bullets(texts(g.action), '조치 내용'));
    if (g.guide.length) p.push('■ 안내사항\n' + bullets(texts(g.guide), '안내사항'));

    var tail = ['추가로 궁금하신 점이 있으시면 언제든지 문의해 주시기 바랍니다.', '감사합니다.'];
    var sig = signature(opts);
    if (sig) tail.push(sig);
    p.push(tail.join('\n'));
    return p.join('\n\n');
  }

  function buildReply(items, opts) {
    opts = opts || {};
    var g = group(items || [], opts);
    var fmt = opts.format || 'polite';
    var text = fmt === 'concise' ? buildConcise(g, opts)
      : fmt === 'detailed' ? buildDetailed(g, opts)
        : buildPolite(g, opts);

    var missing = CATEGORIES.filter(function (c) { return c.required && !g[c.id].length; })
      .map(function (c) { return c.label; });
    return {
      text: text,
      missing: missing,
      uncertainCount: (items || []).filter(function (i) { return i.include && i.uncertain; }).length,
      internalCount: (items || []).filter(function (i) { return i.include && i.internal; }).length,
      counts: CATEGORIES.reduce(function (acc, c) { acc[c.id] = g[c.id].length; return acc; }, {})
    };
  }

  var api = {
    CATEGORIES: CATEGORIES,
    LABEL: LABEL,
    splitSentences: splitSentences,
    classify: classify,
    analyze: analyze,
    polishSentence: polishSentence,
    inquiryTopic: inquiryTopic,
    toFormal: toFormal,
    buildReply: buildReply
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else global.ReplyEngine = api;
})(typeof window !== 'undefined' ? window : this);
