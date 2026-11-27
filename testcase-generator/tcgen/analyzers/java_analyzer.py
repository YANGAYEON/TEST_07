"""Java 소스 분석기 (정규식 + 괄호 매칭 기반 경량 파서).

향후 Java AST 기반 분석기로 교체할 수 있도록 analyze() 인터페이스(텍스트 → Fact)만 유지하면 된다.

출력 Fact
  javaMethod   {cls, method, params[], returnType, throws[], calls[], action}
  javaNull     {var, varLabel, negate, throws, exType, message, returns, method, cls}
  javaEmpty    {var, varLabel, negate, throws, exType, message, returns, method, cls}
  javaEqGroup  {var, varLabel, values[{value, comment, throws}], hasElse, elseComment, method, cls}
  javaCompare  {left, leftLabel, op, right, throws, exType, comment, method, cls}
  javaCond     {expr, throws, exType, comment, hasElse, method, cls}
  javaSwitch   {expr, exprLabel, cases[], hasDefault, method, cls}
  javaCatch    {exType, rethrow, method, cls}
  javaLoop     {loopType, expr, method, cls}
"""
import re

from .common import AnalysisResult, fact, src, labelize, line_of

KEYWORDS = {"if", "for", "while", "switch", "catch", "synchronized", "return", "new", "else", "try", "do", "throw"}


def skeletonize(code):
    """(주석 제거본, 주석+문자열 내용 마스킹본) — 인덱스는 원본과 동일."""
    nc, sk = [], []
    i, n = 0, len(code)
    while i < n:
        c = code[i]
        if code.startswith("//", i):
            j = code.find("\n", i)
            j = n if j == -1 else j
            nc.append(" " * (j - i)); sk.append(" " * (j - i)); i = j
        elif code.startswith("/*", i):
            j = code.find("*/", i + 2)
            j = n if j == -1 else j + 2
            seg = re.sub(r"[^\n]", " ", code[i:j])
            nc.append(seg); sk.append(seg); i = j
        elif c in "\"'":
            q = c
            j = i + 1
            while j < n and code[j] != q and code[j] != "\n":
                j += 2 if code[j] == "\\" else 1
            j = min(j + 1, n)
            nc.append(code[i:j])
            sk.append(q + " " * max(0, j - i - 2) + (q if j - i >= 2 else ""))
            i = j
        else:
            nc.append(c); sk.append(c); i += 1
    return "".join(nc), "".join(sk)


def match_close(sk, pos, open_ch="(", close_ch=")"):
    depth = 0
    for i in range(pos, len(sk)):
        if sk[i] == open_ch:
            depth += 1
        elif sk[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return len(sk) - 1


def first_comment(original, start, end):
    m = re.search(r"//\s*(.+)|/\*+\s*(.+?)\s*\*+/", original[start:end])
    if m:
        return (m.group(1) or m.group(2) or "").strip()[:60]
    return ""


def split_top(expr, ops=("&&", "||"), angle=False):
    out, depth, cur, i = [], 0, "", 0
    while i < len(expr):
        ch = expr[i]
        if ch == "(" or (angle and ch == "<"):
            depth += 1
        elif ch == ")" or (angle and ch == ">"):
            depth -= 1
        op = next((o for o in ops if expr.startswith(o, i)), None)
        if depth == 0 and op:
            out.append(cur.strip()); cur = ""; i += len(op); continue
        cur += ch
        i += 1
    out.append(cur.strip())
    return [o for o in out if o]


def strip_parens(e):
    e = e.strip()
    while e.startswith("(") and match_close(e, 0) == len(e) - 1:
        e = e[1:-1].strip()
    return e


def method_action(name):
    n = name.lower()
    for act, pat in (("조회", r"^(select|get|find|search|list|retrieve|inquire|read|count)"),
                     ("등록", r"^(insert|save|regist|reg|create|add|apply)"),
                     ("수정", r"^(update|modify|change|upd|edit)"),
                     ("삭제", r"^(delete|remove|del|cancel|withdraw)"),
                     ("처리", r"^(process|proc|exec|handle|run|do)")):
        if re.search(pat, n):
            return act
    return "실행"


class JavaAnalyzer:
    file_type = "JAVA"

    def analyze(self, text, file_name, is_cancelled=lambda: False):
        result = AnalysisResult(file_name, self.file_type)
        nc, sk = skeletonize(text)
        cls_m = re.search(r"\b(class|interface|enum)\s+(\w+)", sk)
        cls = cls_m.group(2) if cls_m else re.sub(r"\.java$", "", file_name.split("/")[-1], flags=re.I)

        # 메서드 탐지: 중괄호 깊이 1(클래스 본문)에 있는 선언
        depth_at = []
        d = 0
        for ch in sk:
            depth_at.append(d)
            if ch == "{":
                d += 1
            elif ch == "}":
                d -= 1
        method_re = re.compile(
            r"(?:(?:public|protected|private|static|final|synchronized|abstract|default)\s+)*"
            r"(?:<[^>]+>\s+)?([\w<>\[\],.?\s]+?)\s+(\w+)\s*\(([^)]*)\)\s*(?:throws\s+([\w.,\s]+?))?\s*\{")
        methods = []
        class_depth = 1 if cls_m else 0
        for m in method_re.finditer(sk):
            name = m.group(2)
            if name in KEYWORDS or m.group(1).strip().split()[-1] in KEYWORDS:
                continue
            if depth_at[m.start(2)] != class_depth:
                continue
            body_start = m.end() - 1
            body_end = match_close(sk, body_start, "{", "}")
            ret = re.sub(r"^(?:(?:public|protected|private|static|final|synchronized|abstract|default)\s+)*", "",
                         re.sub(r"\s+", " ", m.group(1).strip())) or "void"
            if ret.split(" ")[-1] in ("class", "new", "return", "else"):
                continue
            params = [p.strip() for p in split_top(nc[m.start(3):m.end(3)], (",",), angle=True) if p.strip()]
            methods.append({"name": name, "ret": ret, "params": params,
                            "throws": [t.strip() for t in (m.group(4) or "").split(",") if t.strip()],
                            "start": m.start(), "body": (body_start, body_end)})

        if not methods:
            # 클래스/메서드 선언이 없는 코드 조각 → 전체를 하나의 단위로 분석
            methods.append({"name": "(코드 조각)", "ret": "", "params": [], "throws": [],
                            "start": 0, "body": (0, len(sk) - 1)})
            result.warn("메서드 선언을 찾지 못해 전체 코드를 하나의 단위로 분석했습니다.")

        cond_count = 0
        for mt in methods:
            if is_cancelled():
                break
            bs, be = mt["body"]
            line = line_of(text, mt["start"])
            calls = list(dict.fromkeys(
                f"{a}.{b}" for a, b in re.findall(r"\b(\w*(?:Mapper|Dao|DAO|Service|Repository))\.(\w+)\s*\(", nc[bs:be])))
            result.add(fact("javaMethod", src(file_name, "Java", line, f"{cls}.{mt['name']}({', '.join(mt['params'])})"),
                            cls=cls, method=mt["name"], params=mt["params"], returnType=mt["ret"],
                            throws=mt["throws"], calls=calls[:8], action=method_action(mt["name"])))
            cond_count += self._body(text, nc, sk, bs, be, cls, mt["name"], file_name, result)

        result.summary = {"class": cls, "methods": [m["name"] for m in methods], "conditions": cond_count}
        return result

    # ------------------------------------------------------------------
    def _block_info(self, text, nc, sk, pos, limit):
        """pos(조건 괄호 다음) 이후의 블록 범위와 throw/return 정보."""
        i = pos
        while i < limit and sk[i].isspace():
            i += 1
        if i < limit and sk[i] == "{":
            end = match_close(sk, i, "{", "}")
        else:
            end = sk.find(";", i)
            end = limit if end == -1 else end
        body = nc[i:end + 1]
        tm = re.search(r"throw\s+new\s+([\w.]+)\s*\(\s*(\"[^\"]*\")?", body)
        info = {"start": i, "end": end, "throws": bool(tm), "exType": tm.group(1) if tm else None,
                "message": (tm.group(2) or "").strip('"') if tm else "",
                "returns": bool(re.search(r"\breturn\b", body)),
                "comment": first_comment(text, i, end + 1)}
        return info

    def _body(self, text, nc, sk, bs, be, cls, method, file_name, result):
        count = 0
        consumed = set()
        for m in re.finditer(r"\bif\s*\(", sk[bs:be]):
            pos = bs + m.start()
            if pos in consumed:
                continue
            # 체인 수집: if (...) {...} else if (...) {...} else {...}
            chain, has_else, else_comment = [], False, ""
            cur = pos
            while True:
                p_open = sk.index("(", cur)
                p_close = match_close(sk, p_open)
                cond = re.sub(r"\s+", " ", nc[p_open + 1:p_close]).strip()
                info = self._block_info(text, nc, sk, p_close + 1, be)
                info["cond"] = cond
                info["line"] = line_of(text, cur)
                chain.append(info)
                consumed.add(cur)
                rest = sk[info["end"] + 1:be]
                em = re.match(r"\s*else\s+if\s*\(", rest)
                if em:
                    cur = info["end"] + 1 + rest.index("if", em.start())
                    continue
                em = re.match(r"\s*else\b", rest)
                if em:
                    has_else = True
                    einfo = self._block_info(text, nc, sk, info["end"] + 1 + em.end(), be)
                    else_comment = einfo["comment"]
                break
            count += len(chain)
            self._emit_chain(chain, has_else, else_comment, cls, method, file_name, result)

        # switch
        for m in re.finditer(r"\bswitch\s*\(", sk[bs:be]):
            pos = bs + m.start()
            p_open = sk.index("(", pos)
            p_close = match_close(sk, p_open)
            expr = nc[p_open + 1:p_close].strip()
            b_open = sk.find("{", p_close)
            b_close = match_close(sk, b_open, "{", "}")
            body = nc[b_open:b_close]
            cases = [c.strip() for c in re.findall(r"\bcase\s+([^:]+?)\s*(?::|->)", body)]
            result.add(fact("javaSwitch", src(file_name, "Java", line_of(text, pos), f"switch ({expr})"),
                            expr=expr, exprLabel=labelize(re.sub(r"\W.*$", "", expr)), cases=cases[:12],
                            hasDefault=bool(re.search(r"\bdefault\s*(?::|->)", body)), method=method, cls=cls))
            count += 1
        # catch
        for m in re.finditer(r"\bcatch\s*\(\s*([\w.|\s]+?)\s+\w+\s*\)", sk[bs:be]):
            pos = bs + m.start()
            b_open = sk.find("{", pos + len(m.group(0)) - 1)
            b_close = match_close(sk, b_open, "{", "}")
            body = nc[b_open:b_close]
            rt = re.search(r"throw\s+new\s+([\w.]+)", body)
            result.add(fact("javaCatch", src(file_name, "Java", line_of(text, pos), m.group(0)),
                            exType=re.sub(r"\s+", "", m.group(1)), rethrow=rt.group(1) if rt else None,
                            method=method, cls=cls))
            count += 1
        # 반복문
        for m in re.finditer(r"\b(for|while)\s*\(|\.forEach\s*\(|\.stream\s*\(\s*\)", sk[bs:be]):
            pos = bs + m.start()
            p_open = sk.find("(", pos)
            p_close = match_close(sk, p_open)
            expr = re.sub(r"\s+", " ", nc[p_open + 1:p_close]).strip()[:80]
            result.add(fact("javaLoop", src(file_name, "Java", line_of(text, pos), m.group(0) + expr + ")"),
                            loopType=(m.group(1) or "stream"), expr=expr, method=method, cls=cls))
            count += 1
        return count

    def _emit_chain(self, chain, has_else, else_comment, cls, method, file_name, result):
        # 동일 변수 등가 비교 체인 → javaEqGroup
        eqs = [self._parse_eq(c["cond"]) for c in chain]
        if all(eqs) and len({e[0] for e in eqs}) == 1:
            var = eqs[0][0]
            result.add(fact("javaEqGroup", src(file_name, "Java", chain[0]["line"], " / ".join(c["cond"] for c in chain)),
                            var=var, varLabel=labelize(var.split(".")[-1]),
                            values=[{"value": e[1], "comment": c["comment"], "throws": c["exType"]} for e, c in zip(eqs, chain)],
                            hasElse=has_else, elseComment=else_comment, method=method, cls=cls))
            return
        for idx, c in enumerate(chain):
            last = idx == len(chain) - 1
            atoms = split_top(strip_parens(c["cond"]))
            unhandled = False
            base = dict(throws=c["throws"], exType=c["exType"], message=c["message"], returns=c["returns"],
                        comment=c["comment"], method=method, cls=cls)
            for atom in atoms:
                a = strip_parens(atom)
                s = src(file_name, "Java", c["line"], f"if ({c['cond']})")
                m = re.match(r"^([\w.]+(?:\(\))?)\s*(==|!=)\s*null$|^null\s*(==|!=)\s*([\w.]+)$", a)
                if m:
                    var = m.group(1) or m.group(4)
                    neg = (m.group(2) or m.group(3)) == "!="
                    result.add(fact("javaNull", s, var=var, varLabel=labelize(var.split(".")[-1].replace("()", "")),
                                    negate=neg, **base))
                    continue
                m = re.match(r"^(!)?\s*(?:\w+Utils?\.|Objects\.)?(isEmpty|isBlank|isNullOrEmpty|isNull|isNotEmpty|isNotBlank)\s*\(\s*([\w.]+)\s*\)$", a) \
                    or re.match(r"^(!)?\s*([\w.]+)\.(isEmpty|isBlank)\s*\(\s*\)$", a)
                if m:
                    groups = m.groups()
                    if groups[1] in ("isEmpty", "isBlank", "isNullOrEmpty", "isNull", "isNotEmpty", "isNotBlank"):
                        var, fn = groups[2], groups[1]
                    else:
                        var, fn = groups[1], groups[2]
                    neg = bool(groups[0]) ^ fn.startswith("isNot")
                    result.add(fact("javaEmpty", s, var=var, varLabel=labelize(var.split(".")[-1]), negate=neg, **base))
                    continue
                m = re.match(r"^([\w.]+(?:\.(?:size|length)\(\))?)\s*(>=|<=|>|<|==|!=)\s*([\w.\-\"']+)$", a)
                if m and not self._parse_eq(a):
                    left = m.group(1)
                    result.add(fact("javaCompare", s, left=left, leftLabel=labelize(re.sub(r"\.(size|length)\(\)$", "", left).split(".")[-1]),
                                    op=m.group(2), right=m.group(3), **base))
                    continue
                m = re.match(r"^([\w.]+)\.compareTo\(\s*([\w.]+)\s*\)\s*(>=|<=|>|<|==|!=)\s*0$", a)
                if m:
                    result.add(fact("javaCompare", s, left=m.group(1), leftLabel=labelize(m.group(1)),
                                    op=m.group(3), right=m.group(2), compareTo=True, **base))
                    continue
                eq = self._parse_eq(a)
                if eq:
                    result.add(fact("javaEqGroup", s, var=eq[0], varLabel=labelize(eq[0].split(".")[-1]),
                                    values=[{"value": eq[1], "comment": c["comment"], "throws": c["exType"]}],
                                    hasElse=has_else and last, elseComment=else_comment, method=method, cls=cls,
                                    partOfCompound=len(atoms) > 1))
                    continue
                unhandled = True
            if unhandled:
                result.add(fact("javaCond", src(file_name, "Java", c["line"], f"if ({c['cond']})"),
                                expr=c["cond"], hasElse=has_else and last, compound=len(atoms) > 1, **base))

    @staticmethod
    def _parse_eq(cond):
        c = strip_parens(cond)
        m = re.match(r'^"([^"]*)"\s*\.\s*equals(?:IgnoreCase)?\s*\(\s*([\w.()]+)\s*\)$', c)
        if m:
            return (m.group(2), m.group(1))
        m = re.match(r'^([\w.()]+)\s*\.\s*equals(?:IgnoreCase)?\s*\(\s*"([^"]*)"\s*\)$', c)
        if m:
            return (m.group(1), m.group(2))
        m = re.match(r'^Objects\.equals\(\s*([\w.]+)\s*,\s*"([^"]*)"\s*\)$', c)
        if m:
            return (m.group(1), m.group(2))
        m = re.match(r"^([\w.]+)\s*==\s*('.'|-?\d+|[A-Z_][A-Z0-9_.]*)$", c)
        if m and m.group(2) != "null":
            return (m.group(1), m.group(2).strip("'"))
        return None
