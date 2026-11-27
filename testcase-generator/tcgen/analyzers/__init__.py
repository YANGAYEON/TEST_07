"""분석 모듈 레지스트리.

각 분석기는 analyze(text, file_name, is_cancelled) → AnalysisResult 인터페이스를 따른다.
새 분석기(예: 로컬 LLM 기반)를 추가하려면 같은 인터페이스로 구현한 뒤 ANALYZERS 에 등록한다.
"""
import re

from .common import AnalyzeError, decode_bytes
from .requirement import RequirementAnalyzer
from .websquare import WebSquareAnalyzer
from .sql_analyzer import SqlAnalyzer
from .java_analyzer import JavaAnalyzer
from .excel_reader import read_xlsx_text

ANALYZERS = {
    "REQ": RequirementAnalyzer(),
    "XML": WebSquareAnalyzer(),
    "SQL": SqlAnalyzer(),
    "JAVA": JavaAnalyzer(),
}

TYPE_LABELS = {"REQ": "요구사항 텍스트", "EXCEL": "Excel 요구사항", "XML": "WebSquare5 XML",
               "MAPPER": "MyBatis Mapper(SQL)", "SQL": "SQL", "JAVA": "Java"}

SUPPORTED_EXT = {".txt", ".md", ".xlsx", ".xls", ".xml", ".sql", ".java"}


def detect_type(file_name, data):
    """파일명 + 내용으로 분석 유형 판별. 지원하지 않으면 None."""
    name = file_name.lower()
    ext = name[name.rfind("."):] if "." in name else ""
    if ext in (".txt", ".md"):
        return "REQ"
    if ext in (".xlsx", ".xls"):
        return "EXCEL"
    if ext == ".sql":
        return "SQL"
    if ext == ".java":
        return "JAVA"
    if ext == ".xml":
        head = data[:4000].decode("utf-8", "ignore")
        if re.search(r"<mapper\b|<sqlMap\b|mybatis|ibatis", head, re.I):
            return "MAPPER"
        return "XML"
    return None


def analyze_file(file_type, file_name, data, is_cancelled=lambda: False):
    """파일 바이트를 받아 유형별 분석기로 분석한다."""
    if file_type == "EXCEL":
        text, sheets = read_xlsx_text(data)
        if not text.strip():
            raise AnalyzeError("Excel 파일에서 요구사항 문장(한글 텍스트)을 찾지 못했습니다.")
        result = ANALYZERS["REQ"].analyze(text, file_name, is_cancelled)
        result.file_type = "EXCEL"
        result.summary["sheets"] = sheets
        return result
    text, enc = decode_bytes(data)
    key = "SQL" if file_type == "MAPPER" else file_type
    analyzer = ANALYZERS.get(key)
    if not analyzer:
        raise AnalyzeError(f"지원하지 않는 파일 형식입니다: {file_type}")
    result = analyzer.analyze(text, file_name, is_cancelled)
    result.summary["encoding"] = enc
    return result
