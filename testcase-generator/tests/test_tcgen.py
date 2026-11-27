"""단위 테스트 — 표준 라이브러리 unittest.

실행: python -m unittest discover -s tests -v
"""
import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from tcgen.analyzers import analyze_file, detect_type, ANALYZERS          # noqa: E402
from tcgen.analyzers.common import AnalyzeError, labelize, canonical, josa, decode_bytes  # noqa: E402
from tcgen.excel_writer import build_xlsx                                 # noqa: E402
from tcgen.generator import generate, merge_cases                         # noqa: E402
from tcgen.storage import ProjectStore                                    # noqa: E402

SAMPLES = os.path.join(BASE, "samples")
REQ_EXAMPLE = ("사용자가 신청기간과 신청상태를 입력하면 해당 조건에 맞는 제출내역을 조회한다. "
               "시작일과 종료일은 필수이며, 조회 결과가 없는 경우 안내 메시지를 표시한다.")


def kinds(result, kind):
    return [f for f in result.facts if f["kind"] == kind]


def sample(name):
    with open(os.path.join(SAMPLES, name), "rb") as f:
        data = f.read()
    return analyze_file(detect_type(name, data), name, data)


class CommonTest(unittest.TestCase):
    def test_labelize(self):
        self.assertEqual(labelize("reqStsCd"), "신청상태코드")
        self.assertEqual(labelize("ica_startDt"), "시작일자")
        self.assertEqual(labelize("REQ_DT"), "신청일자")

    def test_canonical_matches_across_sources(self):
        self.assertEqual(canonical("시작일"), canonical(labelize("START_DT")))
        self.assertEqual(canonical("신청상태"), canonical(labelize("reqStsCd")))

    def test_josa(self):
        self.assertEqual(josa("시작일", "을/를"), "시작일을")
        self.assertEqual(josa("코드", "을/를"), "코드를")
        self.assertEqual(josa("제출번호목록(submitNos)", "이/가"), "제출번호목록(submitNos)이")

    def test_decode_cp949(self):
        text, enc = decode_bytes("한글 요구사항".encode("cp949"))
        self.assertEqual(text, "한글 요구사항")
        self.assertEqual(enc, "cp949")


class RequirementTest(unittest.TestCase):
    def test_spec_example(self):
        r = ANALYZERS["REQ"].analyze(REQ_EXAMPLE)
        self.assertEqual([f["name"] for f in kinds(r, "function")], ["제출내역 조회"])
        fields = {f["label"]: f for f in kinds(r, "field")}
        self.assertTrue(fields["시작일"]["required"])
        self.assertTrue(fields["종료일"]["required"])
        self.assertIn("신청상태", fields)
        self.assertEqual(len(kinds(r, "dateRange")), 1)
        self.assertEqual(len(kinds(r, "noResult")), 1)
        self.assertEqual(len(kinds(r, "resultDisplay")), 1)

    def test_unknown_sentence_marked(self):
        r = ANALYZERS["REQ"].analyze("화면은 깔끔하고 보기 좋아야 한다.")
        self.assertEqual(len(kinds(r, "unknown")), 1)
        cases, _ = generate([r])
        self.assertTrue(all(c["needsReview"] for c in cases))


class XmlTest(unittest.TestCase):
    def test_components(self):
        r = sample("submit_list.xml")
        fields = {f["label"]: f for f in kinds(r, "field")}
        self.assertEqual(fields["시작일"]["fieldType"], "date")
        self.assertTrue(fields["시작일"]["required"])
        self.assertEqual(fields["신청상태"]["component"], "selectbox")
        self.assertEqual(len(fields["신청상태"]["options"]), 3)
        self.assertEqual(fields["제출번호"]["maxLength"], 20)
        btn = {b["label"]: b for b in kinds(r, "button")}
        self.assertEqual(btn["조회"]["submissions"], ["sbm_search"])
        self.assertTrue(btn["삭제"]["confirm"])
        grid = kinds(r, "grid")[0]
        self.assertTrue(grid["hasCheck"])
        self.assertEqual(grid["rowButtons"], ["제출번호"])
        self.assertEqual(len(kinds(r, "dateRange")), 1)

    def test_parse_error_has_line(self):
        with self.assertRaises(AnalyzeError) as cm:
            ANALYZERS["XML"].analyze("<html>\n<body>\n<xf:input id='a'>\n</body></html>", "bad.xml")
        self.assertEqual(cm.exception.line, 4)


class SqlTest(unittest.TestCase):
    def test_spec_example(self):
        sql = ("SELECT *\nFROM TB_SUBMIT\nWHERE REQ_DT BETWEEN :START_DT AND :END_DT\n"
               "  AND REQ_STS_CD = :REQ_STS_CD")
        r = ANALYZERS["SQL"].analyze(sql, "q.sql")
        ops = [c["op"] for c in kinds(r, "sqlCond")]
        self.assertEqual(ops, ["between", "eq"])
        self.assertEqual(len(kinds(r, "dateRange")), 1)
        cases, _ = generate([r])
        scen = " | ".join(c["scenario"] for c in cases)
        for expect in ("동일한 날짜", "늦은 경우", "조회 결과가 없는 경우", "시작일자 미입력", "종료일자 미입력",
                       "신청상태코드 미입력", "존재하지 않는 코드값"):
            self.assertIn(expect, scen)

    def test_mybatis_dynamic(self):
        r = sample("SubmitMapper.xml")
        conds = {c["column"]: c for c in kinds(r, "sqlCond")}
        self.assertTrue(conds["REQ_STS_CD"]["optional"])
        self.assertFalse(conds["REQ_DT"]["optional"])
        self.assertEqual(kinds(r, "sqlJoin")[0]["joinType"], "LEFT")
        upd = [s for s in kinds(r, "sqlStatement") if s["stmtType"] == "UPDATE"][0]
        self.assertEqual(upd["setColumns"], ["DEL_YN", "UPD_DT"])

    def test_delete_without_where(self):
        r = ANALYZERS["SQL"].analyze("DELETE FROM TB_TMP", "d.sql")
        cases, _ = generate([r])
        self.assertTrue(any("WHERE 조건 없는" in c["scenario"] for c in cases))


class JavaTest(unittest.TestCase):
    def test_spec_example(self):
        code = ('if (reqDt == null) {\n    throw new IllegalArgumentException();\n}\n'
                'if ("01".equals(reqStsCd)) {\n    // 신청 처리\n} else if ("02".equals(reqStsCd)) {\n    // 취소 처리\n}')
        r = ANALYZERS["JAVA"].analyze(code, "s.java")
        cases, _ = generate([r])
        scen = [c["scenario"] for c in cases]
        self.assertTrue(any("null인 경우" in s for s in scen))
        self.assertTrue(any('"01"인 경우' in s for s in scen))
        self.assertTrue(any('"02"인 경우' in s for s in scen))
        undefined = [c for c in cases if "정의되지 않은 값" in c["scenario"]]
        self.assertEqual(len(undefined), 1)
        self.assertTrue(undefined[0]["needsReview"])
        null_case = [c for c in cases if "null인 경우" in c["scenario"]][0]
        self.assertIn("IllegalArgumentException", null_case["expected"])

    def test_class_methods(self):
        r = sample("SubmitService.java")
        self.assertEqual(r.summary["methods"], ["selectSubmitList", "processRequest", "deleteSubmit"])
        self.assertEqual(len(kinds(r, "javaCatch")), 1)
        self.assertEqual(len(kinds(r, "javaSwitch")), 1)


class GeneratorTest(unittest.TestCase):
    def setUp(self):
        self.results = [ANALYZERS["REQ"].analyze(REQ_EXAMPLE, "req")] + \
                       [sample(n) for n in ("submit_list.xml", "SubmitMapper.xml")]

    def test_integration_merges_sources(self):
        cases, ctx = generate(self.results, "p")
        keys = [c["key"] for c in cases]
        self.assertEqual(len(keys), len(set(keys)))
        start_req = [c for c in cases if c["key"] == "field:시작일:empty"][0]
        types = {s["type"] for s in start_req["sources"]}
        self.assertEqual(types, {"요구사항", "XML", "SQL"})
        self.assertEqual(start_req["priority"], "높음")
        for c in cases:
            self.assertTrue(c["sources"], c["scenario"])   # 모든 케이스에 근거 존재

    def test_merge_preserves_developer_edits(self):
        gen, _ = generate(self.results, "p")
        cases, stats = merge_cases([], gen)
        self.assertEqual(stats["added"], len(gen))
        self.assertEqual(len({c["testId"] for c in cases}), len(cases))
        cases[0]["expected"] = "개발자 수정"
        cases[0]["modified"] = True
        cases[1]["status"] = "성공"
        cases.append({"uid": "m1", "testId": "TC-999", "origin": "manual", "key": None, "scenario": "수동"})
        gen2, _ = generate(self.results, "p")
        merged, stats2 = merge_cases(cases, gen2)
        self.assertEqual(merged[0]["expected"], "개발자 수정")
        self.assertEqual(merged[1]["status"], "성공")
        self.assertTrue(any(c["uid"] == "m1" for c in merged))
        self.assertEqual(stats2["added"], 0)

        # 근거 자료 제거 후 재분석 → 수정 케이스는 stale 로 보존
        gen3, _ = generate(self.results[:1], "p")
        merged3, stats3 = merge_cases(merged, gen3)
        self.assertGreater(stats3["removed"], 0)
        self.assertTrue(any(c["expected"] == "개발자 수정" for c in merged3))


class ExcelAndStorageTest(unittest.TestCase):
    def test_xlsx_structure(self):
        gen, _ = generate([ANALYZERS["REQ"].analyze(REQ_EXAMPLE, "req")])
        cases, _ = merge_cases([], gen)
        cases[0]["note"] = "제어문자\x01포함 & <태그>"
        data = build_xlsx({"name": "테스트"}, cases)
        z = zipfile.ZipFile(io.BytesIO(data))
        sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("<autoFilter", sheet)
        self.assertIn('state="frozen"', sheet)
        self.assertIn("wrapText", z.read("xl/styles.xml").decode())
        self.assertIn("&lt;태그&gt;", sheet)
        self.assertNotIn("\x01", sheet)
        import xml.dom.minidom
        for n in z.namelist():
            if n.endswith(".xml") or n.endswith(".rels"):
                xml.dom.minidom.parseString(z.read(n))

    def test_large_export(self):
        gen, _ = generate([ANALYZERS["REQ"].analyze(REQ_EXAMPLE, "req")])
        cases, _ = merge_cases([], gen)
        many = [dict(cases[i % len(cases)], testId=f"TC-{i:05d}") for i in range(3000)]
        self.assertGreater(len(build_xlsx({"name": "대용량"}, many)), 10000)

    def test_store_roundtrip(self):
        d = tempfile.mkdtemp()
        try:
            st = ProjectStore(d)
            p = st.create("저장 테스트", "설명")
            with self.assertRaises(Exception):
                st.create("저장 테스트")
            st.add_file(p, "a.sql", b"SELECT 1 FROM DUAL", "SQL", "SQL")
            st.save(p)
            again = ProjectStore(d).get(p["id"])
            self.assertEqual(again["files"][0]["name"], "a.sql")
            self.assertEqual(st.read_file(p["id"], again["files"][0]["id"]), b"SELECT 1 FROM DUAL")
            st.delete(p["id"])
            self.assertEqual(st.list(), [])
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
