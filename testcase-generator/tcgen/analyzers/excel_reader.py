"""Excel(.xlsx) 요구사항 문서 읽기 — 표준 라이브러리(zipfile + XML)만 사용.

입력 : xlsx 바이트
출력 : 요구사항 분석기에 전달할 텍스트(셀 단위 문장) + 시트별 행 수
"""
import io
import re
import zipfile
import xml.etree.ElementTree as ET

from .common import AnalyzeError

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def read_xlsx_text(data, max_rows=20000):
    if data[:4] == b"\xd0\xcf\x11\xe0":
        raise AnalyzeError("구 버전 Excel(.xls)은 지원하지 않습니다. Excel에서 .xlsx 형식으로 다시 저장해 주세요.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise AnalyzeError("올바른 xlsx 파일이 아닙니다 (압축 구조 오류).")
    try:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_map = {r.get("Id"): r.get("Target") for r in rels}
        lines, sheets = [], []
        for sh in wb.findall("m:sheets/m:sheet", NS):
            target = rel_map.get(sh.get(REL_NS), "")
            path = "xl/" + target.lstrip("/").replace("xl/", "") if target else None
            if not path or path not in zf.namelist():
                continue
            root = ET.fromstring(zf.read(path))
            rows = root.findall(".//m:sheetData/m:row", NS)
            sheets.append({"name": sh.get("name"), "rows": len(rows)})
            for r_idx, row in enumerate(rows[:max_rows]):
                cells = []
                for c in row.findall("m:c", NS):
                    t = c.get("t")
                    if t == "s":
                        v = c.find("m:v", NS)
                        val = shared[int(v.text)] if v is not None and v.text and v.text.isdigit() and int(v.text) < len(shared) else ""
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter("{%s}t" % NS["m"]))
                    else:
                        v = c.find("m:v", NS)
                        val = v.text if v is not None and v.text else ""
                    if val:
                        cells.append(val.strip())
                # 한글 문장으로 보이는 셀만 요구사항 문장으로 사용 (ID/번호 셀 제외)
                for val in cells:
                    for ln in val.splitlines():
                        if len(re.findall(r"[가-힣]", ln)) >= 6:
                            lines.append(ln.strip())
        return "\n".join(lines), sheets
    except AnalyzeError:
        raise
    except Exception as e:
        raise AnalyzeError(f"Excel 파일을 읽는 중 오류가 발생했습니다: {e}")
