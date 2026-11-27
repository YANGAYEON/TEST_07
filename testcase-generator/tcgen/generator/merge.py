"""재분석 결과 병합.

규칙
  - 수동 추가(origin=manual) 케이스 : 그대로 유지
  - 개발자 수정(modified=True) 케이스 : 내용 덮어쓰지 않음. 재분석 결과에 근거가 사라지면 stale 표시
  - 자동 생성 미수정 케이스 : 새 생성 결과로 내용 갱신 (테스트 ID / 실행 결과는 유지)
                               재분석 결과에 없으면 삭제 (단, 실행 결과가 있으면 stale 로 보존)
  - 신규 키 : 새 테스트 ID 를 부여하여 추가
"""
import re
import uuid
from datetime import datetime

CONTENT_FIELDS = ["feature", "category", "scenario", "precondition", "inputData", "steps", "expected",
                  "priority", "note"]
RESULT_FIELDS = ["actual", "status", "executedAt", "tester", "failReason"]


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_uid():
    return uuid.uuid4().hex[:12]


def next_test_id(cases, prefix="TC-"):
    mx = 0
    for c in cases:
        m = re.match(r"^\D*(\d+)$", c.get("testId", ""))
        if m:
            mx = max(mx, int(m.group(1)))
    return f"{prefix}{mx + 1:03d}"


def blank_case(**kw):
    c = {"uid": new_uid(), "testId": "", "key": None, "origin": "manual", "modified": False, "modifiedFields": [],
         "feature": "", "category": "정상 테스트", "scenario": "", "precondition": "", "inputData": "",
         "steps": "", "expected": "", "actual": "", "status": "미실행", "priority": "중간", "sourceText": "",
         "sources": [], "note": "", "needsReview": False, "reviewReason": "", "executedAt": "", "tester": "",
         "failReason": "", "stale": False, "createdAt": now(), "updatedAt": now()}
    c.update(kw)
    return c


def merge_cases(existing, generated):
    gen_by_key = {g["key"]: g for g in generated}
    out, seen, stats = [], set(), {"added": 0, "updated": 0, "kept": 0, "removed": 0, "stale": 0}
    for c in existing:
        key = c.get("key")
        if c.get("origin") == "manual" or not key:
            out.append(c)
            continue
        g = gen_by_key.get(key)
        if c.get("modified"):
            c["stale"] = g is None
            if g is not None:
                seen.add(key)
                # 근거 자료는 최신 분석 결과로 참고 표시만 갱신 (내용 필드는 보존)
                c["sources"] = g["sources"]
                c["sourceText"] = g["sourceText"]
            else:
                stats["stale"] += 1
            stats["kept"] += 1
            out.append(c)
            continue
        if g is None:
            if c.get("status", "미실행") != "미실행":
                c["stale"] = True
                stats["stale"] += 1
                out.append(c)
            else:
                stats["removed"] += 1
            continue
        seen.add(key)
        changed = any(c.get(f) != g.get(f) for f in CONTENT_FIELDS)
        for f in CONTENT_FIELDS + ["sources", "sourceText", "needsReview", "reviewReason"]:
            c[f] = g.get(f, c.get(f))
        c["stale"] = False
        if changed:
            c["updatedAt"] = now()
            stats["updated"] += 1
        out.append(c)
    for g in generated:
        if g["key"] in seen or any(c.get("key") == g["key"] for c in out):
            continue
        c = blank_case(origin="auto", key=g["key"], testId=next_test_id(out))
        for f in CONTENT_FIELDS + ["sources", "sourceText", "needsReview", "reviewReason"]:
            c[f] = g.get(f, c.get(f))
        out.append(c)
        stats["added"] += 1
    return out, stats
