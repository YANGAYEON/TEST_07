"""테스트 케이스 빌더 — 키 기반 중복 제거, 근거 자료 병합, 문장 조립 도우미."""
from ..analyzers.common import josa

PRIORITY_RANK = {"낮음": 1, "중간": 2, "높음": 3}
RANK_PRIORITY = {v: k for k, v in PRIORITY_RANK.items()}
REVIEW_DEV = "개발자 확인 필요"
REVIEW_BIZ = "업무 규칙 확인 필요"


def steps(*lines):
    lines = [l for l in lines if l]
    return "\n".join(f"{i}. {l}" for i, l in enumerate(lines, 1))


def bullets(pairs):
    """[(라벨, 값)] → '- 라벨: 값' 줄 목록"""
    out = []
    for k, v in pairs:
        if v is None or v == "":
            continue
        out.append(f"- {k}: {v}" if k else f"- {v}")
    return "\n".join(out)


def src_text(s):
    type_name = {"요구사항": "요구사항", "XML": "화면XML", "SQL": "SQL", "Java": "Java"}.get(s.get("type"), s.get("type", ""))
    loc = f" L{s['line']}" if s.get("line") else ""
    detail = f" — {s['detail']}" if s.get("detail") else ""
    return f"[{type_name}] {s.get('file', '')}{loc}{detail}"


class CaseBuilder:
    def __init__(self):
        self.cases = {}
        self.order = []

    def add(self, key, *, feature, category, scenario, expected, sources, precondition="", input_data="",
            procedure="", priority="중간", note="", review=None):
        sources = [s for s in (sources if isinstance(sources, list) else [sources]) if s]
        new = {"key": key, "feature": feature, "category": category, "scenario": scenario,
               "precondition": precondition, "inputData": input_data, "steps": procedure,
               "expected": expected, "priority": priority, "note": note,
               "needsReview": bool(review), "reviewReason": review or "", "_sources": sources}
        cur = self.cases.get(key)
        if cur is None:
            self.cases[key] = new
            self.order.append(key)
            return new
        # 병합: 근거 추가, 중요도는 높은 쪽
        for s in sources:
            if not any(_same_src(s, x) for x in cur["_sources"]):
                cur["_sources"].append(s)
        if PRIORITY_RANK[priority] > PRIORITY_RANK[cur["priority"]]:
            cur["priority"] = priority
        if cur["needsReview"] and not review:
            # 확정 근거가 있는 쪽의 내용으로 교체
            for k in ("scenario", "expected", "category", "precondition"):
                if new[k]:
                    cur[k] = new[k]
            if new["inputData"]:
                cur["inputData"] = new["inputData"]
            if new["steps"]:
                cur["steps"] = new["steps"]
            cur["needsReview"] = False
            cur["reviewReason"] = ""
        if note and note not in cur["note"]:
            cur["note"] = (cur["note"] + "\n" + note).strip()
        return cur

    def has(self, key):
        return key in self.cases

    def results(self):
        out = []
        for k in self.order:
            c = dict(self.cases[k])
            srcs = c.pop("_sources")
            types = {s.get("type") for s in srcs}
            # 여러 종류의 자료에서 같은 테스트가 도출되면 중요도 한 단계 상향 (통합 분석)
            if len(types) >= 2 and c["priority"] != "높음" and not c["needsReview"]:
                c["priority"] = RANK_PRIORITY[PRIORITY_RANK[c["priority"]] + 1]
            c["sources"] = srcs
            c["sourceText"] = "\n".join(src_text(s) for s in srcs)
            if c["needsReview"]:
                c["note"] = (f"※ {c['reviewReason']}\n" + c["note"]).strip()
            out.append(c)
        return out


def _same_src(a, b):
    return a.get("file") == b.get("file") and a.get("line") == b.get("line") and a.get("detail") == b.get("detail")


__all__ = ["CaseBuilder", "steps", "bullets", "josa", "REVIEW_DEV", "REVIEW_BIZ"]
