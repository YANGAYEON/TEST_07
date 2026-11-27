"""규칙 기반 테스트 케이스 생성 엔진.

입력 : 분석 결과 목록(AnalysisResult.facts), 옵션(project_name, changed_files)
처리 :
  1) 통합 컨텍스트 구성 — 화면명/주 기능/주 동작, 자료 간 동일 항목(필드·기간) 병합
  2) Fact 종류별 규칙 적용 → CaseBuilder 에 키 단위로 추가 (같은 키 = 같은 테스트, 근거만 합침)
  3) 중요도 자동 보정 (여러 자료에서 도출된 테스트는 상향)
출력 : 테스트 케이스 dict 목록 (ID 미부여 — merge 단계에서 부여)
"""
import re

from ..analyzers.common import canonical, labelize, josa
from .builder import CaseBuilder, steps, bullets, REVIEW_DEV, REVIEW_BIZ

CATEGORIES = ["정상 테스트", "오류 테스트", "경계값 테스트", "필수값 테스트", "조건 분기 테스트",
              "데이터 검증 테스트", "권한 테스트", "중복 처리 테스트", "예외 처리 테스트", "회귀 테스트"]
STATUSES = ["미실행", "성공", "실패", "보류"]
PRIORITIES = ["높음", "중간", "낮음"]

NORMAL, ERROR, BOUNDARY, REQUIRED, BRANCH, DATA, AUTH, DUP, EXC, REGR = CATEGORIES

ACTION_VERB = {"조회": "조회", "저장": "저장", "등록": "등록", "수정": "수정", "삭제": "삭제", "취소": "취소",
               "취하": "취하", "신청": "신청", "승인": "승인", "반려": "반려", "엑셀다운로드": "엑셀 다운로드",
               "다운로드": "다운로드", "업로드": "업로드", "출력": "출력", "처리": "처리", "실행": "실행"}
WRITE_ACTIONS = {"저장", "등록", "수정", "삭제", "취소", "취하", "신청", "승인", "반려", "확정", "처리", "업로드"}


class Ctx:
    pass


def _sample(field, role=None):
    t = field.get("fieldType")
    if role == "start":
        return "2026-01-01"
    if role == "end":
        return "2026-01-31"
    if t == "date":
        return "2026-01-15"
    if t in ("code", "radio", "check"):
        opts = [o for o in field.get("options", []) if o.get("value")]
        if opts:
            return f"{opts[0]['label']}({opts[0]['value']})"
        return "정상 코드값(예: 01)"
    if t == "number":
        return "1000"
    if field.get("allowChar") in ("0-9",) or re.search(r"(번호|No)$", field.get("label", "")):
        return "12345"
    return "테스트"


# ---------------------------------------------------------------------------
def generate(results, project_name="", changed_files=None):
    facts = [f for r in results for f in r.facts]
    b = CaseBuilder()
    ctx = _context(facts, project_name)

    _field_rules(b, ctx)
    _range_rules(b, ctx, facts)
    for f in facts:
        k = f["kind"]
        rule = RULES.get(k)
        if rule:
            rule(b, ctx, f)
    _requirement_links(b, ctx, facts)
    for fname in (changed_files or []):
        b.add(f"regr:{fname}", feature=ctx.feature, category=REGR,
              scenario=f"변경된 파일({fname}) 반영 후 기존 기능 회귀 확인",
              precondition="이전 분석 이후 파일 내용이 변경됨\n기존 테스트 케이스 중 '성공' 건이 존재함",
              procedure=steps("변경 사항을 반영한 버전으로 배포한다.", "기존 '성공' 상태 테스트 케이스를 다시 수행한다.",
                              "결과를 이전 수행 결과와 비교한다."),
              expected="변경과 무관한 기존 기능이 이전과 동일하게 동작한다.",
              sources=[{"file": fname, "type": "변경감지", "line": None, "detail": "파일 해시 변경"}], priority="중간")
    return b.results(), ctx.summary()


# ---------------------------------------------------------------------------
def _context(facts, project_name):
    ctx = Ctx()
    screens = [f for f in facts if f["kind"] == "screen"]
    functions = [f for f in facts if f["kind"] == "function"]
    buttons = [f for f in facts if f["kind"] == "button"]
    stmts = [f for f in facts if f["kind"] == "sqlStatement"]

    ctx.screen = screens[0]["title"] if screens else (functions[0]["name"] if functions else (project_name or "대상"))
    if functions:
        ctx.feature = functions[0]["name"]
        ctx.action = functions[0]["action"]
    else:
        ctx.feature = ctx.screen if screens else (project_name or ctx.screen)
        q = next((x for x in buttons if x["action"] == "조회"), None)
        if q:
            ctx.action = "조회"
        elif buttons:
            ctx.action = buttons[0]["action"]
        elif stmts:
            ctx.action = "조회" if stmts[0]["stmtType"] == "SELECT" else "저장"
        else:
            ctx.action = "조회"
    ctx.object = re.sub(r"\s*(조회|등록|저장|수정|삭제|신청|관리|목록|화면)$", "", ctx.screen) or ctx.screen
    ctx.verb = ACTION_VERB.get(ctx.action, ctx.action)
    btn = next((x for x in buttons if x["action"] == ctx.action), None)
    ctx.button = btn["label"] if btn else ctx.verb
    ctx.has_select = any(s["stmtType"] == "SELECT" for s in stmts) or ctx.action == "조회"
    ctx.grids = [f for f in facts if f["kind"] == "grid"]
    ctx.grid_label = ctx.grids[0]["label"] if ctx.grids else "조회 결과 목록"
    ctx.no_result_msg = None
    for f in facts:
        if f["kind"] == "noResult" and f.get("message"):
            ctx.no_result_msg = f["message"]
    ctx.range_msg = None
    for bt in buttons:
        for m in bt.get("messages", []):
            if re.search(r"(시작|종료|기간)", m):
                ctx.range_msg = m

    # 필드 병합 (요구사항 / XML / SQL 에서 같은 항목을 하나로)
    fields = {}
    rank = {"XML": 3, "요구사항": 2, "SQL": 1}
    for f in facts:
        if f["kind"] != "field":
            continue
        key = canonical(f["label"])
        st = f["src"]["type"]
        cur = fields.get(key)
        if cur is None:
            cur = fields[key] = {"label": f["label"], "canon": key, "fieldType": f.get("fieldType", "text"),
                                 "required": f.get("required"), "maxLength": f.get("maxLength"),
                                 "minLength": f.get("minLength"), "options": list(f.get("options") or []),
                                 "component": f.get("component"), "allowChar": f.get("allowChar", ""),
                                 "defaultValue": f.get("defaultValue"), "chooseOption": f.get("chooseOption"),
                                 "multi": f.get("multi"), "ident": f.get("ident"), "sources": [f["src"]],
                                 "types": {st}, "_rank": rank.get(st, 0), "sqlOp": f.get("sqlOp")}
            continue
        cur["sources"].append(f["src"])
        cur["types"].add(st)
        if rank.get(st, 0) > cur["_rank"]:
            cur["label"], cur["_rank"] = f["label"], rank.get(st, 0)
        if f.get("component"):
            cur["component"] = f["component"]
            cur["fieldType"] = f.get("fieldType", cur["fieldType"])
        elif cur["fieldType"] == "text" and f.get("fieldType") not in (None, "text"):
            cur["fieldType"] = f["fieldType"]
        r = f.get("required")
        if r is True or (r is False and cur["required"] is None):
            cur["required"] = r
        for k in ("maxLength", "minLength"):
            if f.get(k) and not cur[k]:
                cur[k] = f[k]
        if f.get("options") and not cur["options"]:
            cur["options"] = list(f["options"])
        for k in ("allowChar", "defaultValue", "chooseOption", "multi", "sqlOp"):
            if f.get(k) and not cur.get(k):
                cur[k] = f[k]
        if not cur.get("ident") and f.get("ident"):
            cur["ident"] = f["ident"]
    # 동적 SQL 근거 연결
    for f in facts:
        if f["kind"] == "sqlDynamic":
            fd = fields.get(canonical(f["label"]))
            if fd:
                fd["sources"].append(f["src"])
    ctx.fields = fields
    ctx.required = [x for x in fields.values() if x["required"] is True]

    # 기간 병합
    ranges = {}
    for f in facts:
        if f["kind"] != "dateRange":
            continue
        key = (canonical(f["start"]), canonical(f["end"]))
        cur = ranges.get(key)
        if cur is None:
            ranges[key] = {"start": f["start"], "end": f["end"], "sources": [f["src"]],
                           "inclusive": f.get("inclusive"), "column": f.get("column")}
        else:
            cur["sources"].append(f["src"])
            if f.get("inclusive") is not None:
                cur["inclusive"] = f["inclusive"]
            if f.get("column"):
                cur["column"] = f["column"]
            if f["src"]["type"] == "XML":
                cur["start"], cur["end"] = f["start"], f["end"]
    for (ks, ke), r in ranges.items():
        r["startField"] = fields.get(ks, {"label": r["start"], "fieldType": "date"})
        r["endField"] = fields.get(ke, {"label": r["end"], "fieldType": "date"})
        r["startLabel"] = r["startField"]["label"]
        r["endLabel"] = r["endField"]["label"]
    ctx.ranges = list(ranges.values())
    ctx.range_canons = {c for k in ranges for c in k}

    def normal_inputs(exclude=None, override=None):
        pairs = []
        for fd in fields.values():
            if fd["canon"] == exclude:
                continue
            if fd["required"] is True or fd["canon"] in ctx.range_canons:
                role = None
                for r in ctx.ranges:
                    if fd is r["startField"]:
                        role = "start"
                    elif fd is r["endField"]:
                        role = "end"
                pairs.append((fd["label"], _sample(fd, role)))
        if override:
            pairs = [(k, override.get(k, v)) for k, v in pairs]
            for k, v in override.items():
                if k not in dict(pairs):
                    pairs.append((k, v))
        return pairs
    ctx.normal_inputs = normal_inputs
    ctx.pre = f"{ctx.screen} 화면 사용 권한이 있는 사용자로 로그인되어 있음"
    ctx.pre_data = f"{ctx.pre}\n{ctx.verb} 대상 테스트 데이터가 존재함"

    def summary():
        return {"screen": ctx.screen, "feature": ctx.feature, "action": ctx.action,
                "fields": [{"label": f["label"], "type": f["fieldType"], "required": f["required"],
                            "sources": sorted(f["types"])} for f in fields.values()],
                "ranges": [f"{r['startLabel']} ~ {r['endLabel']}" for r in ctx.ranges]}
    ctx.summary = summary
    return ctx


def _go(ctx):
    return f"{ctx.screen} 화면에 접속한다."


def _click(ctx, label=None):
    return f"[{label or ctx.button}] 버튼을 클릭한다."


# ---------------------------------------------------------------------------
# 입력 항목 규칙
# ---------------------------------------------------------------------------
def _field_rules(b, ctx):
    for fd in ctx.fields.values():
        name, c, t, srcs = fd["label"], fd["canon"], fd["fieldType"], fd["sources"]
        comp = fd.get("component")
        only_sql = fd["types"] == {"SQL"}
        lbl_obj = josa(name, "을/를")
        feature = ctx.feature

        # --- 정상 입력
        if t == "code" and fd["options"]:
            opts = ", ".join(f"{o['label']}({o['value']})" for o in fd["options"] if o.get("value"))[:120]
            b.add(f"field:{c}:normal", feature=feature, category=NORMAL,
                  scenario=f"{name} 정상 코드 선택 후 {ctx.verb}", precondition=ctx.pre_data,
                  input_data=bullets(ctx.normal_inputs(override={name: _sample(fd)})) + f"\n- 선택 가능 값: {opts}",
                  procedure=steps(_go(ctx), "필수 조건을 정상 입력한다.", f"{name}에서 각 코드값을 차례로 선택한다.", _click(ctx)),
                  expected=f"선택한 {name}에 해당하는 데이터만 {ctx.verb}된다.", sources=srcs, priority="높음")
        elif t not in ("check", "radio") and c not in ctx.range_canons:
            b.add(f"field:{c}:normal", feature=feature, category=NORMAL,
                  scenario=f"{name}에 올바른 값을 입력하여 {ctx.verb}", precondition=ctx.pre_data,
                  input_data=bullets(ctx.normal_inputs(override={name: _sample(fd)})),
                  procedure=steps(_go(ctx), f"{name}에 정상 값을 입력한다.", _click(ctx)),
                  expected=f"입력한 {name} 조건이 적용되어 정상적으로 {ctx.verb}된다.", sources=srcs,
                  priority="중간")

        # --- 미입력
        if t not in ("check",):
            r = fd["required"]
            if r is True:
                b.add(f"field:{c}:empty", feature=feature, category=REQUIRED,
                      scenario=f"{name} 미입력 후 {ctx.verb}", precondition=ctx.pre,
                      input_data=bullets(ctx.normal_inputs(override={name: "(미입력)"})),
                      procedure=steps(_go(ctx), f"{josa(name, '은/는')} 비워 둔다.",
                                      "나머지 필수 항목은 정상 입력한다.", _click(ctx)),
                      expected=f"'{name}' 필수 입력 안내 메시지가 표시되고 {ctx.verb}가 수행되지 않는다.\n포커스가 {name} 항목으로 이동한다.",
                      sources=srcs, priority="높음")
            elif r is False:
                b.add(f"field:{c}:empty", feature=feature, category=BRANCH,
                      scenario=f"{name} 미입력 시 조건 미적용 {ctx.verb}", precondition=ctx.pre_data,
                      input_data=bullets(ctx.normal_inputs(override={name: "(미입력)"})),
                      procedure=steps(_go(ctx), f"{name} 값을 입력하지 않는다.", _click(ctx)),
                      expected=f"{name} 조건이 적용되지 않고 나머지 조건에 해당하는 전체 데이터가 {ctx.verb}된다 (동적 조건).",
                      sources=srcs, priority="중간")
            else:
                b.add(f"field:{c}:empty", feature=feature, category=REQUIRED,
                      scenario=f"{name} 미입력 후 {ctx.verb}", precondition=ctx.pre,
                      input_data=bullets(ctx.normal_inputs(override={name: "(미입력)"})),
                      procedure=steps(_go(ctx), f"{name} 값을 비워 둔다.", _click(ctx)),
                      expected=f"[필수 여부 확인] 필수 항목이면 안내 메시지 표시 후 처리 중단, 선택 항목이면 {name} 조건 없이 {ctx.verb}된다.",
                      sources=srcs, priority="낮음", review=f"{REVIEW_BIZ} — {name} 필수 여부 미확인")

        if t == "date":
            b.add(f"field:{c}:format", feature=feature, category=ERROR,
                  scenario=f"{name}에 잘못된 날짜 형식 입력", precondition=ctx.pre,
                  input_data=bullets([(name, "2026-13-45 / 20261 / abcd")]),
                  procedure=steps(_go(ctx), f"{name}에 형식이 잘못된 값을 입력한다.", _click(ctx)),
                  expected="입력이 차단되거나 날짜 형식 오류 안내 메시지가 표시되고 처리되지 않는다.",
                  sources=srcs, priority="중간")
            b.add(f"field:{c}:invalid_date", feature=feature, category=BOUNDARY,
                  scenario=f"{name}에 존재하지 않는 날짜 입력 (윤년/말일 경계)", precondition=ctx.pre,
                  input_data=bullets([(name, "2026-02-29 (평년), 2026-04-31")]),
                  procedure=steps(_go(ctx), f"{name}에 존재하지 않는 날짜를 입력한다.", _click(ctx)),
                  expected="유효하지 않은 날짜로 처리되어 오류 안내 또는 입력 차단된다.",
                  sources=srcs, priority="낮음")
        elif t == "code":
            if not only_sql or fd.get("sqlOp") in ("eq", "in"):
                b.add(f"field:{c}:invalid_code", feature=feature, category=ERROR,
                      scenario=f"{name}에 존재하지 않는 코드값 전송", precondition=ctx.pre,
                      input_data=bullets([(name, "99 (미정의 코드)")]),
                      procedure=steps(_go(ctx), f"개발자 도구 또는 요청 파라미터 변경으로 {name} 값을 '99'로 전송한다.", _click(ctx)),
                      expected="오류 없이 조회 결과 없음으로 처리되거나, 유효하지 않은 코드 안내 메시지가 표시된다.",
                      sources=srcs, priority="낮음", review=f"{REVIEW_BIZ} — 미정의 코드 처리 방식")
            if comp == "selectbox":
                dv = fd.get("defaultValue")
                b.add(f"field:{c}:default", feature=feature, category=NORMAL,
                      scenario=f"{name} 초기 기본값 확인", precondition=ctx.pre,
                      procedure=steps(_go(ctx), f"{name}의 초기 선택값을 확인한다."),
                      expected=(f"화면 최초 진입 시 {name}에 '{dv}' 항목이 선택되어 있다." if dv
                                else f"{name} 기본값이 설계서와 일치한다."),
                      sources=srcs, priority="낮음", review=None if dv else f"{REVIEW_BIZ} — 기본값 미정의")
        elif t == "check":
            multi = fd.get("multi") or len(fd["options"]) > 1
            b.add(f"field:{c}:checked", feature=feature, category=NORMAL, scenario=f"{name} 선택(체크) 후 {ctx.verb}",
                  precondition=ctx.pre_data, procedure=steps(_go(ctx), f"{name} 항목을 체크한다.", _click(ctx)),
                  expected=f"{name} 선택 조건이 반영되어 처리된다.", sources=srcs, priority="중간")
            b.add(f"field:{c}:unchecked", feature=feature, category=BRANCH, scenario=f"{name} 미선택 후 {ctx.verb}",
                  precondition=ctx.pre_data, procedure=steps(_go(ctx), f"{name} 항목을 체크하지 않는다.", _click(ctx)),
                  expected=f"{name} 미선택 상태의 처리 규칙대로 동작한다.", sources=srcs, priority="낮음",
                  review=f"{REVIEW_BIZ} — 미선택 시 처리 규칙")
            if multi:
                b.add(f"field:{c}:multi", feature=feature, category=NORMAL, scenario=f"{name} 복수 선택",
                      precondition=ctx.pre_data, input_data=bullets([(name, ", ".join(o["label"] for o in fd["options"][:4]))]),
                      procedure=steps(_go(ctx), f"{name}에서 2개 이상 항목을 선택한다.", _click(ctx)),
                      expected="선택한 모든 항목이 조건으로 반영된다.", sources=srcs, priority="중간")
                b.add(f"field:{c}:all", feature=feature, category=NORMAL, scenario=f"{name} 전체 선택 및 해제",
                      precondition=ctx.pre, procedure=steps(_go(ctx), "전체 선택 후 다시 전체 해제한다."),
                      expected="모든 항목이 일괄 선택/해제된다.", sources=srcs, priority="낮음")
        elif t == "radio":
            for o in fd["options"][:6]:
                b.add(f"field:{c}:radio:{o.get('value')}", feature=feature, category=NORMAL,
                      scenario=f"{name} '{o['label']}' 선택 후 {ctx.verb}", precondition=ctx.pre_data,
                      input_data=bullets([(name, f"{o['label']}({o.get('value')})")]),
                      procedure=steps(_go(ctx), f"{name}에서 '{o['label']}' 항목을 선택한다.", _click(ctx)),
                      expected=f"'{o['label']}' 선택에 해당하는 처리가 수행된다.", sources=srcs, priority="중간")
            b.add(f"field:{c}:default", feature=feature, category=NORMAL, scenario=f"{name} 초기 기본값 확인",
                  precondition=ctx.pre, procedure=steps(_go(ctx), f"{name}의 초기 선택값을 확인한다."),
                  expected=f"{name} 기본값이 설계서와 일치한다.", sources=srcs, priority="낮음",
                  review=None if fd.get("defaultValue") else f"{REVIEW_BIZ} — 기본값 미정의")
        elif t == "number":
            b.add(f"field:{c}:format", feature=feature, category=ERROR, scenario=f"{name}에 숫자가 아닌 값 입력",
                  precondition=ctx.pre, input_data=bullets([(name, "abc / 1,0a / -")]),
                  procedure=steps(_go(ctx), f"{name}에 문자를 입력한다.", _click(ctx)),
                  expected="문자 입력이 차단되거나 숫자 형식 오류 안내 메시지가 표시된다.", sources=srcs, priority="중간")
        else:  # text
            if not only_sql:
                b.add(f"field:{c}:blank", feature=feature, category=ERROR, scenario=f"{name}에 공백만 입력",
                      precondition=ctx.pre, input_data=bullets([(name, "'   ' (공백 3자)")]),
                      procedure=steps(_go(ctx), f"{name}에 공백만 입력한다.", _click(ctx)),
                      expected=("미입력과 동일하게 필수 입력 안내 메시지가 표시된다." if fd["required"] is True
                                else "공백이 제거(trim)되어 미입력과 동일하게 처리된다."),
                      sources=srcs, priority="중간" if fd["required"] else "낮음",
                      review=None if fd["required"] is True else f"{REVIEW_BIZ} — 공백 처리 규칙")
            if fd.get("allowChar"):
                b.add(f"field:{c}:format", feature=feature, category=ERROR,
                      scenario=f"{name}에 허용되지 않은 문자 입력 (허용: {fd['allowChar']})", precondition=ctx.pre,
                      input_data=bullets([(name, "가나다 / abc / !@#")]),
                      procedure=steps(_go(ctx), f"{name}에 허용 문자 외의 값을 입력한다."),
                      expected=f"허용 문자({fd['allowChar']}) 외 입력은 차단된다.", sources=srcs, priority="중간")
            if fd.get("maxLength"):
                n = fd["maxLength"]
                b.add(f"field:{c}:max", feature=feature, category=BOUNDARY, scenario=f"{name} 최대 길이({n}자) 입력",
                      precondition=ctx.pre, input_data=bullets([(name, f"{n}자 문자열")]),
                      procedure=steps(_go(ctx), f"{name}에 정확히 {n}자를 입력한다.", _click(ctx)),
                      expected=f"{n}자까지 정상 입력·저장되며 잘림이 없다.", sources=srcs, priority="중간")
                b.add(f"field:{c}:over", feature=feature, category=BOUNDARY, scenario=f"{name} 최대 길이 초과({n + 1}자) 입력",
                      precondition=ctx.pre, input_data=bullets([(name, f"{n + 1}자 문자열 (한글 포함 시 Byte 기준 확인)")]),
                      procedure=steps(_go(ctx), f"{name}에 {n + 1}자를 입력(또는 붙여넣기)한다.", _click(ctx)),
                      expected=f"{n}자 초과 입력이 차단되거나 길이 초과 안내 메시지가 표시된다.", sources=srcs, priority="높음")
            elif not only_sql and comp in (None, "input", "textarea"):
                b.add(f"field:{c}:over", feature=feature, category=BOUNDARY, scenario=f"{name} 최대 길이 초과 입력",
                      precondition=ctx.pre, input_data=bullets([(name, "DB 컬럼 길이 + 1 자")]),
                      procedure=steps(_go(ctx), f"{name}에 매우 긴 문자열을 입력한다.", _click(ctx)),
                      expected="길이 초과가 차단되거나 안내 메시지가 표시되며 DB 오류가 발생하지 않는다.",
                      sources=srcs, priority="낮음", review=f"{REVIEW_BIZ} — 최대 길이 미정의")
            if fd.get("minLength"):
                n = fd["minLength"]
                b.add(f"field:{c}:min", feature=feature, category=BOUNDARY, scenario=f"{name} 최소 길이 미만({n - 1}자) 입력",
                      precondition=ctx.pre, input_data=bullets([(name, f"{max(n - 1, 0)}자 문자열")]),
                      procedure=steps(_go(ctx), f"{name}에 {n - 1}자를 입력한다.", _click(ctx)),
                      expected=f"최소 {n}자 이상 입력 안내 메시지가 표시된다.", sources=srcs, priority="중간")


def _range_rules(b, ctx, facts):
    for r in ctx.ranges:
        s, e, srcs = r["startLabel"], r["endLabel"], r["sources"]
        key = f"{canonical(s)}~{canonical(e)}"
        b.add(f"range:{key}:normal", feature=ctx.feature, category=NORMAL,
              scenario=f"정상적인 기간({s}~{e})을 입력하여 {ctx.verb}", precondition=ctx.pre_data,
              input_data=bullets(ctx.normal_inputs()),
              procedure=steps(_go(ctx), f"{josa(s, '을/를')} 입력한다.", f"{josa(e, '을/를')} 입력한다.", _click(ctx)),
              expected=f"입력한 기간에 해당하는 데이터가 {ctx.verb}되어 {ctx.grid_label}에 표시된다.",
              sources=srcs, priority="높음")
        b.add(f"range:{key}:same", feature=ctx.feature, category=BOUNDARY,
              scenario=f"{josa(s, '과/와')} {josa(e, '이/가')} 동일한 날짜인 경우",
              precondition=ctx.pre_data,
              input_data=bullets(ctx.normal_inputs(override={s: "2026-01-15", e: "2026-01-15"})),
              procedure=steps(_go(ctx), f"{josa(s, '과/와')} {e}에 같은 날짜를 입력한다.", _click(ctx)),
              expected="해당 일자 하루의 데이터가 정상 조회된다 (경계일 포함).", sources=srcs, priority="중간")
        b.add(f"range:{key}:reverse", feature=ctx.feature, category=ERROR,
              scenario=f"{josa(s, '이/가')} {e}보다 늦은 경우", precondition=ctx.pre,
              input_data=bullets(ctx.normal_inputs(override={s: "2026-01-31", e: "2026-01-01"})),
              procedure=steps(_go(ctx), f"{josa(s, '을/를')} {e}보다 늦은 날짜로 입력한다.", _click(ctx)),
              expected=(f"'{ctx.range_msg}' 메시지가 표시되고 {ctx.verb}되지 않는다." if ctx.range_msg
                        else f"기간 오류 안내 메시지가 표시되고 {ctx.verb}되지 않는다."),
              sources=srcs, priority="높음")
        if r.get("inclusive") is not None and r.get("column"):
            col = r["column"]
            b.add(f"range:{key}:inclusive", feature=ctx.feature, category=DATA,
                  scenario=f"기간 경계일({s}, {e}) 당일 데이터 포함 여부 확인",
                  precondition=f"{ctx.pre}\n{col} 값이 시작일 당일, 종료일 당일, 기간 밖(전날/다음날)인 데이터가 각각 존재함",
                  input_data=bullets(ctx.normal_inputs()),
                  procedure=steps(_go(ctx), "기간을 입력하고 조회한다.", "경계일 데이터의 포함 여부를 확인한다."),
                  expected=("시작일·종료일 당일 데이터는 포함되고, 기간 밖 데이터는 제외된다."
                            if r["inclusive"] else "SQL 조건이 경계를 제외(>, <)하므로 당일 데이터 포함 여부를 확인한다."),
                  note=f"{col} 컬럼이 시간 포함 DATE 형이면 종료일 당일 데이터가 누락될 수 있음",
                  sources=srcs, priority="높음")
    for f in facts:
        if f["kind"] == "periodLimit":
            v, u = f["value"], f["unit"]
            b.add("range:limit:max", feature=ctx.feature, category=BOUNDARY,
                  scenario=f"조회 기간을 최대 허용 기간({v}{u})으로 입력", precondition=ctx.pre_data,
                  input_data=bullets([("기간", f"2026-01-01 ~ {v}{u} 후 같은 날 하루 전")]),
                  procedure=steps(_go(ctx), f"정확히 {v}{u} 기간을 입력한다.", _click(ctx)),
                  expected="정상적으로 조회된다.", sources=[f["src"]], priority="중간")
            b.add("range:limit:over", feature=ctx.feature, category=BOUNDARY,
                  scenario=f"조회 기간이 최대 허용 기간({v}{u}) 초과", precondition=ctx.pre,
                  input_data=bullets([("기간", f"{v}{u} + 1일")]),
                  procedure=steps(_go(ctx), f"{v}{u}에서 하루를 초과하는 기간을 입력한다.", _click(ctx)),
                  expected=f"기간 초과 안내 메시지가 표시되고 {ctx.verb}되지 않는다.", sources=[f["src"]], priority="높음")


# ---------------------------------------------------------------------------
# 요구사항 규칙
# ---------------------------------------------------------------------------
def _r_function(b, ctx, f):
    act, obj, name = f["action"], f["object"], f["name"]
    if act == "다운로드" and "엑셀" in obj:
        act, obj = "엑셀다운로드", ctx.object
        name = f"{ctx.object} 엑셀다운로드"
    verb = ACTION_VERB.get(act, act)
    if act == "조회":
        b.add("action:조회:normal", feature=name, category=NORMAL, scenario=f"정상 조건으로 {name}",
              precondition=ctx.pre_data, input_data=bullets(ctx.normal_inputs()),
              procedure=steps(_go(ctx), "조회 조건을 정상 입력한다.", _click(ctx, "조회" if ctx.action == "조회" else None)),
              expected=f"조건에 맞는 {josa(obj, '이/가')} 조회되어 {ctx.grid_label}에 표시된다.", sources=[f["src"]], priority="높음")
    else:
        b.add(f"action:{act}:normal", feature=name, category=NORMAL, scenario=f"정상적으로 {name}",
              precondition=ctx.pre_data, input_data=bullets(ctx.normal_inputs()),
              procedure=steps(_go(ctx), f"{verb} 대상을 선택하거나 값을 입력한다.", _click(ctx, verb)),
              expected=f"{obj} {josa(verb, '이/가')} 정상 처리되고 완료 메시지가 표시된다.\nDB에 {verb} 결과가 반영된다.",
              sources=[f["src"]], priority="높음")
        if act in WRITE_ACTIONS:
            b.add(f"action:{act}:dbcheck", feature=name, category=DATA, scenario=f"{name} 후 데이터 반영 검증",
                  precondition=ctx.pre_data,
                  procedure=steps(f"{josa(name, '을/를')} 수행한다.", "DB 또는 재조회 화면에서 결과를 확인한다."),
                  expected=f"{verb} 내용이 정확히 저장되고 등록자/수정일시 등 이력 컬럼이 갱신된다.",
                  sources=[f["src"]], priority="중간")


def _r_no_result(b, ctx, f):
    msg = f.get("message")
    b.add("result:none", feature=ctx.feature, category=DATA, scenario="조회 결과가 없는 경우",
          precondition=f"{ctx.pre}\n조건에 해당하는 데이터가 없음",
          input_data=bullets(ctx.normal_inputs(override={})) or "- 데이터가 없는 조건",
          procedure=steps(_go(ctx), "데이터가 없는 조건을 입력한다.", _click(ctx)),
          expected=(f"'{msg}' 메시지가 표시되고 {josa(ctx.grid_label, '은/는')} 빈 상태로 표시된다." if msg and msg != "안내 메시지"
                    else f"조회 결과 없음 안내 메시지가 표시되고 {josa(ctx.grid_label, '은/는')} 빈 상태로 표시된다."),
          sources=[f["src"]], priority="높음")


def _r_result_display(b, ctx, f):
    b.add("result:exists", feature=ctx.feature, category=NORMAL, scenario="조회 결과가 존재하는 경우 목록 표시",
          precondition=ctx.pre_data, input_data=bullets(ctx.normal_inputs()),
          procedure=steps(_go(ctx), "조건을 입력하고 조회한다.", "목록의 건수와 각 컬럼 값을 확인한다."),
          expected=f"조회 결과가 {ctx.grid_label}에 표시되며 건수와 컬럼 값이 DB 데이터와 일치한다.",
          sources=[f["src"]], priority="높음")


def _r_numeric(b, ctx, f):
    lab, op, v = f["label"], f["op"], int(f["value"])
    ok, ng = {"이상": (v, v - 1), "이하": (v, v + 1), "초과": (v + 1, v), "미만": (v - 1, v)}[op]
    b.add(f"num:{canonical(lab)}:{op}:ok", feature=ctx.feature, category=BOUNDARY,
          scenario=f"{lab} 경계값 {ok:,} 입력 ({v:,} {op} 조건 충족)", precondition=ctx.pre,
          input_data=bullets([(lab, f"{ok:,}")]), procedure=steps(_go(ctx), f"{lab}에 {ok:,}을 입력한다.", _click(ctx)),
          expected="정상 처리된다.", sources=[f["src"]], priority="높음")
    b.add(f"num:{canonical(lab)}:{op}:ng", feature=ctx.feature, category=BOUNDARY,
          scenario=f"{lab} 경계값 {ng:,} 입력 ({v:,} {op} 조건 위반)", precondition=ctx.pre,
          input_data=bullets([(lab, f"{ng:,}")]), procedure=steps(_go(ctx), f"{lab}에 {ng:,}을 입력한다.", _click(ctx)),
          expected=f"'{josa(lab, '은/는')} {v:,} {op}' 안내 메시지가 표시되고 처리되지 않는다.", sources=[f["src"]], priority="높음")


def _action_in_text(text):
    for a in ("삭제", "수정", "등록", "저장", "승인", "반려", "취소", "취하", "신청", "다운로드", "조회"):
        if a in text:
            return "엑셀다운로드" if a == "다운로드" else a
    return "general"


def _feature_for(ctx, act):
    if act in ("general", ctx.action):
        return ctx.feature
    return f"{ctx.object} {act}"


def _r_permission(b, ctx, f):
    act = _action_in_text(f["text"])
    verb = ACTION_VERB.get(act, "해당 기능")
    b.add(f"perm:{act}", feature=_feature_for(ctx, act), category=AUTH, scenario=f"권한이 없는 사용자로 {verb} 시도",
          precondition="권한이 없는 사용자 계정으로 로그인",
          procedure=steps(_go(ctx), f"{verb} 기능을 실행한다."),
          expected=f"요구사항: {f['text']}\n→ 버튼이 비활성/미표시되거나 권한 없음 메시지가 표시되고 처리되지 않는다.",
          sources=[f["src"]], priority="높음")
    b.add(f"perm:{act}:ok", feature=_feature_for(ctx, act), category=AUTH, scenario=f"권한이 있는 사용자로 {verb} 수행",
          precondition="권한이 있는 사용자 계정으로 로그인", procedure=steps(_go(ctx), f"{verb} 기능을 실행한다."),
          expected="정상 처리된다.", sources=[f["src"]], priority="중간")


def _r_duplicate(b, ctx, f):
    act = _action_in_text(f["text"])
    verb = ACTION_VERB.get(act, "처리")
    b.add(f"dup:{act}", feature=_feature_for(ctx, act), category=DUP, scenario=f"이미 {verb}된 데이터로 다시 {verb}",
          precondition=f"{ctx.pre}\n동일한 데이터가 이미 {verb}되어 있음",
          procedure=steps(_go(ctx), f"기존과 동일한 데이터로 {josa(verb, '을/를')} 시도한다."),
          expected=f"요구사항: {f['text']}\n→ 중복 안내 메시지가 표시되고 데이터가 중복 생성되지 않는다.",
          sources=[f["src"]], priority="높음")


def _r_condition(b, ctx, f):
    text = f["text"]
    if f.get("_linked"):
        return
    b.add(f"req:cond:{text[:40]}", feature=ctx.feature, category=BRANCH, scenario=f"[조건] {text}",
          precondition=ctx.pre_data, procedure=steps(_go(ctx), "요구사항의 조건을 만족하는 상황을 만든다.", "동작을 확인한다."),
          expected=f"요구사항대로 동작한다: {text}", sources=[f["src"]], priority="중간",
          review=f"{REVIEW_DEV} — 조건/기대 결과 구체화")


def _r_message(b, ctx, f):
    b.add(f"req:msg:{f['text'][:40]}", feature=ctx.feature, category=NORMAL, scenario=f"[메시지] {f['text']}",
          precondition=ctx.pre, procedure=steps(_go(ctx), "메시지가 표시되는 상황을 만든다."),
          expected=f"요구사항에 정의된 메시지가 표시된다: {f['text']}", sources=[f["src"]], priority="낮음",
          review=f"{REVIEW_DEV} — 메시지 표시 조건")


def _r_unknown(b, ctx, f):
    if f.get("_linked"):
        return
    b.add(f"req:unknown:{f['text'][:40]}", feature=ctx.feature, category=NORMAL, scenario=f"[해석 불가] {f['text']}",
          precondition="", procedure="",
          expected="자동 해석하지 못한 요구사항입니다. 내용을 확인하여 테스트 시나리오를 작성하세요.",
          sources=[f["src"]], priority="낮음", review=f"{REVIEW_DEV} — 규칙으로 해석 불가")


# ---------------------------------------------------------------------------
# XML 규칙
# ---------------------------------------------------------------------------
def _btn_feature(ctx, f):
    if f["action"] == ctx.action:
        return ctx.feature
    return f"{ctx.object} {f['label']}"


def _r_button(b, ctx, f):
    act, lab = f["action"], f["label"]
    feature = _btn_feature(ctx, f)
    s = [f["src"]]
    note = ("호출: " + ", ".join(f["actions"])) if f.get("actions") else ""
    expected = {
        "조회": f"조회 조건에 맞는 결과가 {ctx.grid_label}에 표시된다.",
        "저장": "저장 완료 메시지가 표시되고 입력 내용이 DB에 반영된다.",
        "수정": "수정 완료 메시지가 표시되고 변경 내용이 DB에 반영된다.",
        "삭제": "삭제 확인 후 대상이 삭제되고 목록이 재조회된다.",
        "엑셀다운로드": "Excel 파일이 다운로드되며 내용이 화면 조회 결과와 일치한다.",
        "업로드": "파일이 업로드되고 처리 결과가 표시된다.",
        "초기화": "입력한 조건이 모두 초기값으로 돌아간다.",
        "행추가": "목록에 신규 행이 추가된다.",
        "출력": "출력(인쇄) 미리보기가 표시된다.",
        "승인": "승인 처리되고 상태가 변경된다.",
        "반려": "반려 처리되고 상태가 변경된다.",
        "닫기": "팝업/화면이 닫힌다.",
    }.get(act)
    pre = ctx.pre_data if act in ("조회", "엑셀다운로드", "삭제", "수정", "승인", "반려") else ctx.pre
    proc = [_go(ctx)]
    if act in ("조회", "엑셀다운로드"):
        proc.append("조회 조건을 정상 입력한다.")
    if act in ("삭제", "수정", "승인", "반려") and ctx.grids:
        proc.append(f"{ctx.grid_label}에서 대상 행을 선택한다.")
    proc.append(_click(ctx, lab))
    if f.get("confirm"):
        proc.append("확인 창에서 [확인]을 선택한다.")
    key = f"action:{act}:normal" if act in ("조회", "저장", "수정", "삭제", "승인", "반려", "등록", "엑셀다운로드") else f"btn:{f['ident'] or lab}:normal"
    b.add(key, feature=feature, category=NORMAL, scenario=f"[{lab}] 버튼 정상 클릭",
          precondition=pre, input_data=bullets(ctx.normal_inputs()) if act == "조회" else "",
          procedure=steps(*proc), expected=expected or f"[{lab}] 버튼에 정의된 동작이 수행된다.",
          sources=s, note=note, priority="높음" if act in ("조회", "저장", "삭제", "수정") else "중간",
          review=None if expected else f"{REVIEW_BIZ} — 버튼 동작 정의 필요")

    if act in ("조회", "저장", "수정", "엑셀다운로드") and ctx.required:
        names = ", ".join(x["label"] for x in ctx.required)
        b.add(f"btn:{f['ident'] or lab}:required", feature=feature, category=REQUIRED,
              scenario=f"필수값({names}) 누락 상태에서 [{lab}] 클릭", precondition=ctx.pre,
              input_data=bullets([(x["label"], "(미입력)") for x in ctx.required]),
              procedure=steps(_go(ctx), "필수 항목을 모두 비워 둔다.", _click(ctx, lab)),
              expected="첫 번째 누락 항목에 대한 필수 입력 안내 메시지가 표시되고 처리(서버 요청)가 수행되지 않는다.",
              sources=s, priority="높음")
    if act not in ("초기화", "닫기", "행추가"):
        write = act in WRITE_ACTIONS or act in ("저장", "삭제")
        b.add(f"btn:{f['ident'] or lab}:double", feature=feature, category=DUP, scenario=f"[{lab}] 버튼 빠르게 중복 클릭",
              precondition=pre, procedure=steps(_go(ctx), f"[{lab}] 버튼을 빠르게 2~3회 연속 클릭한다."),
              expected=("요청이 1회만 처리되어 데이터가 중복 생성/삭제되지 않는다." if write
                        else "중복 요청이 발생하지 않거나 결과가 한 번만 정상 표시된다."),
              sources=s, priority="높음" if write else "낮음")
        b.add(f"perm:{act if act in WRITE_ACTIONS or act in ('삭제', '저장', '조회', '엑셀다운로드') else f['ident']}",
              feature=feature, category=AUTH, scenario=f"권한이 없는 사용자로 [{lab}] 클릭",
              precondition="해당 기능 권한이 없는 사용자 계정으로 로그인",
              procedure=steps(_go(ctx), _click(ctx, lab)),
              expected="버튼이 비활성/미표시되거나 권한 없음 메시지가 표시되고 서버 처리가 수행되지 않는다.",
              sources=s, priority="중간" if write else "낮음", review=f"{REVIEW_BIZ} — 권한 정책")
    if f.get("confirm"):
        b.add(f"btn:{f['ident'] or lab}:confirm_cancel", feature=feature, category=BRANCH,
              scenario=f"[{lab}] 확인 창에서 [취소] 선택", precondition=pre,
              procedure=steps(_go(ctx), _click(ctx, lab), "확인 창에서 [취소]를 선택한다."),
              expected="처리가 수행되지 않고 화면 상태가 유지된다.", sources=s,
              note=next((f"확인 메시지: {m}" for m in f.get("messages", []) if "?" in m or "까" in m), ""), priority="중간")


def _r_grid(b, ctx, f):
    g, s = f["label"], [f["src"]]
    cols = ", ".join(f.get("columns", [])[:10])
    b.add("result:exists", feature=ctx.feature, category=NORMAL, scenario="조회 결과가 존재하는 경우 목록 표시",
          precondition=ctx.pre_data, input_data=bullets(ctx.normal_inputs()),
          procedure=steps(_go(ctx), "조건을 입력하고 조회한다.", f"{g}의 건수와 컬럼 값을 확인한다."),
          expected=f"조회 결과가 {g}에 표시되며 건수와 컬럼({cols}) 값이 DB 데이터와 일치한다.", sources=s, priority="높음")
    b.add("result:none", feature=ctx.feature, category=DATA, scenario="조회 결과가 없는 경우",
          precondition=f"{ctx.pre}\n조건에 해당하는 데이터가 없음",
          procedure=steps(_go(ctx), "데이터가 없는 조건을 입력하고 조회한다."),
          expected=f"조회 결과 없음 안내가 표시되고 {josa(g, '은/는')} 빈 상태가 된다.", sources=s, priority="높음",
          review=None if ctx.no_result_msg else f"{REVIEW_BIZ} — 결과 없음 메시지 문구")
    b.add("grid:single", feature=ctx.feature, category=BOUNDARY, scenario="조회 결과가 1건인 경우",
          precondition=f"{ctx.pre}\n조건에 해당하는 데이터가 정확히 1건", procedure=steps(_go(ctx), "1건만 해당하는 조건으로 조회한다."),
          expected=f"{g}에 1건이 표시되고 건수 표시가 1건이다.", sources=s, priority="중간")
    b.add("grid:multi", feature=ctx.feature, category=BOUNDARY, scenario="조회 결과가 다건(페이지 크기 초과)인 경우",
          precondition=f"{ctx.pre}\n해당 데이터가 페이지 크기보다 많음", procedure=steps(_go(ctx), "다건이 조회되는 조건으로 조회한다.", "스크롤/페이지 이동을 확인한다."),
          expected="전체 건수가 정확히 표시되고 스크롤 또는 페이징으로 모든 데이터를 확인할 수 있다.", sources=s, priority="중간")
    b.add("grid:dup", feature=ctx.feature, category=DATA, scenario="목록 데이터 중복 표시 여부",
          precondition=ctx.pre_data, procedure=steps(_go(ctx), "조회 후 동일 키(번호) 행이 중복되는지 확인한다."),
          expected="동일 데이터가 중복 표시되지 않는다 (JOIN 으로 인한 행 증가 없음).", sources=s, priority="중간")
    for rb in f.get("rowButtons", []):
        b.add(f"grid:rowbtn:{canonical(rb)}", feature=ctx.feature, category=NORMAL,
              scenario=f"{g}의 행별 [{rb}] 클릭 동작", precondition=ctx.pre_data,
              procedure=steps(_go(ctx), "조회한다.", f"임의 행의 [{rb}] 항목을 클릭한다."),
              expected="클릭한 행의 데이터 기준으로 정의된 동작(상세 이동/팝업 등)이 수행된다.", sources=s, priority="중간",
              review=f"{REVIEW_BIZ} — 행 클릭 동작 정의")
    if f.get("hasCheck"):
        b.add("grid:checkall", feature=ctx.feature, category=NORMAL, scenario=f"{g} 전체 선택 및 해제",
              precondition=ctx.pre_data, procedure=steps(_go(ctx), "조회한다.", "헤더 체크박스로 전체 선택 후 다시 해제한다."),
              expected="모든 행이 일괄 선택/해제된다.", sources=s, priority="낮음")


def _r_grid_select(b, ctx, buttons):
    """행 선택이 필요한 버튼(삭제/수정 등) × 체크 그리드 → 행 미선택 테스트."""
    if not any(g.get("hasCheck") for g in ctx.grids):
        return
    for bt in buttons:
        if bt["action"] in ("삭제", "수정", "승인", "반려", "저장"):
            msg = next((m for m in bt.get("messages", []) if "선택" in m), None)
            b.add(f"grid:noselect:{bt['ident']}", feature=_btn_feature(ctx, bt), category=ERROR,
                  scenario=f"행을 선택하지 않고 [{bt['label']}] 클릭", precondition=ctx.pre_data,
                  procedure=steps(_go(ctx), "조회한다.", "행을 선택하지 않는다.", _click(ctx, bt["label"])),
                  expected=(f"'{msg}' 메시지가 표시되고 처리되지 않는다." if msg else "행 선택 안내 메시지가 표시되고 처리되지 않는다."),
                  sources=[bt["src"]], priority="높음")


def _r_generator(b, ctx, f):
    for n, desc in (("0", "생성 대상이 0건"), ("1", "생성 대상이 1건"), ("n", "생성 대상이 다건")):
        b.add(f"gen:{f['ident']}:{n}", feature=ctx.feature, category=BOUNDARY,
              scenario=f"동적 영역({f['ident']}) — {desc}", precondition=ctx.pre,
              procedure=steps(_go(ctx), f"{desc}이 되도록 데이터를 준비하고 화면을 표시한다."),
              expected="건수에 맞게 영역이 생성되고 레이아웃이 깨지지 않는다.", sources=[f["src"]], priority="낮음")


# ---------------------------------------------------------------------------
# SQL 규칙
# ---------------------------------------------------------------------------
def _sql_feature(ctx, f):
    return ctx.feature if ctx.feature else f.get("sqlId", "SQL")


def _r_sql_stmt(b, ctx, f):
    st, tables, sid = f["stmtType"], f.get("tables", []), f.get("sqlId")
    t0 = tables[0] if tables else "대상 테이블"
    s = [f["src"]]
    feature = ctx.feature if st == "SELECT" else f"{sid} ({st} {t0})"
    if st == "SELECT":
        b.add("result:exists", feature=ctx.feature, category=NORMAL, scenario="조회 결과가 존재하는 경우 목록 표시",
              precondition=ctx.pre_data, input_data=bullets(ctx.normal_inputs()),
              procedure=steps(_go(ctx), "조건을 입력하고 조회한다.", "결과 건수와 값을 DB와 비교한다."),
              expected=f"조회 결과가 {ctx.grid_label}에 표시되며 건수와 값이 DB({', '.join(tables[:3])}) 데이터와 일치한다.",
              sources=s, priority="높음")
        b.add("result:none", feature=ctx.feature, category=DATA, scenario="조회 결과가 없는 경우",
              precondition=f"{ctx.pre}\n조건에 해당하는 데이터가 없음",
              procedure=steps(_go(ctx), "데이터가 없는 조건을 입력하고 조회한다."),
              expected="오류 없이 0건으로 처리되고 결과 없음 안내가 표시된다.", sources=s, priority="높음",
              review=None if ctx.no_result_msg else f"{REVIEW_BIZ} — 결과 없음 메시지 문구")
    elif st in ("INSERT", "MERGE"):
        cols = ", ".join(f.get("columns", [])[:12])
        b.add(f"sql:{sid}:insert", feature=feature, category=DATA, scenario=f"정상 등록 후 {t0} 데이터 검증",
              precondition=ctx.pre, procedure=steps("정상 값으로 등록을 수행한다.", f"{t0} 테이블에서 등록된 행을 조회한다."),
              expected=f"{t0}에 1건이 생성되고 컬럼({cols or '전체'}) 값이 입력값과 일치한다.", sources=s, priority="높음")
        b.add(f"sql:{sid}:dupkey", feature=feature, category=DUP, scenario=f"동일 키로 중복 등록 ({t0})",
              precondition=f"{ctx.pre}\n동일 키 데이터가 이미 존재함", procedure=steps("같은 키 값으로 다시 등록한다."),
              expected="중복 키 오류가 사용자 친화적 메시지로 표시되고 데이터가 중복 저장되지 않는다.",
              sources=s, priority="높음", review=f"{REVIEW_BIZ} — PK/UNIQUE 구성 확인")
        b.add(f"sql:{sid}:notnull", feature=feature, category=EXC, scenario=f"필수 컬럼 NULL 등록 시도 ({t0})",
              precondition=ctx.pre, procedure=steps("필수 컬럼 값을 비운 채 등록을 요청한다."),
              expected="DB 제약 오류가 처리되어 안내 메시지가 표시되고 트랜잭션이 롤백된다.",
              sources=s, priority="중간", review=f"{REVIEW_BIZ} — NOT NULL 컬럼 확인")
    elif st in ("UPDATE", "DELETE"):
        verb = "수정" if st == "UPDATE" else "삭제"
        logical = st == "UPDATE" and any(re.search(r"(DEL|USE)_?YN", c, re.I) for c in f.get("setColumns", []))
        if logical:
            verb = "삭제(논리)"
        set_cols = ", ".join(f.get("setColumns", [])[:10])
        b.add(f"sql:{sid}:ok", feature=feature, category=DATA, scenario=f"정상 {verb} 후 {t0} 데이터 검증",
              precondition=ctx.pre_data, procedure=steps(f"대상 데이터를 {verb}한다.", f"{t0} 테이블과 화면을 재조회한다."),
              expected=(f"대상 행의 {set_cols} 값이 변경되고, 목록 조회에서 제외된다." if logical
                        else (f"대상 행의 {set_cols} 값이 정확히 변경되고 다른 행은 변경되지 않는다." if st == "UPDATE"
                              else "대상 행만 삭제되고 재조회 시 표시되지 않는다.")),
              sources=s, priority="높음")
        b.add(f"sql:{sid}:notarget", feature=feature, category=EXC, scenario=f"{verb} 대상이 존재하지 않는 경우 (0건)",
              precondition=f"{ctx.pre}\n대상 데이터가 이미 삭제되었거나 존재하지 않음",
              procedure=steps(f"존재하지 않는 키로 {josa(verb, '을/를')} 요청한다."),
              expected="0건 처리 시 안내 메시지가 표시되고 오류가 발생하지 않는다.", sources=s, priority="중간",
              review=f"{REVIEW_BIZ} — 0건 처리 정책")
        if not f.get("hasWhere"):
            b.add(f"sql:{sid}:nowhere", feature=feature, category=DATA, scenario=f"WHERE 조건 없는 {st} — 전체 행 영향 확인",
                  precondition="테스트 DB에 여러 건의 데이터가 존재함", procedure=steps("해당 SQL을 실행하는 기능을 수행한다.", "영향 받은 행 수를 확인한다."),
                  expected=f"{t0} 전체 행이 {verb}되는 것이 의도된 동작인지 확인한다.", sources=s, priority="높음",
                  review=f"{REVIEW_DEV} — WHERE 절 누락 여부")
        if st == "DELETE" or logical:
            b.add(f"sql:{sid}:fk", feature=feature, category=EXC, scenario="연관(자식) 데이터가 존재하는 대상 삭제",
                  precondition="삭제 대상과 연관된 하위 데이터가 존재함", procedure=steps("연관 데이터가 있는 대상을 삭제한다."),
                  expected="FK 오류 없이 정책(삭제 차단/연쇄 삭제)대로 처리된다.", sources=s, priority="중간",
                  review=f"{REVIEW_BIZ} — 연관 데이터 처리 정책")


def _r_sql_cond(b, ctx, f):
    op, col, lab, s = f["op"], f["column"], f["colLabel"], [f["src"]]
    if f["stmtType"] != "SELECT":
        return
    c = canonical(lab)
    if op == "eq" and f.get("literal"):
        b.add(f"sql:lit:{col}:{f['literal']}", feature=ctx.feature, category=DATA,
              scenario=f"고정 조건 {col} = {f['literal']} 적용 확인",
              precondition=f"{ctx.pre}\n{col} 값이 {f['literal']}인 데이터와 아닌 데이터가 모두 존재함",
              procedure=steps(_go(ctx), "조회한다."),
              expected=f"{lab}({col}) 값이 {f['literal']}인 데이터만 조회되고 그 외 데이터는 제외된다.",
              sources=s, priority="중간")
    elif op in ("eq", "in") and f["params"]:
        p = f["params"][0]
        fd = ctx.fields.get(canonical(labelize(p)))
        if op == "in":
            b.add(f"sql:in:{col}:multi", feature=ctx.feature, category=NORMAL, scenario=f"{lab} 복수 값 조건 조회 (IN)",
                  precondition=ctx.pre_data, input_data=bullets([(lab, "값 2개 이상")]),
                  procedure=steps(_go(ctx), f"{josa(lab, '을/를')} 여러 개 선택하고 조회한다."),
                  expected="선택한 값 중 하나라도 일치하는 데이터가 모두 조회된다.", sources=s, priority="중간")
            b.add(f"sql:in:{col}:empty", feature=ctx.feature, category=EXC, scenario=f"{lab} 목록이 비어 있는 경우 (IN 빈 목록)",
                  precondition=ctx.pre, procedure=steps(_go(ctx), f"{josa(lab, '을/를')} 하나도 선택하지 않고 조회한다."),
                  expected="SQL 오류(IN ()) 없이 조건 미적용 또는 안내 메시지로 처리된다.", sources=s, priority="높음")
        elif fd and fd["fieldType"] == "code":
            b.add(f"field:{fd['canon']}:normal", feature=ctx.feature, category=NORMAL,
                  scenario=f"{fd['label']} 정상 코드 선택 후 {ctx.verb}", precondition=ctx.pre_data,
                  procedure=steps(_go(ctx), f"{josa(fd['label'], '을/를')} 선택한다.", _click(ctx)),
                  expected=f"선택한 {fd['label']}에 해당하는 데이터만 {ctx.verb}된다.", sources=s, priority="높음")
    elif op == "like":
        b.add(f"sql:like:{col}:partial", feature=ctx.feature, category=NORMAL, scenario=f"{lab} 부분 일치 검색",
              precondition=ctx.pre_data, input_data=bullets([(lab, "값의 일부 (앞/중간/뒤)")]),
              procedure=steps(_go(ctx), f"{lab}에 일부 문자만 입력하고 조회한다."),
              expected="입력값을 포함하는 데이터가 모두 조회된다.", sources=s, priority="중간")
        b.add(f"sql:like:{col}:wildcard", feature=ctx.feature, category=ERROR, scenario=f"{lab}에 와일드카드 문자(%, _) 입력",
              precondition=ctx.pre_data, input_data=bullets([(lab, "% / _ / ' (작은따옴표)")]),
              procedure=steps(_go(ctx), f"{lab}에 특수문자를 입력하고 조회한다."),
              expected="SQL 오류가 발생하지 않고, 특수문자가 문자 그대로 검색되는지 확인한다.", sources=s, priority="중간",
              review=f"{REVIEW_DEV} — LIKE ESCAPE 처리 여부")
    elif op in ("isNull", "isNotNull"):
        want = "NULL인" if op == "isNull" else "NULL이 아닌"
        b.add(f"sql:null:{col}:{op}", feature=ctx.feature, category=DATA, scenario=f"{lab}({col}) {want} 데이터만 조회되는지 확인",
              precondition=f"{ctx.pre}\n{col}이 NULL인 데이터와 값이 있는 데이터가 모두 존재함",
              procedure=steps(_go(ctx), "조회한다."), expected=f"{col}이 {want} 데이터만 조회된다.", sources=s, priority="중간")
    elif op in ("ge", "gt", "le", "lt") and f["params"] and canonical(lab) not in ctx.range_canons:
        sym = {"ge": ">=", "gt": ">", "le": "<=", "lt": "<"}[op]
        b.add(f"sql:cmp:{col}:{op}", feature=ctx.feature, category=BOUNDARY, scenario=f"{lab} 경계값 조건({col} {sym} 입력값) 확인",
              precondition=f"{ctx.pre}\n{col} 값이 입력값과 같은 데이터, ±1 데이터가 존재함",
              procedure=steps(_go(ctx), "경계값을 입력하고 조회한다."),
              expected=f"{col} {sym} 조건에 따라 경계값 데이터의 포함/제외가 정확하다.", sources=s, priority="중간")
    elif op == "exists":
        b.add(f"sql:exists:{f['sqlId']}:{'not' if f['negate'] else ''}", feature=ctx.feature, category=DATA,
              scenario=f"{'NOT ' if f['negate'] else ''}EXISTS 서브쿼리 조건 확인",
              precondition=f"{ctx.pre}\n연관 데이터가 있는 행과 없는 행이 모두 존재함", procedure=steps(_go(ctx), "조회한다."),
              expected=f"연관 데이터가 {'없는' if f['negate'] else '있는'} 행만 조회된다.", sources=s, priority="중간")
    elif op == "expr":
        b.add(f"sql:expr:{f['literal'][:40]}", feature=ctx.feature, category=BRANCH, scenario=f"SQL 조건 확인: {f['literal'][:60]}",
              precondition=ctx.pre_data, procedure=steps(_go(ctx), "조건을 만족/불만족하는 데이터로 조회한다."),
              expected="조건에 맞는 데이터만 조회된다.", sources=s, priority="낮음", review=f"{REVIEW_DEV} — 조건 의미 확인")
    if f.get("nvl"):
        b.add(f"sql:nvlcond:{col}", feature=ctx.feature, category=DATA, scenario=f"{col}이 NULL인 데이터의 조건 처리(NVL)",
              precondition=f"{ctx.pre}\n{col}이 NULL인 데이터가 존재함", procedure=steps(_go(ctx), "조회한다."),
              expected="NVL 기본값 기준으로 조건이 적용된다.", sources=s, priority="낮음")


def _r_sql_join(b, ctx, f):
    t, jt = f["table"], f["joinType"]
    if jt in ("LEFT", "RIGHT", "FULL"):
        exp = f"조인 대상({t}) 데이터가 없어도 기준 행은 조회되고, 조인 컬럼은 빈 값(또는 NVL 기본값)으로 표시된다."
    else:
        exp = f"조인 대상({t})에 일치하는 데이터가 없는 행은 조회되지 않는다."
    b.add(f"sql:join:{f['sqlId']}:{t}", feature=ctx.feature, category=DATA, scenario=f"{jt} JOIN 대상({t}) 데이터 미존재 시 결과 확인",
          precondition=f"{ctx.pre}\n{t}에 매칭되는 데이터가 없는 기준 데이터가 존재함", procedure=steps(_go(ctx), "조회한다."),
          expected=exp, sources=[f["src"]], priority="중간")


def _r_sql_case(b, ctx, f):
    for w in f["whens"]:
        b.add(f"sql:case:{f['sqlId']}:{w}", feature=ctx.feature, category=BRANCH, scenario=f"CASE 분기: WHEN {w}",
              precondition=f"{ctx.pre}\n{w} 조건을 만족하는 데이터가 존재함", procedure=steps(_go(ctx), "조회한다."),
              expected="해당 WHEN 분기의 결과값이 표시된다.", sources=[f["src"]], priority="중간")
    b.add(f"sql:case:{f['sqlId']}:else", feature=ctx.feature, category=BRANCH, scenario="CASE 분기: 어느 WHEN에도 해당하지 않는 데이터",
          precondition=f"{ctx.pre}\nWHEN 조건에 해당하지 않는 데이터가 존재함", procedure=steps(_go(ctx), "조회한다."),
          expected=("ELSE 분기 값이 표시된다." if f["hasElse"] else "ELSE 가 없어 NULL 이 표시된다 — 의도 여부 확인"),
          sources=[f["src"]], priority="중간" if f["hasElse"] else "높음",
          review=None if f["hasElse"] else f"{REVIEW_DEV} — CASE ELSE 누락")


def _r_sql_nvl(b, ctx, f):
    b.add(f"sql:nvl:{f['column']}", feature=ctx.feature, category=DATA, scenario=f"{f['colLabel']}({f['column']}) NULL 데이터 표시",
          precondition=f"{ctx.pre}\n{f['column']}이 NULL인 데이터가 존재함", procedure=steps(_go(ctx), "조회한다."),
          expected=f"NULL 값이 {f['default']}(으)로 표시된다.", sources=[f["src"]], priority="낮음")


def _r_sql_order(b, ctx, f):
    b.add(f"sql:order:{f['sqlId']}", feature=ctx.feature, category=DATA, scenario="조회 결과 정렬 순서 확인",
          precondition=f"{ctx.pre_data}\n정렬 기준 값이 서로 다른 데이터가 여러 건 존재함", procedure=steps(_go(ctx), "조회한다.", "정렬 순서를 확인한다."),
          expected=f"결과가 {', '.join(f['columns'])} 순서로 정렬된다.", sources=[f["src"]], priority="낮음")


def _r_sql_group(b, ctx, f):
    b.add(f"sql:group:{f['sqlId']}", feature=ctx.feature, category=DATA, scenario="집계(GROUP BY) 결과 정확성 확인",
          precondition=f"{ctx.pre}\n그룹별로 여러 건의 데이터가 존재함", procedure=steps(_go(ctx), "조회한다.", "그룹별 합계/건수를 수기 계산값과 비교한다."),
          expected=f"{', '.join(f['columns'])} 기준 집계 결과가 정확하다.", sources=[f["src"]], priority="중간")


def _r_sql_paging(b, ctx, f):
    for k, sc, ex in (("first", "첫 페이지 조회", "1페이지 데이터가 정확히 페이지 크기만큼 표시된다."),
                      ("last", "마지막 페이지 조회", "남은 건수만 표시되고 오류가 없다."),
                      ("boundary", "총 건수가 페이지 크기의 배수인 경우", "빈 페이지가 생기지 않는다.")):
        b.add(f"sql:paging:{k}", feature=ctx.feature, category=BOUNDARY, scenario=f"페이징: {sc}", precondition=ctx.pre_data,
              procedure=steps(_go(ctx), "조회 후 페이지를 이동한다."), expected=ex, sources=[f["src"]], priority="낮음")


def _r_sql_distinct(b, ctx, f):
    b.add(f"sql:distinct:{f['sqlId']}", feature=ctx.feature, category=DATA, scenario="DISTINCT 중복 제거 확인",
          precondition=f"{ctx.pre}\n중복될 수 있는 데이터가 존재함", procedure=steps(_go(ctx), "조회한다."),
          expected="중복 행이 제거되어 표시된다.", sources=[f["src"]], priority="낮음")


def _r_sql_injection(b, ctx, f):
    b.add(f"sql:inj:{f['param']}", feature=ctx.feature, category=ERROR, scenario=f"${{{f['param']}}} 문자열 치환 파라미터에 SQL 구문 입력",
          precondition=ctx.pre, input_data=bullets([(labelize(f["param"]), "' OR '1'='1 / ; DROP TABLE")]),
          procedure=steps(_go(ctx), "해당 파라미터에 SQL 특수 구문을 입력한다."),
          expected="SQL Injection 이 발생하지 않는다 (허용 값 화이트리스트 검증).", sources=[f["src"]], priority="높음",
          note="${} 는 문자열 그대로 치환되므로 #{} 사용 또는 화이트리스트 검증 권장")


# ---------------------------------------------------------------------------
# Java 규칙
# ---------------------------------------------------------------------------
def _jf(f):
    return f"{f['cls']}.{f['method']}"


def _j_var(f, key="var", label="varLabel"):
    v, l = f[key], f.get(label) or f[key]
    return f"{l}({v})" if l != v else v


def _j_outcome(f):
    if f.get("throws"):
        msg = f" — '{f['message']}'" if f.get("message") else ""
        return f"{f['exType']} 예외가 발생하고 처리가 중단된다{msg}."
    if f.get("returns"):
        return "즉시 반환(return)되어 이후 로직이 수행되지 않는다."
    if f.get("comment"):
        return f"'{f['comment']}' 로직이 수행된다."
    return None


def _r_java_method(b, ctx, f):
    ps = f["params"]
    ret = f["returnType"]
    exp = {"조회": f"정상 결과({ret})가 반환된다.", "등록": "등록 처리되고 DB에 반영된다.", "수정": "수정 처리되고 DB에 반영된다.",
           "삭제": "삭제 처리되고 처리 건수가 반환된다." if ret and ret != "void" else "삭제 처리된다."}.get(
        f["action"], "예외 없이 정상 종료된다." if ret in ("void", "") else f"정상 결과({ret})가 반환된다.")
    b.add(f"java:{_jf(f)}:normal", feature=_jf(f), category=NORMAL, scenario=f"{f['method']} 정상 파라미터로 호출",
          precondition="테스트 데이터가 준비되어 있음",
          input_data=bullets([(None, p) for p in ps]) or "- (파라미터 없음)",
          procedure=steps(f"{_jf(f)} 메서드를 정상 파라미터로 호출한다." if f["method"] != "(코드 조각)" else "코드가 실행되는 기능을 정상 값으로 수행한다.",
                          "반환값과 DB 상태를 확인한다."),
          expected=exp, note=("호출: " + ", ".join(f["calls"])) if f.get("calls") else "",
          sources=[f["src"]], priority="중간")
    for t in f.get("throws", []):
        b.add(f"java:{_jf(f)}:throws:{t}", feature=_jf(f), category=EXC, scenario=f"{t} 발생 시 호출부 처리",
              precondition=f"{t} 예외가 발생하는 상황을 구성함", procedure=steps(f"{_jf(f)} 실행 중 {t} 예외가 발생하도록 한다."),
              expected="호출부에서 예외가 처리되어 사용자에게 오류 안내가 표시된다.", sources=[f["src"]], priority="중간",
              review=f"{REVIEW_DEV} — 예외 처리 위치")


def _r_java_null(b, ctx, f):
    kind = "null" if f["kind"] == "javaNull" else "빈 값"
    v = _j_var(f)
    out = _j_outcome(f)
    if not f["negate"]:
        b.add(f"java:{_jf(f)}:{kind}:{f['var']}", feature=_jf(f), category=EXC if f.get("throws") else BRANCH,
              scenario=f"{josa(v, '이/가')} {kind}인 경우", precondition="",
              input_data=bullets([(v, kind if kind == "null" else '"" 또는 빈 목록')]),
              procedure=steps(f"{f['var']}에 {kind} 값을 설정하여 {_jf(f)} 메서드를 호출한다."),
              expected=out or f"{kind} 분기 처리가 수행된다.", sources=[f["src"]],
              priority="높음" if f.get("throws") else "중간",
              review=None if out else f"{REVIEW_DEV} — {kind} 분기 업무 의미")
    else:
        b.add(f"java:{_jf(f)}:{kind}:{f['var']}", feature=_jf(f), category=BRANCH,
              scenario=f"{josa(v, '이/가')} {kind}인 경우 (조건 미충족)",
              input_data=bullets([(v, kind)]), procedure=steps(f"{f['var']}에 {kind} 값을 설정하여 호출한다."),
              expected=f"{kind} 이 아닐 때만 수행되는 로직이 생략되고 NullPointerException 이 발생하지 않는다.",
              sources=[f["src"]], priority="중간")


def _r_java_eq(b, ctx, f):
    v = _j_var(f)
    for item in f["values"]:
        val = item["value"]
        if item.get("throws"):
            exp = f"{item['throws']} 예외가 발생한다."
        elif item.get("comment"):
            exp = f"'{item['comment']}' 로직이 수행된다."
        else:
            exp = None
        b.add(f"java:{_jf(f)}:eq:{f['var']}:{val}", feature=_jf(f), category=BRANCH,
              scenario=f"{josa(v, '이/가')} \"{val}\"인 경우", input_data=bullets([(v, f'"{val}"')]),
              procedure=steps(f"{f['var']}=\"{val}\" 값으로 {_jf(f)} 메서드를 호출한다.", "수행된 분기와 결과를 확인한다."),
              expected=exp or "해당 분기 로직이 수행된다.", sources=[f["src"]], priority="중간",
              review=None if exp else f"{REVIEW_DEV} — 분기 업무 의미")
    if not f.get("partOfCompound"):
        vals = ", ".join(f"\"{x['value']}\"" for x in f["values"])
        if f["hasElse"]:
            exp = f"else 분기가 수행된다{(': ' + f['elseComment']) if f.get('elseComment') else ''}."
            rv = None
        else:
            exp = "어떤 분기도 수행되지 않는다 — 미정의 값에 대한 처리(오류/무시)가 의도된 것인지 확인한다."
            rv = f"{REVIEW_DEV} — 미정의 값 처리"
        b.add(f"java:{_jf(f)}:eq:{f['var']}:undefined", feature=_jf(f), category=ERROR,
              scenario=f"{josa(v, '이/가')} 정의되지 않은 값인 경우 ({vals} 외)", input_data=bullets([(v, '"99" 또는 null')]),
              procedure=steps(f"{f['var']}에 정의되지 않은 값을 넣어 호출한다."),
              expected=exp, sources=[f["src"]], priority="중간", review=rv)


def _r_java_compare(b, ctx, f):
    l, op, r = f["left"], f["op"], f["right"]
    lv = f"{f['leftLabel']}({l})" if f.get("leftLabel") and f["leftLabel"] != l else l
    out = _j_outcome(f) or "조건 충족 시 분기 로직이 수행된다."
    if re.match(r"^-?\d+$", r):
        n = int(r)
        sat = {">": n + 1, ">=": n, "<": n - 1, "<=": n, "==": n, "!=": n + 1}[op]
        unsat = {">": n, ">=": n - 1, "<": n, "<=": n + 1, "==": n + 1, "!=": n}[op]
        b.add(f"java:{_jf(f)}:cmp:{l}:{op}{r}:sat", feature=_jf(f), category=BOUNDARY,
              scenario=f"{lv} = {sat:,} (조건 {l} {op} {n:,} 충족 경계)", input_data=bullets([(lv, f"{sat:,}")]),
              procedure=steps(f"{l}={sat}로 호출한다."), expected=out, sources=[f["src"]],
              priority="높음" if f.get("throws") else "중간")
        b.add(f"java:{_jf(f)}:cmp:{l}:{op}{r}:unsat", feature=_jf(f), category=BOUNDARY,
              scenario=f"{lv} = {unsat:,} (조건 {l} {op} {n:,} 미충족 경계)", input_data=bullets([(lv, f"{unsat:,}")]),
              procedure=steps(f"{l}={unsat}로 호출한다."), expected="조건 분기가 수행되지 않고 다음 로직으로 진행된다.",
              sources=[f["src"]], priority="중간")
    else:
        rl = labelize(r.split(".")[-1])
        b.add(f"java:{_jf(f)}:cmp:{l}:{op}{r}:sat", feature=_jf(f), category=BOUNDARY if not f.get("throws") else EXC,
              scenario=f"{lv} {op} {rl}({r}) 조건 충족", input_data=bullets([(lv, f"{r}보다 {'큰' if '>' in op else '작은'} 값")]),
              procedure=steps("조건을 만족하는 값으로 호출한다."), expected=out, sources=[f["src"]],
              priority="높음" if f.get("throws") else "중간", review=None if _j_outcome(f) else f"{REVIEW_DEV} — 분기 의미")
        b.add(f"java:{_jf(f)}:cmp:{l}:{op}{r}:eq", feature=_jf(f), category=BOUNDARY,
              scenario=f"{lv}, {rl}({r}) 두 값이 같은 경우 (경계)", input_data=bullets([(lv, f"{r}와 동일")]),
              procedure=steps("두 값을 같게 하여 호출한다."),
              expected=("조건(" + f"{l} {op} {r}" + ")에 따라 " + ("분기 수행" if "=" in op else "분기가 수행되지 않음") + "."),
              sources=[f["src"]], priority="중간")


def _r_java_cond(b, ctx, f):
    out = _j_outcome(f)
    b.add(f"java:{_jf(f)}:cond:{f['expr'][:50]}", feature=_jf(f), category=BRANCH,
          scenario=f"조건 분기 if ({f['expr'][:80]}) 충족/미충족",
          procedure=steps("조건을 만족하는 값으로 호출한다.", "조건을 만족하지 않는 값으로 호출한다."),
          expected=(f"충족 시: {out}\n미충족 시: 다음 로직으로 진행된다." if out else "각 경우의 분기 로직이 수행된다."),
          sources=[f["src"]], priority="중간", review=f"{REVIEW_DEV} — 복합 조건 값 조합")


def _r_java_switch(b, ctx, f):
    v = f"{f['exprLabel']}({f['expr']})" if f.get("exprLabel") and f["exprLabel"] != f["expr"] else f["expr"]
    for cs in f["cases"]:
        b.add(f"java:{_jf(f)}:switch:{f['expr']}:{cs}", feature=_jf(f), category=BRANCH, scenario=f"switch {v} = {cs}",
              input_data=bullets([(v, cs)]), procedure=steps(f"{f['expr']}={cs}가 되도록 호출한다."),
              expected=f"case {cs} 로직이 수행된다.", sources=[f["src"]], priority="중간")
    b.add(f"java:{_jf(f)}:switch:{f['expr']}:default", feature=_jf(f), category=BRANCH if f["hasDefault"] else ERROR,
          scenario=f"switch {v} — case 에 없는 값", input_data=bullets([(v, "정의되지 않은 값")]),
          procedure=steps("case 에 없는 값으로 호출한다."),
          expected="default 로직이 수행된다." if f["hasDefault"] else "default 가 없어 아무 처리도 되지 않는다 — 의도 확인",
          sources=[f["src"]], priority="중간", review=None if f["hasDefault"] else f"{REVIEW_DEV} — default 누락")


def _r_java_catch(b, ctx, f):
    ex = f["exType"]
    b.add(f"java:{_jf(f)}:catch:{ex}", feature=_jf(f), category=EXC, scenario=f"{ex} 발생 시 예외 처리",
          precondition=f"{ex} 예외가 발생하도록 환경을 구성함 (예: DB 연결 오류, 제약 위반)",
          procedure=steps(f"{_jf(f)} 실행 중 {ex} 예외를 유발한다.", "예외 처리 결과와 데이터 상태를 확인한다."),
          expected=(f"{f['rethrow']}(으)로 변환되어 전달되고 트랜잭션이 롤백된다." if f.get("rethrow")
                    else "예외가 처리(로그 기록)되고 프로그램이 비정상 종료되지 않는다."),
          sources=[f["src"]], priority="높음", review=None if f.get("rethrow") else f"{REVIEW_DEV} — 예외 무시 여부")


def _r_java_loop(b, ctx, f):
    b.add(f"java:{_jf(f)}:loop:{f['expr'][:30]}:0", feature=_jf(f), category=BOUNDARY, scenario=f"반복 대상 0건 ({f['expr'][:50]})",
          input_data=bullets([("반복 대상", "빈 목록")]), procedure=steps("반복 대상이 없는 상태로 호출한다."),
          expected="오류 없이 반복이 수행되지 않고 정상 종료된다.", sources=[f["src"]], priority="중간")
    b.add(f"java:{_jf(f)}:loop:{f['expr'][:30]}:n", feature=_jf(f), category=BOUNDARY, scenario=f"반복 대상 1건 / 다건 ({f['expr'][:50]})",
          input_data=bullets([("반복 대상", "1건, 100건 이상")]), procedure=steps("반복 대상이 1건, 다건인 경우 각각 호출한다."),
          expected="모든 항목이 누락 없이 처리되고 처리 건수가 일치한다.", sources=[f["src"]], priority="중간")


RULES = {
    "function": _r_function, "noResult": _r_no_result, "resultDisplay": _r_result_display,
    "numericLimit": _r_numeric, "permission": _r_permission, "duplicate": _r_duplicate,
    "condition": _r_condition, "message": _r_message, "unknown": _r_unknown,
    "button": _r_button, "grid": _r_grid, "generator": _r_generator,
    "sqlStatement": _r_sql_stmt, "sqlCond": _r_sql_cond, "sqlJoin": _r_sql_join, "sqlCase": _r_sql_case,
    "sqlNvl": _r_sql_nvl, "sqlOrderBy": _r_sql_order, "sqlGroupBy": _r_sql_group, "sqlPaging": _r_sql_paging,
    "sqlDistinct": _r_sql_distinct, "sqlInjection": _r_sql_injection,
    "javaMethod": _r_java_method, "javaNull": _r_java_null, "javaEmpty": _r_java_null, "javaEqGroup": _r_java_eq,
    "javaCompare": _r_java_compare, "javaCond": _r_java_cond, "javaSwitch": _r_java_switch,
    "javaCatch": _r_java_catch, "javaLoop": _r_java_loop,
}


def _requirement_links(b, ctx, facts):
    """요구사항 문장 ↔ 화면 요소 연결 (예: '제출번호를 클릭하면 상세 화면으로 이동' → 그리드 행 클릭 테스트)."""
    buttons = [f for f in facts if f["kind"] == "button"]
    _r_grid_select(b, ctx, buttons)
    req_sentences = [f for f in facts if f["kind"] in ("condition", "unknown", "message")]
    for key in list(b.cases):
        c = b.cases[key]
        if not key.startswith("grid:rowbtn:"):
            continue
        col = c["scenario"].split("[")[-1].split("]")[0]
        for rf in req_sentences:
            if col and col in rf["text"]:
                b.add(key, feature=c["feature"], category=NORMAL, scenario=c["scenario"], precondition=c["precondition"],
                      procedure=c["steps"], expected=f"요구사항: {rf['text']}", sources=[rf["src"]], priority="중간")
                req_key = ("req:cond:" if rf["kind"] == "condition" else "req:unknown:" if rf["kind"] == "unknown" else "req:msg:") + rf["text"][:40]
                if req_key in b.cases:
                    b.cases.pop(req_key)
                    b.order.remove(req_key)
