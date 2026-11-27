"""요구사항(자연어) 분석기 — 문장 패턴/키워드 규칙 기반.

입력 : 요구사항 텍스트 (직접 입력, .txt, Excel 셀 텍스트)
출력 : Fact 목록
  function     {name, action, object}           기능 (예: 제출내역 조회)
  field        {label, fieldType, required, maxLength, minLength}
  dateRange    {name, start, end}
  noResult     {message}
  resultDisplay{target}
  numericLimit {label, op, value}
  periodLimit  {value, unit}       조회 기간 최대 제한
  condition    {text}    '~인 경우' 등 조건 문장 (업무 의미 확인 필요)
  permission   {text}
  duplicate    {text}
  message      {text}
  unknown      {text}    규칙으로 해석하지 못한 문장 → '개발자 확인 필요'
"""
import re

from .common import AnalysisResult, fact, src, guess_field_type, canonical

ACTION_WORDS = {
    "조회": "조회", "검색": "조회", "등록": "등록", "저장": "저장", "추가": "등록", "수정": "수정",
    "변경": "수정", "삭제": "삭제", "취소": "취소", "취하": "취하", "승인": "승인", "반려": "반려",
    "다운로드": "다운로드", "업로드": "업로드", "출력": "출력", "인쇄": "출력", "추출": "추출",
    "전송": "전송", "발송": "발송", "신청": "신청", "접수": "접수", "확정": "확정", "생성": "생성",
}
_ACT = "|".join(sorted(ACTION_WORDS, key=len, reverse=True))
_VERB_END = r"(?:한다|하면|할|하는|하여|해야|합니다|하고|된다|되면|처리|하며|해|기능|할\s*수)"

RE_FUNC = re.compile(r"((?:[가-힣A-Za-z0-9]*[^가이은는을를의에만도과와고며면한된른던할될서로\s\W]\s)?[가-힣A-Za-z0-9]{2,})(?:을|를|이|가)?\s*(" + _ACT + r")" + _VERB_END)
RE_INPUT = re.compile(r"(.+?)(?:을|를)\s*(입력|선택|지정|체크)(?:하면|하고|한\s*후|하여|한다|해야|받|할|하는|합니다)")
RE_REQUIRED = re.compile(r"(.+?)\s*(?:은|는|이|가)?\s*(?:반드시\s*입력|필수\s*입력|필수값|필수\s*항목|필수)")
RE_MAXLEN = re.compile(r"([가-힣A-Za-z0-9 ]+?)\s*(?:은|는|이|가)?\s*(?:최대\s*)?(\d+)\s*(?:자|글자|byte|바이트|Byte)\s*(?:이내|이하|까지|를\s*초과할\s*수\s*없)")
RE_MINLEN = re.compile(r"([가-힣A-Za-z0-9 ]+?)\s*(?:은|는|이|가)?\s*(?:최소\s*)(\d+)\s*(?:자|글자|byte|바이트)")
RE_NUMLIMIT = re.compile(r"([가-힣A-Za-z0-9]+?)\s*(?:은|는|이|가)?\s*(\d[\d,]*)\s*(?:원|건|개|일|회|%|명|년|개월)?\s*(이상|이하|초과|미만)")
RE_PERIOD = re.compile(r"기간.{0,10}?(?:최대\s*)?(\d+)\s*(일|개월|달|년).{0,12}?(초과|넘|이내|까지)")
RE_NORESULT = re.compile(r"(결과|데이터|자료|내역|대상|목록).{0,8}(없|0\s*건|존재하지\s*않)")
RE_CONDITION = re.compile(r"(경우|때에?는?|시에?는?|라면|이면|하면)\b")
RE_PERMISSION = re.compile(r"(권한|관리자만|담당자만|본인만|로그인한|승인권자|접근\s*제한)")
RE_DUP = re.compile(r"(중복|이미\s*(등록|존재|신청))")
RE_MESSAGE = re.compile(r"(메시지|알림|경고|팝업|안내|확인\s*창|confirm|alert)", re.I)
RE_DISPLAY = re.compile(r"(표시|보여|출력|노출|조회된다|나타)")

NON_FIELD = {"사용자", "개발자", "담당자", "관리자", "고객", "해당", "조건", "결과", "화면", "버튼", "내용",
             "값", "정보", "항목", "자료", "데이터", "이를", "그"}
NON_OBJECT = {"중복", "다시", "모두", "함께", "직접", "자동", "일괄", "즉시", "바로", "정상", "추가로", "별도"}
_STOP_TOKENS = re.compile(r"^(?:사용자가|사용자는|담당자가|관리자가|고객이|화면에서|화면에|해당|조회\s*조건으로|조건으로)\s*")


def split_sentences(text):
    text = text.replace("\r", "")
    raw = re.split(r"(?<=[.!?。])\s+|\n+|(?<=다\.)", text)
    out = []
    for s in raw:
        s = s.strip(" \t-*•·●○■□▶>0123456789.)")
        if not s:
            continue
        # 연결 어미 기준 절 분리: '~이며,', '~하고,'
        parts = re.split(r"(?<=이며|하며|되며|하고|이고)\s*,\s*|(?<=며)\s*,\s*", s)
        out.extend(p.strip() for p in parts if p.strip())
    return out


def split_items(phrase):
    phrase = _STOP_TOKENS.sub("", phrase.strip())
    phrase = re.sub(r"^.*?(?:사용자|담당자|관리자|고객|신청인)(?:가|는|이|은)\s+", "", phrase)
    parts = re.split(r"\s*(?:,|/|·|\s및\s|\s또는\s|\s그리고\s)\s*", phrase)
    items = []
    for p in parts:
        sub = re.split(r"(?<=[가-힣])(?<!결)(?<!효)(?<!성)(?<!초)(?<!통)(?<!부)(과|와)\s+", p)
        sub = [x for x in sub if x not in ("과", "와")]
        items.extend(sub)
    cleaned = []
    for it in items:
        it = re.sub(r"(은|는|을|를|이|가|도|만)$", "", it.strip())
        it = re.sub(r"^(각각|모두|해당|입력한|선택한|조회할)\s*", "", it)
        it = it.strip(" '\"")
        if 1 < len(it) <= 20 and it not in NON_FIELD and not re.search(r"\s{1,}\S+\s+\S+\s+\S+", it):
            cleaned.append(it)
    return cleaned


class RequirementAnalyzer:
    file_type = "REQ"

    def analyze(self, text, file_name="요구사항(직접 입력)", is_cancelled=lambda: False):
        result = AnalysisResult(file_name, self.file_type)
        sentences = split_sentences(text or "")
        fields = {}      # canonical → fact
        functions = []

        def get_field(label, line, sentence, ftype=None):
            key = canonical(label)
            if key not in fields:
                fields[key] = result.add(fact("field", src(file_name, "요구사항", line, sentence),
                                              label=label, fieldType=ftype or guess_field_type(label),
                                              required=None, maxLength=None, minLength=None, ident=None))
            elif ftype and fields[key]["fieldType"] == "text":
                fields[key]["fieldType"] = ftype
            return fields[key]

        line_no = 0
        for sentence in sentences:
            if is_cancelled():
                break
            line_no += 1
            if re.fullmatch(r"[\[【<(#].*[\]】>)]?", sentence) and not re.search(r"(다|함|음|요)\.?$", sentence):
                continue  # 제목/머리말 줄
            matched = False
            s_src = src(file_name, "요구사항", line_no, sentence)

            # 1) 기능
            for m in RE_FUNC.finditer(sentence):
                obj, act = m.group(1), m.group(2)
                obj = re.sub(r"(을|를|이|가)$", "", obj)
                if " " in obj and obj.split(" ")[0] in NON_FIELD | NON_OBJECT:
                    obj = obj.split(" ")[1]
                obj = obj.replace(" ", "")
                if re.search(r"(으로|로)$", obj):
                    obj = re.sub(r"(으로|로)$", "", obj)
                if obj in NON_FIELD or obj in ACTION_WORDS or obj in NON_OBJECT or obj.endswith("만"):
                    continue
                name = f"{obj} {act}"
                if not any(f["name"] == name for f in functions):
                    functions.append(result.add(fact("function", s_src, name=name,
                                                     action=ACTION_WORDS[act], object=obj)))
                matched = True

            # 2) 입력/선택 항목
            for m in RE_INPUT.finditer(sentence):
                verb = m.group(2)
                for item in split_items(m.group(1)):
                    if item.endswith("기간"):
                        f_s = get_field("시작일", line_no, sentence, "date")
                        f_e = get_field("종료일", line_no, sentence, "date")
                        result.add(fact("dateRange", s_src, name=item, start=f_s["label"], end=f_e["label"]))
                    else:
                        ftype = "code" if verb in ("선택", "체크") and guess_field_type(item) != "date" else None
                        get_field(item, line_no, sentence, ftype)
                    matched = True

            # 3) 필수값
            m = RE_REQUIRED.search(sentence)
            if m:
                for item in split_items(m.group(1)):
                    if item.endswith("기간"):
                        for lab in ("시작일", "종료일"):
                            get_field(lab, line_no, sentence, "date")["required"] = True
                    else:
                        get_field(item, line_no, sentence)["required"] = True
                matched = True

            # 4) 길이 제한
            for m in RE_MAXLEN.finditer(sentence):
                for item in split_items(m.group(1)) or [m.group(1).strip()]:
                    get_field(item, line_no, sentence)["maxLength"] = int(m.group(2))
                matched = True
            for m in RE_MINLEN.finditer(sentence):
                for item in split_items(m.group(1)) or [m.group(1).strip()]:
                    get_field(item, line_no, sentence)["minLength"] = int(m.group(2))
                matched = True

            # 5) 조회 기간 제한
            pm = RE_PERIOD.search(sentence)
            if pm:
                unit = "개월" if pm.group(2) == "달" else pm.group(2)
                result.add(fact("periodLimit", s_src, value=int(pm.group(1)), unit=unit))
                matched = True
            # 5-1) 숫자 범위
            if not RE_MAXLEN.search(sentence) and not pm:
                for m in RE_NUMLIMIT.finditer(sentence):
                    label = re.sub(r"(은|는|이|가)$", "", m.group(1))
                    if label in NON_FIELD:
                        continue
                    get_field(label, line_no, sentence, "number")
                    result.add(fact("numericLimit", s_src, label=label, op=m.group(3),
                                    value=m.group(2).replace(",", "")))
                    matched = True

            # 6) 조회 결과 없음
            if RE_NORESULT.search(sentence):
                msg = None
                mm = re.search(r"['\"‘“]([^'\"’”]+)['\"’”]", sentence)
                if mm:
                    msg = mm.group(1)
                elif RE_MESSAGE.search(sentence):
                    msg = "안내 메시지"
                result.add(fact("noResult", s_src, message=msg))
                matched = True
            elif RE_DISPLAY.search(sentence) and re.search(r"(결과|목록|내역|그리드|표)", sentence):
                result.add(fact("resultDisplay", s_src, target=sentence))
                matched = True

            # 7) 권한 / 중복
            if RE_PERMISSION.search(sentence):
                result.add(fact("permission", s_src, text=sentence))
                matched = True
            if RE_DUP.search(sentence):
                result.add(fact("duplicate", s_src, text=sentence))
                matched = True

            # 8) 기타 조건 문장 (위 규칙으로 처리되지 않은 '경우')
            if not matched and RE_CONDITION.search(sentence):
                result.add(fact("condition", s_src, text=sentence))
                matched = True
            if not matched and RE_MESSAGE.search(sentence):
                result.add(fact("message", s_src, text=sentence))
                matched = True

            if not matched and len(sentence) >= 6:
                result.add(fact("unknown", s_src, text=sentence))

        # 조회 기능이 있는데 결과 표시 문장이 없으면 기본 결과 표시 사실 추가
        if any(f["action"] == "조회" for f in functions) and not any(f["kind"] == "resultDisplay" for f in result.facts):
            result.add(fact("resultDisplay", functions[0]["src"], target=functions[0]["name"]))

        result.summary = {"sentences": len(sentences), "functions": [f["name"] for f in functions],
                          "fields": [f["label"] for f in fields.values()]}
        return result
