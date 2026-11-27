"""WebSquare5 XML 화면 분석기.

입력 : WebSquare5 화면 XML
출력 : Fact 목록
  screen     {title}
  field      {label, ident, fieldType(date|code|number|text|check|radio), component, required,
              maxLength, minLength, options[], multi, defaultValue, dataType, allowChar}
  dateRange  {start, end, name}
  button     {ident, label, action, handler, submissions[], messages[], confirm}
  grid       {ident, label, dataList, columns[], rowButtons[], hasCheck, editable}
  generator  {ident}
  submission {ident, action, ref, target}
"""
import re

from .common import AnalysisResult, fact, src, labelize, guess_field_type
from .xmltree import parse_xml

INPUT_TAGS = {"input", "secret", "textarea", "inputCalendar", "calendar", "select1", "select", "checkbox",
              "radio", "autoComplete", "multiselect", "editor", "spinner"}
LABEL_TAGS = {"textbox", "span", "label"}
BUTTON_TAGS = {"trigger", "button", "anchor"}

ACTION_RULES = [
    ("조회", r"조회|검색|search|srch|inq|select|find|retrieve"),
    ("저장", r"저장|등록|save|reg|insert|신청|submit|apply|확정"),
    ("수정", r"수정|변경|modify|update|upd|mod|edit"),
    ("삭제", r"삭제|delete|del|remove|취하|wthdr"),
    ("엑셀다운로드", r"엑셀|excel|down|다운"),
    ("업로드", r"업로드|upload|upl"),
    ("초기화", r"초기화|reset|init|clear"),
    ("행추가", r"행추가|addrow|add_row|추가|add"),
    ("출력", r"출력|인쇄|print"),
    ("승인", r"승인|approve|aprv"),
    ("반려", r"반려|reject|rjct"),
    ("닫기", r"닫기|close|취소|cancel"),
]


def classify_action(text):
    t = (text or "").lower()
    for action, pat in ACTION_RULES:
        if re.search(pat, t, re.I):
            return action
    return "실행"


def _clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip(" :*")


class WebSquareAnalyzer:
    file_type = "XML"

    def analyze(self, text, file_name, is_cancelled=lambda: False):
        result = AnalysisResult(file_name, self.file_type)
        root = parse_xml(text)
        if root.tag not in ("html", "body", "head") and not root.find("body"):
            # MyBatis mapper 등 다른 XML은 상위에서 분기한다. 그래도 들어오면 경고 후 계속.
            result.warn("WebSquare5 화면 XML 구조(html/head/body)가 아닙니다. 컴포넌트만 추출합니다.")

        # ---- 화면 제목
        title_node = root.find("title")
        title = _clean(title_node.all_text()) if title_node is not None else ""
        if not title:
            title = labelize(re.sub(r"\.xml$", "", file_name, flags=re.I).split("/")[-1])
        result.add(fact("screen", src(file_name, "XML", 1, "화면"), title=title))

        # ---- dataMap / dataList 컬럼명 (ref 바인딩 → 라벨)
        data_names = {}
        for dc in root.find_all("dataMap", "dataList"):
            dc_id = dc.get("id", default="")
            for col in dc.find_all("key", "column"):
                cid = col.get("id")
                if cid:
                    nm = col.get("name") or ""
                    data_names[f"{dc_id}.{cid}"] = (nm, col.get("dataType"))
                    data_names.setdefault(cid, (nm, col.get("dataType")))

        # ---- submission
        submissions = {}
        for sb in root.find_all("submission"):
            sid = sb.get("id")
            if not sid:
                continue
            submissions[sid] = result.add(fact(
                "submission", src(file_name, "XML", sb.line, f"submission {sid} → {sb.get('action', 'actionId', default='')}"),
                ident=sid, action=sb.get("action", "actionId", default=""), ref=sb.get("ref", default=""),
                target=sb.get("target", default="")))
        for node in root.iter():
            aid = node.attrs.get("actionId")
            if aid and node.tag != "submission":
                result.add(fact("submission", src(file_name, "XML", node.line, f"actionId {aid}"),
                                ident=node.get("id", default=aid), action=aid, ref="", target=""))

        # ---- script 이벤트 핸들러
        handlers = self._parse_scripts(root)

        # ---- 컴포넌트 (문서 순서대로, 직전 라벨을 기억)
        last_label = None
        date_fields = []
        counts = {"field": 0, "button": 0, "grid": 0}
        for node in root.iter():
            if is_cancelled():
                break
            tag = node.tag
            if tag in LABEL_TAGS and not self._inside(node, "gridView"):
                lab = _clean(node.get("label", "value") or node.text)
                if lab and len(lab) <= 30:
                    last_label = (lab, node)
                continue
            if tag in INPUT_TAGS and not self._inside(node, "gridView"):
                if node.parent is not None and node.parent.tag in INPUT_TAGS:
                    continue
                f = self._field(node, file_name, last_label, data_names)
                if f:
                    result.add(f)
                    counts["field"] += 1
                    if f["fieldType"] == "date":
                        date_fields.append((f, node))
                last_label = None
            elif tag in BUTTON_TAGS:
                b = self._button(node, file_name, handlers, submissions)
                result.add(b)
                counts["button"] += 1
            elif tag == "gridView":
                result.add(self._grid(node, file_name, handlers))
                counts["grid"] += 1
            elif tag == "generator":
                result.add(fact("generator", src(file_name, "XML", node.line, f"generator {node.get('id', default='')}"),
                                ident=node.get("id", default="generator")))

        # ---- 시작일/종료일 쌍
        used = set()
        for i, (f1, n1) in enumerate(date_fields):
            if i in used:
                continue
            for j in range(i + 1, len(date_fields)):
                if j in used:
                    continue
                f2, n2 = date_fields[j]
                id1, id2 = (f1["ident"] or "").lower(), (f2["ident"] or "").lower()
                is_start = re.search(r"(st|start|strt|fr|from|bgn|시작)", id1 + f1["label"])
                is_end = re.search(r"(end|ed|to|fin|종료)", id2 + f2["label"])
                same_parent = n1.parent is n2.parent
                if (is_start and is_end) or (same_parent and j == i + 1):
                    used.update({i, j})
                    result.add(fact("dateRange", src(file_name, "XML", n1.line, f"{f1['ident']} ~ {f2['ident']}"),
                                    name=f"{f1['label']}~{f2['label']}", start=f1["label"], end=f2["label"]))
                    break

        result.summary = {"title": title, "fields": counts["field"], "buttons": counts["button"],
                          "grids": counts["grid"], "submissions": len(submissions), "handlers": len(handlers)}
        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _inside(node, tag):
        p = node.parent
        while p is not None:
            if p.tag == tag:
                return True
            p = p.parent
        return False

    def _field(self, node, file_name, last_label, data_names):
        tag = node.tag
        ident = node.get("id", default="")
        ref = node.get("ref", default="")
        ref_key = re.sub(r"^data:", "", ref)
        dn = data_names.get(ref_key) or data_names.get(ref_key.split(".")[-1]) if ref_key else None

        label = node.get("title", "label", "placeholder") or ""
        if not label and dn and dn[0]:
            label = dn[0]
        if not label and last_label:
            label = last_label[0]
        if not label:
            label = labelize(ident) or ident or tag
        label = _clean(label)

        appearance = node.get("appearance", default="")
        component, ftype = "input", None
        if tag in ("inputCalendar", "calendar"):
            component, ftype = "calendar", "date"
        elif tag == "textarea":
            component = "textarea"
        elif tag in ("select1", "autoComplete"):
            if appearance == "full":
                component, ftype = "radio", "radio"
            else:
                component, ftype = "selectbox", "code"
        elif tag in ("select", "checkbox", "multiselect"):
            if appearance == "minimal":
                component, ftype = "selectbox", "code"
            else:
                component, ftype = "checkbox", "check"
        elif tag == "radio":
            component, ftype = "radio", "radio"
        elif tag == "secret":
            component = "password"

        data_type = (node.get("dataType") or (dn[1] if dn else None) or "").lower()
        if not ftype:
            if data_type in ("date", "datetime"):
                ftype = "date"
            elif data_type in ("number", "float", "bigdecimal", "int"):
                ftype = "number"
            else:
                ftype = guess_field_type(label, ident) if guess_field_type(label, ident) != "code" else "text"

        options = []
        for item in node.find_all("item"):
            lab_n = item.find("label")
            val_n = item.find("value")
            options.append({"label": _clean(lab_n.all_text() if lab_n else ""),
                            "value": _clean(val_n.all_text() if val_n else "")})
        if not options:
            for itemset in node.find_all("itemset"):
                options.append({"label": f"(동적 코드: {itemset.get('nodeset', default='')})", "value": ""})

        req = node.get("mandatory", "required", "essential")
        required = True if (req or "").lower() in ("true", "y", "yes", "required") else None
        cls = node.get("class", default="")
        if required is None and re.search(r"\b(req|required|mandatory|essential)\b", cls):
            required = True

        def _int(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        return fact("field", src(file_name, "XML", node.line, f"<{node.raw_tag} id=\"{ident}\">"),
                    label=label, ident=ident, fieldType=ftype, component=component, required=required,
                    maxLength=_int(node.get("maxlength", "maxLength", "maxByteLength")),
                    minLength=_int(node.get("minlength", "minLength", "minByteLength")),
                    options=options, multi=(component == "checkbox" and len(options) > 1),
                    defaultValue=node.get("value", "chooseOptionLabel", default=None),
                    chooseOption=(node.get("chooseOption", default="") == "true"),
                    dataType=data_type, allowChar=node.get("allowChar", default=""),
                    displayFormat=node.get("displayFormat", default=""))

    def _button(self, node, file_name, handlers, submissions):
        ident = node.get("id", default="")
        lab_node = node.find("label")
        label = _clean(lab_node.all_text() if lab_node else "") or _clean(node.get("value", "title", "label") or node.text)
        if not label:
            label = labelize(ident) or ident or "버튼"
        handler_name = ""
        for k, v in node.attrs.items():
            if k.lower().endswith("onclick"):
                handler_name = re.sub(r"\(.*$", "", v).split(".")[-1].strip()
        h = dict(handlers.get(handler_name, {}))
        # 콜백 등 한 단계 호출된 scwin 함수까지 포함
        for ref in re.findall(r"scwin\.(\w+)", h.get("body", "")):
            sub_h = handlers.get(ref)
            if sub_h and ref != handler_name:
                h["body"] = h.get("body", "") + sub_h["body"]
                h["submissions"] = h.get("submissions", []) + sub_h["submissions"]
                h["messages"] = h.get("messages", []) + sub_h["messages"]
                h["confirm"] = h.get("confirm") or sub_h["confirm"]
        subs = list(dict.fromkeys(h.get("submissions", [])))
        for sid in submissions:
            if sid in h.get("body", "") and sid not in subs:
                subs.append(sid)
        actions = [submissions[s]["action"] for s in subs if s in submissions]
        return fact("button", src(file_name, "XML", node.line, f"<{node.raw_tag} id=\"{ident}\"> {label}"),
                    ident=ident, label=label, action=classify_action(f"{label} {ident}"),
                    handler=handler_name, submissions=subs, actions=actions,
                    messages=h.get("messages", [])[:5], confirm=h.get("confirm", False),
                    validates=h.get("validates", False))

    def _grid(self, node, file_name, handlers):
        ident = node.get("id", default="")
        headers = []
        header = node.find("header")
        if header is not None:
            for c in header.find_all("column"):
                headers.append(_clean(c.get("value", "label") or c.all_text()))
        body_cols = []
        gbody = node.find("gBody")
        if gbody is not None:
            body_cols = gbody.find_all("column")
        else:
            body_cols = [c for c in node.find_all("column") if c.get("inputType")]
        row_buttons, has_check, editable = [], False, False
        for i, c in enumerate(body_cols):
            it = (c.get("inputType", default="text") or "").lower()
            name = headers[i] if i < len(headers) else labelize(c.get("id", default=""))
            if it in ("button", "link", "image"):
                row_buttons.append(name or c.get("id", default="행 버튼"))
            elif it == "checkbox":
                has_check = True
            elif it in ("text", "select", "calendar", "textarea") and c.get("readOnly", default="true") == "false":
                editable = True
        if not any(headers):
            headers = [labelize(c.get("id", default="")) for c in body_cols if c.get("id")]
        if node.get("readOnly", default="") == "false":
            editable = True
        label = node.get("title", "label") or labelize(ident) or "목록"
        if not re.search(r"(목록|그리드|리스트|내역|결과)$", label):
            label = f"{label} 목록"
        return fact("grid", src(file_name, "XML", node.line, f"<{node.raw_tag} id=\"{ident}\">"),
                    ident=ident, label=_clean(label), dataList=node.get("dataList", default=""),
                    columns=[h for h in headers if h and h.lower() not in ("chk", "check")][:30],
                    rowButtons=row_buttons, hasCheck=has_check or node.get("checkAllType", default="") != "",
                    editable=editable)

    def _parse_scripts(self, root):
        handlers = {}
        for sc in root.find_all("script"):
            code = sc.all_text()
            if not code.strip():
                continue
            for m in re.finditer(r"(?:scwin\.)?(\w+)\s*=\s*(?:async\s+)?function\s*\([^)]*\)\s*\{|function\s+(\w+)\s*\([^)]*\)\s*\{", code):
                name = m.group(1) or m.group(2)
                start = m.end() - 1
                depth, i = 0, start
                while i < len(code):
                    ch = code[i]
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    i += 1
                body = code[start:i + 1]
                msgs = []
                for mm in re.finditer(r"(alert|confirm)\w*\s*\(([^;]*?)\)\s*;?", body, re.I):
                    for q in re.findall(r"[\"']([^\"']{2,80})[\"']", mm.group(2)):
                        if re.search(r"[가-힣]", q):
                            msgs.append(q)
                subs = re.findall(r"(?:executeSubmission|sbm\.execute|\.execute|executeSubmit)\s*\(\s*(?:\$p\s*,\s*)?[\"']?(\w+)", body)
                handlers[name] = {"body": body, "messages": msgs, "submissions": subs,
                                  "confirm": bool(re.search(r"confirm\s*\(", body, re.I)),
                                  "validates": bool(re.search(r"validat\w*\s*\(", body, re.I))}
        return handlers
