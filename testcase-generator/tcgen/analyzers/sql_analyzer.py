"""SQL 분석기 (일반 .sql 및 MyBatis/iBatis Mapper XML).

SQL을 실행하거나 DB에 접속하지 않는다. 구조와 조건만 문자열 수준으로 분석한다.

출력 Fact
  sqlStatement {stmtType, tables[], sqlId, hasWhere, columns[], setColumns[]}
  field        {label, ident, fieldType, required, origin='sql'}    SELECT WHERE 조건 파라미터
  dateRange    {start, end, name, inclusive, column}
  sqlCond      {op, column, colLabel, params[], literal, negate, optional, stmtType, sqlId, subquery}
  sqlJoin      {joinType, table}
  sqlCase      {whens[], hasElse}
  sqlNvl       {column, colLabel, default}
  sqlGroupBy / sqlOrderBy {columns[]}
  sqlPaging    {}
  sqlDistinct  {}
  sqlDynamic   {param, test}           MyBatis <if>/<when> 동적 조건
  sqlInjection {param}                 ${} 문자열 치환 사용
"""
import re

from .common import AnalysisResult, fact, src, labelize, guess_field_type, line_of
from .xmltree import parse_xml

PARAM_RE = re.compile(r"(?<![:\w]):(\w+)|#\{\s*(\w+)[^}]*\}|\$\{\s*(\w+)[^}]*\}")
STMT_TAGS = {"select", "insert", "update", "delete", "sql", "statement", "procedure"}
CLAUSE_END = re.compile(r"\b(GROUP\s+BY|ORDER\s+BY|HAVING|UNION|INTERSECT|MINUS|FETCH|LIMIT|OFFSET|FOR\s+UPDATE|CONNECT\s+BY|START\s+WITH)\b", re.I)


def mask_sql(sql):
    """주석 제거 + 문자열 내용은 같은 길이의 공백으로 치환(구조 분석용)."""
    out = []
    nocomment = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i)); nocomment.append(" " * (j - i)); i = j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j == -1 else j + 2
            seg = re.sub(r"[^\n]", " ", sql[i:j])
            out.append(seg); nocomment.append(seg); i = j
        elif c == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'" and j + 1 < n and sql[j + 1] == "'":
                    j += 2; continue
                if sql[j] == "'":
                    break
                j += 1
            j = min(j + 1, n)
            out.append("'" + re.sub(r"[^\n]", " ", sql[i + 1:j - 1]) + ("'" if j - i >= 2 else ""))
            nocomment.append(sql[i:j]); i = j
        else:
            out.append(c); nocomment.append(c); i += 1
    return "".join(nocomment), "".join(out)


def depth_map(sk):
    d, arr = 0, []
    for ch in sk:
        if ch == "(":
            d += 1
            arr.append(d)
        elif ch == ")":
            arr.append(d)
            d -= 1
        else:
            arr.append(d)
    return arr


def params_in(text):
    out = []
    for m in PARAM_RE.finditer(text):
        p = m.group(1) or m.group(2) or m.group(3)
        if p and p.upper() not in ("MI", "SS", "HH24", "MM"):
            out.append(p)
    return out


def strip_fn(col):
    """NVL(A.REQ_DT, ...) / TO_CHAR(REQ_DT,'YYYYMMDD') → REQ_DT"""
    c = col.strip()
    nvl = bool(re.match(r"(NVL|COALESCE|IFNULL|ISNULL)\s*\(", c, re.I))
    for _ in range(3):
        m = re.match(r"^\w+\s*\((.*)\)$", c, re.S)
        if not m:
            break
        c = m.group(1).split(",")[0].strip()
    c = re.sub(r"^\w+\.", "", c)
    return c, nvl


class SqlAnalyzer:
    file_type = "SQL"

    def analyze(self, text, file_name, is_cancelled=lambda: False):
        result = AnalysisResult(file_name, self.file_type)
        stripped = text.lstrip("﻿ \r\n\t")
        statements = []   # (sql_text, sql_id, line, optional_params, dynamic_tests)
        if stripped.startswith("<"):
            statements = self._from_mapper(text, result)
        else:
            nocomment, sk = mask_sql(text)
            start = 0
            for m in re.finditer(r";", sk):
                seg = nocomment[start:m.start()]
                if seg.strip():
                    statements.append((seg, None, line_of(text, start + len(seg) - len(seg.lstrip())), set(), []))
                start = m.end()
            seg = nocomment[start:]
            if seg.strip():
                statements.append((seg, None, line_of(text, start + len(seg) - len(seg.lstrip())), set(), []))

        counts = {}
        for idx, (sql, sql_id, line, optional, dyn) in enumerate(statements, 1):
            if is_cancelled():
                break
            try:
                t = self._statement(sql, sql_id or f"SQL#{idx}", line, optional, dyn, file_name, result)
                if t:
                    counts[t] = counts.get(t, 0) + 1
            except Exception as e:  # 개별 문장 오류는 경고로 남기고 계속
                result.warn(f"SQL 문장 분석 실패: {e}", line)
        if not statements:
            result.warn("분석 가능한 SQL 문장이 없습니다.")
        result.summary = {"statements": len(statements), "types": counts}
        return result

    # ------------------------------------------------------------------
    def _from_mapper(self, text, result):
        root = parse_xml(text)
        stmts = []
        sql_fragments = {n.get("id"): n for n in root.find_all("sql") if n.get("id")}

        def flatten(node, optional, dyn):
            if node.tag in ("if", "when"):
                test = node.get("test", default="")
                inner_params = params_in(node.all_text())
                for p in inner_params:
                    optional.add(p)
                dyn.append({"tag": node.tag, "test": test, "params": inner_params, "line": node.line})
            prefix = {"where": " WHERE ", "set": " SET "}.get(node.tag, "")
            if node.tag == "trim":
                prefix = " " + node.get("prefix", default="") + " "
            if node.tag == "foreach":
                return f" {node.get('open', default='(')}#{{{node.get('item', default='item')}}}{node.get('close', default=')')} "
            if node.tag == "include":
                frag = sql_fragments.get(node.get("refid"))
                return flatten(frag, optional, dyn) if frag is not None and frag is not node else " "
            body = _ordered_text(node, lambda c: flatten(c, optional, dyn))
            if node.tag in ("where", "trim", "set"):
                body = re.sub(r"^\s*(AND|OR)\b", "", body, flags=re.I)
                body = re.sub(r",\s*$", "", body)
            return prefix + body

        for n in root.iter():
            if n.tag in ("select", "insert", "update", "delete") and n is not root:
                optional, dyn = set(), []
                sql = flatten(n, optional, dyn)
                stmts.append((sql, n.get("id", default=n.tag), n.line, optional, dyn))
        return stmts

    def _statement(self, sql, sql_id, line, optional, dyn, file_name, result):
        nocomment, sk = mask_sql(sql)
        upper = sk.upper()
        m = re.search(r"\b(SELECT|INSERT|UPDATE|DELETE|MERGE|WITH)\b", upper)
        if not m:
            result.warn(f"{sql_id}: SQL 유형을 인식할 수 없습니다.", line)
            return None
        stype = m.group(1)
        if stype == "WITH":
            m2 = re.search(r"\)\s*(SELECT|INSERT|UPDATE|DELETE)\b", upper)
            stype = m2.group(1) if m2 else "SELECT"
        if stype == "MERGE":
            stype = "MERGE"

        def S(detail, ln_offset_idx=None):
            ln = line + (sql[:ln_offset_idx].count("\n") if ln_offset_idx is not None else 0)
            return src(file_name, "SQL", ln, f"[{sql_id}] {re.sub(r'\s+', ' ', detail).strip()}")

        tables = []
        for tm in re.finditer(r"\b(?:FROM|JOIN|INTO|UPDATE|MERGE\s+INTO)\s+([A-Za-z_][\w.$#]*)", upper):
            t = nocomment[tm.start(1):tm.end(1)]
            if t.upper() not in ("SELECT", "DUAL", "SET") and t not in tables:
                tables.append(t)

        depth = depth_map(sk)
        top = depth[m.start()] if m.start() < len(depth) else 0
        if "(" in sk[:m.start()] and stype == "SELECT":
            top = depth[m.start()]

        # WHERE 절 (최상위)
        where_text, where_pos = "", None
        for wm in re.finditer(r"\bWHERE\b", upper):
            if depth[wm.start()] == top:
                where_pos = wm.end()
                end = len(sk)
                for em in CLAUSE_END.finditer(upper, wm.end()):
                    if depth[em.start()] == top:
                        end = em.start()
                        break
                for em in re.finditer(r"\)", sk[wm.end():]):
                    pos = wm.end() + em.start()
                    if depth[pos] == top and top > 0:
                        end = min(end, pos)
                        break
                where_text = nocomment[wm.end():end]
                break

        # 컬럼 목록
        columns, set_columns = [], []
        if stype == "INSERT":
            cm = re.search(r"INTO\s+[\w.$#]+\s*\(([^)]*)\)", nocomment, re.I)
            if cm:
                columns = [c.strip() for c in cm.group(1).split(",") if c.strip()]
        if stype == "UPDATE":
            sm = re.search(r"\bSET\b(.*?)(\bWHERE\b|$)", sk, re.I | re.S)
            if sm:
                seg = nocomment[sm.start(1):sm.end(1)]
                set_columns = [re.sub(r"^\w+\.", "", a.split("=")[0].strip()) for a in _split_top(seg, ",") if "=" in a]

        result.add(fact("sqlStatement", S(f"{stype} {', '.join(tables[:3])}"), stmtType=stype, tables=tables,
                        sqlId=sql_id, hasWhere=bool(where_text.strip()), columns=columns,
                        setColumns=set_columns, line=line))

        # ${} 문자열 치환
        for im in re.finditer(r"\$\{\s*(\w+)", nocomment):
            result.add(fact("sqlInjection", S(im.group(0), im.start()), param=im.group(1), sqlId=sql_id))

        # 동적 조건
        for d in dyn:
            for p in d["params"]:
                result.add(fact("sqlDynamic", src(file_name, "SQL", d["line"], f"[{sql_id}] <{d['tag']} test=\"{d['test']}\">"),
                                param=p, test=d["test"], tag=d["tag"], sqlId=sql_id, label=labelize(p)))

        # JOIN
        for jm in re.finditer(r"\b(LEFT|RIGHT|FULL|INNER|CROSS)?\s*(OUTER\s+)?JOIN\s+([\w.$#]+)", upper):
            jt = (jm.group(1) or "INNER").upper()
            tbl = nocomment[jm.start(3):jm.end(3)]
            result.add(fact("sqlJoin", S(jm.group(0), jm.start()), joinType=jt, table=tbl, sqlId=sql_id))
        if "(+)" in sk:
            result.add(fact("sqlJoin", S("Oracle (+) 외부 조인"), joinType="LEFT", table="(+)", sqlId=sql_id))

        # CASE
        for cm in re.finditer(r"\bCASE\b(.*?)\bEND\b", sk, re.I | re.S):
            seg = nocomment[cm.start():cm.end()]
            whens = [re.sub(r"\s+", " ", w).strip() for w in re.findall(r"\bWHEN\b(.*?)\bTHEN\b", seg, re.I | re.S)]
            if whens:
                result.add(fact("sqlCase", S(seg[:120], cm.start()), whens=whens[:8],
                                hasElse=bool(re.search(r"\bELSE\b", seg, re.I)), sqlId=sql_id))
        # NVL (조회 컬럼)
        sel_end = where_pos or len(sk)
        for nm in re.finditer(r"\b(NVL|COALESCE|IFNULL|ISNULL)\s*\(\s*([\w.]+)\s*,\s*([^)]+)\)", nocomment[:sel_end], re.I):
            col = re.sub(r"^\w+\.", "", nm.group(2))
            result.add(fact("sqlNvl", S(nm.group(0), nm.start()), column=col, colLabel=labelize(col),
                            default=nm.group(3).strip(), sqlId=sql_id))
        if stype == "SELECT":
            if re.search(r"\bSELECT\s+DISTINCT\b", upper):
                result.add(fact("sqlDistinct", S("SELECT DISTINCT"), sqlId=sql_id))
            gm = re.search(r"\bGROUP\s+BY\b(.*?)(\bHAVING\b|\bORDER\s+BY\b|$)", sk, re.I | re.S)
            if gm:
                cols = [c.strip() for c in nocomment[gm.start(1):gm.end(1)].split(",") if c.strip()]
                result.add(fact("sqlGroupBy", S(gm.group(0)[:100], gm.start()), columns=cols[:8], sqlId=sql_id))
            om = None
            for om_ in re.finditer(r"\bORDER\s+BY\b", upper):
                if depth[om_.start()] == top:
                    om = om_
            if om:
                seg = nocomment[om.end():]
                seg = re.split(r"\)|\bFETCH\b|\bLIMIT\b|\bOFFSET\b", seg, flags=re.I)[0]
                cols = [re.sub(r"\s+", " ", c).strip() for c in seg.split(",") if c.strip()]
                result.add(fact("sqlOrderBy", S("ORDER BY " + ", ".join(cols)[:100], om.start()), columns=cols[:6], sqlId=sql_id))
            if re.search(r"\bROWNUM\b|\bROW_NUMBER\s*\(|\bLIMIT\b|\bFETCH\s+(FIRST|NEXT)\b|\bOFFSET\b", upper):
                result.add(fact("sqlPaging", S("페이징 처리"), sqlId=sql_id))

        # WHERE 조건
        if where_text.strip():
            atoms = self._split_conditions(where_text)
            pending_range = {}
            for atom in atoms:
                idx = sql.find(atom.strip()[:30]) if atom.strip() else None
                self._condition(atom, stype, sql_id, optional, S, idx if idx and idx >= 0 else None, result, pending_range)
            # 같은 컬럼의 >= / <= 쌍 → 기간
            for col, info in pending_range.items():
                if "lo" in info and "hi" in info and guess_field_type(labelize(col), col) == "date":
                    lo, hi = info["lo"], info["hi"]
                    result.add(fact("dateRange", info["src"], name=labelize(col) + " 기간", start=labelize(lo),
                                    end=labelize(hi), inclusive=info.get("inclusive", True), column=col, sqlId=sql_id))
        return stype

    @staticmethod
    def _split_conditions(where):
        _, sk = mask_sql(where)
        depth = depth_map(sk)
        atoms, start, between = [], 0, False
        for m in re.finditer(r"\b(AND|OR)\b", sk, re.I):
            if depth[m.start()] != 0:
                continue
            piece = sk[start:m.start()]
            if re.search(r"\bBETWEEN\b", piece, re.I) and not between:
                between = True
                continue
            atoms.append(where[start:m.start()])
            start = m.end()
            between = False
        atoms.append(where[start:])
        out = []
        for a in atoms:
            a = a.strip()
            if a.startswith("(") and a.endswith(")"):
                inner = a[1:-1]
                if re.search(r"\b(AND|OR)\b", inner, re.I) and not re.search(r"\bSELECT\b", inner, re.I):
                    out.extend(SqlAnalyzer._split_conditions(inner))
                    continue
            if a:
                out.append(a)
        return out

    def _condition(self, atom, stype, sql_id, optional, S, idx, result, pending_range):
        a = re.sub(r"\s+", " ", atom).strip()
        params = params_in(a)
        is_opt = bool(params) and all(p in optional for p in params)

        def add_cond(op, column, **kw):
            col, nvl = strip_fn(column)
            d = dict(op=op, column=col, colLabel=labelize(col), params=params, optional=is_opt,
                     stmtType=stype, sqlId=sql_id, nvl=nvl, literal=None, negate=False, subquery=False)
            d.update(kw)
            result.add(fact("sqlCond", S(a, idx), **d))
            if stype == "SELECT":
                for p in params:
                    result.add(fact("field", S(a, idx), label=labelize(p), ident=p,
                                    fieldType=guess_field_type(labelize(p), p) if op not in ("in",) else "code",
                                    # SQL 바인딩만으로는 화면 필수 여부를 확정할 수 없음 → 동적 조건이면 선택(False), 아니면 미확정(None)
                                    required=False if (is_opt and p in optional) else None,
                                    maxLength=None, minLength=None, origin="sql", sqlOp=op))
            return col

        if re.match(r"^(NOT\s+)?EXISTS\s*\(", a, re.I):
            add_cond("exists", "(서브쿼리)", negate=a.upper().startswith("NOT"), subquery=True)
            return
        m = re.match(r"^(.+?)\s+(NOT\s+)?BETWEEN\s+(.+?)\s+AND\s+(.+)$", a, re.I)
        if m:
            col = add_cond("between", m.group(1), negate=bool(m.group(2)), low=m.group(3), high=m.group(4))
            ps = params
            if len(ps) >= 2 and guess_field_type(labelize(col), col) in ("date",) or (len(ps) >= 2 and re.search(r"(DT|DATE|YMD|DE)$", ps[0], re.I)):
                result.add(fact("dateRange", S(a, idx), name=labelize(col) + " 기간", start=labelize(ps[0]),
                                end=labelize(ps[1]), inclusive=True, column=col, sqlId=sql_id))
            return
        m = re.match(r"^(.+?)\s+(NOT\s+)?IN\s*\((.*)\)$", a, re.I | re.S)
        if m:
            add_cond("in", m.group(1), negate=bool(m.group(2)), subquery=bool(re.search(r"\bSELECT\b", m.group(3), re.I)),
                     literal=None if params else m.group(3))
            return
        m = re.match(r"^(.+?)\s+(NOT\s+)?LIKE\s+(.+)$", a, re.I)
        if m:
            add_cond("like", m.group(1), negate=bool(m.group(2)), literal=None if params else m.group(3))
            return
        m = re.match(r"^(.+?)\s+IS\s+(NOT\s+)?NULL$", a, re.I)
        if m:
            add_cond("isNotNull" if m.group(2) else "isNull", m.group(1))
            return
        m = re.match(r"^(.+?)\s*(<>|!=|>=|<=|=|>|<)\s*(.+)$", a)
        if m:
            lhs, op, rhs = m.group(1), m.group(2), m.group(3).strip()
            rhs_params = params_in(rhs)
            if not rhs_params and not params_in(lhs) and re.match(r"^[A-Za-z_][\w.]*$", rhs) and re.match(r"^[A-Za-z_][\w.]*$", lhs.strip()):
                add_cond("joinEq", lhs, literal=rhs)
                return
            opname = {"=": "eq", "<>": "ne", "!=": "ne", ">=": "ge", "<=": "le", ">": "gt", "<": "lt"}[op]
            col = add_cond(opname, lhs, literal=None if (rhs_params or params_in(lhs)) else rhs)
            if rhs_params and opname in ("ge", "gt", "le", "lt"):
                info = pending_range.setdefault(col, {"src": S(a, idx)})
                if opname in ("ge", "gt"):
                    info["lo"] = rhs_params[0]
                else:
                    info["hi"] = rhs_params[0]
                if opname in ("gt", "lt"):
                    info["inclusive"] = False
            return
        add_cond("expr", a, literal=a)


def _split_top(text, sep):
    out, depth, cur = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def _ordered_text(node, render_child):
    """expat 버퍼링 때문에 node.text 에 자식 사이 텍스트가 모두 합쳐진다.
    순서 보존을 위해 Node 에 저장된 텍스트 조각 정보를 사용한다 (xmltree.Node.pieces)."""
    pieces = getattr(node, "pieces", None)
    if pieces is None:
        return (node.text or "") + " ".join(render_child(c) for c in node.children)
    out = []
    for p in pieces:
        out.append(render_child(p) if not isinstance(p, str) else p)
    return " ".join(out)
