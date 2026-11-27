"""테스트 케이스 Excel(.xlsx) 출력 — 표준 라이브러리(zipfile)로 OOXML 을 직접 작성.

외부 라이브러리(Apache POI, openpyxl) 없이 폐쇄망에서 동작한다.
  - 헤더 스타일, 열 너비 자동 조정, 줄바꿈, 행 높이 자동 계산
  - 헤더 자동 필터(테스트 상태별 필터), 틀 고정
  - 테스트 상태 드롭다운(데이터 유효성 검사), 상태별 색상
  - 요약 시트 (분류/상태별 건수)
"""
import io
import math
import re
import unicodedata
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

COLUMNS = [
    ("테스트 ID", "testId"), ("기능명", "feature"), ("테스트 분류", "category"), ("테스트 시나리오", "scenario"),
    ("사전 조건", "precondition"), ("입력 데이터", "inputData"), ("테스트 절차", "steps"), ("예상 결과", "expected"),
    ("실제 결과", "actual"), ("테스트 상태", "status"), ("중요도", "priority"), ("근거 자료", "sourceText"),
    ("비고", "note"), ("실행 일자", "executedAt"), ("테스트 수행자", "tester"), ("실패 사유", "failReason"),
    ("생성 구분", "_origin"),
]
MAX_WIDTH = {"scenario": 40, "precondition": 34, "inputData": 34, "steps": 46, "expected": 46, "actual": 34,
             "sourceText": 50, "note": 34, "failReason": 30, "feature": 26}

_INVALID = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def _x(s):
    return escape(_INVALID.sub("", str(s if s is not None else "")))


def _dw(s):
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _origin(c):
    if c.get("origin") == "manual":
        return "수동 추가"
    return "자동 생성(수정됨)" if c.get("modified") else "자동 생성"


STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="4">
 <font><sz val="10"/><name val="맑은 고딕"/><family val="3"/><charset val="129"/></font>
 <font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="맑은 고딕"/><family val="3"/><charset val="129"/></font>
 <font><b/><sz val="14"/><color rgb="FF1F2A44"/><name val="맑은 고딕"/><family val="3"/><charset val="129"/></font>
 <font><b/><sz val="10"/><name val="맑은 고딕"/><family val="3"/><charset val="129"/></font>
</fonts>
<fills count="8">
 <fill><patternFill patternType="none"/></fill>
 <fill><patternFill patternType="gray125"/></fill>
 <fill><patternFill patternType="solid"><fgColor rgb="FF2F3E75"/><bgColor indexed="64"/></patternFill></fill>
 <fill><patternFill patternType="solid"><fgColor rgb="FFE3F4E8"/><bgColor indexed="64"/></patternFill></fill>
 <fill><patternFill patternType="solid"><fgColor rgb="FFFDE4E4"/><bgColor indexed="64"/></patternFill></fill>
 <fill><patternFill patternType="solid"><fgColor rgb="FFFFF4D6"/><bgColor indexed="64"/></patternFill></fill>
 <fill><patternFill patternType="solid"><fgColor rgb="FFEEF1F8"/><bgColor indexed="64"/></patternFill></fill>
 <fill><patternFill patternType="solid"><fgColor rgb="FFFFF8E8"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="2">
 <border><left/><right/><top/><bottom/><diagonal/></border>
 <border><left style="thin"><color rgb="FFC9CFDD"/></left><right style="thin"><color rgb="FFC9CFDD"/></right><top style="thin"><color rgb="FFC9CFDD"/></top><bottom style="thin"><color rgb="FFC9CFDD"/></bottom><diagonal/></border>
</borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="10">
 <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
 <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
 <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
 <xf numFmtId="0" fontId="3" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="top" wrapText="1"/></xf>
 <xf numFmtId="0" fontId="3" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="top" wrapText="1"/></xf>
 <xf numFmtId="0" fontId="3" fillId="5" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="top" wrapText="1"/></xf>
 <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="top" wrapText="1"/></xf>
 <xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>
 <xf numFmtId="0" fontId="3" fillId="6" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center"/></xf>
 <xf numFmtId="0" fontId="0" fillId="7" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""

STATUS_STYLE = {"성공": 3, "실패": 4, "보류": 5, "미실행": 6}
CENTER_KEYS = {"testId", "category", "priority", "executedAt", "tester", "_origin"}


def _cell(ref, value, style):
    v = _x(value)
    if v == "":
        return f'<c r="{ref}" s="{style}"/>'
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{v}</t></is></c>'


def build_cases_sheet(cases):
    widths = []
    for title, key in COLUMNS:
        w = _dw(title) + 2
        for c in cases:
            val = _origin(c) if key == "_origin" else str(c.get(key) or "")
            for ln in val.split("\n")[:30]:
                w = max(w, _dw(ln) + 2)
        widths.append(max(8, min(w, MAX_WIDTH.get(key, 22))))
    rows = []
    hdr = "".join(_cell(f"{_col(i)}1", t, 1) for i, (t, _) in enumerate(COLUMNS))
    rows.append(f'<row r="1" ht="24" customHeight="1">{hdr}</row>')
    for r, c in enumerate(cases, start=2):
        cells, lines = [], 1
        for i, (_, key) in enumerate(COLUMNS):
            val = _origin(c) if key == "_origin" else (c.get(key) or "")
            if key == "status":
                st = STATUS_STYLE.get(val, 6)
            elif key in CENTER_KEYS:
                st = 6
            elif c.get("needsReview") and key in ("scenario", "expected", "note"):
                st = 9
            else:
                st = 2
            cells.append(_cell(f"{_col(i)}{r}", val, st))
            est = sum(max(1, math.ceil(_dw(ln) / max(widths[i] - 1, 1))) for ln in str(val).split("\n")) if val else 1
            lines = max(lines, est)
        ht = min(409, max(18, lines * 14 + 4))
        rows.append(f'<row r="{r}" ht="{ht}" customHeight="1">{"".join(cells)}</row>')
    last_col = _col(len(COLUMNS) - 1)
    last_row = max(len(cases) + 1, 2)
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    status_col = _col([k for _, k in COLUMNS].index("status"))
    prio_col = _col([k for _, k in COLUMNS].index("priority"))
    dv = (f'<dataValidations count="2">'
          f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" sqref="{status_col}2:{status_col}{last_row + 500}">'
          f'<formula1>"미실행,성공,실패,보류"</formula1></dataValidation>'
          f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" sqref="{prio_col}2:{prio_col}{last_row + 500}">'
          f'<formula1>"높음,중간,낮음"</formula1></dataValidation></dataValidations>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<dimension ref="A1:{last_col}{last_row}"/>'
            '<sheetViews><sheetView workbookViewId="0" zoomScale="90"><pane ySplit="1" xSplit="1" topLeftCell="B2" '
            'activePane="bottomRight" state="frozen"/><selection pane="bottomRight" activeCell="B2" sqref="B2"/></sheetView></sheetViews>'
            '<sheetFormatPr defaultRowHeight="16.5"/>'
            f'<cols>{cols}</cols><sheetData>{"".join(rows)}</sheetData>'
            f'<autoFilter ref="A1:{last_col}{last_row}"/>{dv}'
            '<pageMargins left="0.4" right="0.4" top="0.5" bottom="0.5" header="0.3" footer="0.3"/>'
            '<pageSetup orientation="landscape" paperSize="9" fitToHeight="0"/>'
            '</worksheet>')


def build_summary_sheet(project, cases):
    from .generator import CATEGORIES, STATUSES, PRIORITIES
    rows, r = [], 1

    def row(cells, ht=None):
        nonlocal r
        h = f' ht="{ht}" customHeight="1"' if ht else ""
        rows.append(f'<row r="{r}"{h}>' + "".join(_cell(f"{_col(i)}{r}", v, s) for i, (v, s) in enumerate(cells)) + "</row>")
        r += 1

    row([(f"테스트 케이스 요약 — {project.get('name', '')}", 7)], 26)
    row([("출력 일시", 8), (datetime.now().strftime("%Y-%m-%d %H:%M"), 2)])
    row([("프로젝트 설명", 8), (project.get("description", ""), 2)])
    r += 1
    total = len(cases)
    done = sum(1 for c in cases if c.get("status") in ("성공", "실패"))
    passed = sum(1 for c in cases if c.get("status") == "성공")
    row([("구분", 1), ("건수", 1), ("비율", 1)])
    row([("전체", 8), (total, 6), ("100%", 6)])
    for st in STATUSES:
        n = sum(1 for c in cases if c.get("status") == st)
        row([(st, 8), (n, STATUS_STYLE.get(st, 6)), (f"{(n / total * 100 if total else 0):.1f}%", 6)])
    row([("수행률", 8), (f"{done}/{total}", 6), (f"{(done / total * 100 if total else 0):.1f}%", 6)])
    row([("성공률(수행 대비)", 8), (f"{passed}/{done}", 6), (f"{(passed / done * 100 if done else 0):.1f}%", 6)])
    r += 1
    row([("테스트 분류", 1), ("건수", 1), ("실패", 1)])
    for cat in CATEGORIES:
        n = sum(1 for c in cases if c.get("category") == cat)
        if n:
            row([(cat, 8), (n, 6), (sum(1 for c in cases if c.get("category") == cat and c.get("status") == "실패"), 6)])
    r += 1
    row([("중요도", 1), ("건수", 1), ("미실행", 1)])
    for p in PRIORITIES:
        row([(p, 8), (sum(1 for c in cases if c.get("priority") == p), 6),
             (sum(1 for c in cases if c.get("priority") == p and c.get("status") == "미실행"), 6)])
    review = sum(1 for c in cases if c.get("needsReview"))
    r += 1
    row([("개발자 확인 필요", 8), (review, 6), ("근거가 불충분하여 검토가 필요한 케이스", 2)])
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<cols><col min="1" max="1" width="24" customWidth="1"/><col min="2" max="2" width="16" customWidth="1"/>'
            '<col min="3" max="3" width="40" customWidth="1"/></cols>'
            f'<sheetData>{"".join(rows)}</sheetData></worksheet>')


def build_xlsx(project, cases):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                   '</Relationships>')
        z.writestr("docProps/core.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                   'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                   'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                   f'<dc:title>{_x(project.get("name", ""))} 테스트 케이스</dc:title><dc:creator>Test Case Generator</dc:creator>'
                   f'<dcterms:created xsi:type="dcterms:W3CDTF">{datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</dcterms:created>'
                   '</cp:coreProperties>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets><sheet name="테스트케이스" sheetId="1" r:id="rId1"/><sheet name="요약" sheetId="2" r:id="rId2"/></sheets>'
                   '<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'
                   f"'테스트케이스'!$A$1:${_col(len(COLUMNS) - 1)}${max(len(cases) + 1, 2)}</definedName></definedNames>"
                   '</workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                   '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
                   '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   '</Relationships>')
        z.writestr("xl/styles.xml", STYLES)
        z.writestr("xl/worksheets/sheet1.xml", build_cases_sheet(cases))
        z.writestr("xl/worksheets/sheet2.xml", build_summary_sheet(project, cases))
    return buf.getvalue()
