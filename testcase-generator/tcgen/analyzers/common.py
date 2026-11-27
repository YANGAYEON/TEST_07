"""분석기 공통 유틸리티.

- Fact: 분석기가 생성하는 중간 결과(사실) 단위. 분석기와 테스트 생성기 사이의 계약이다.
  추후 로컬 LLM 분석기를 붙일 때도 동일한 Fact 형식을 반환하면 생성기를 그대로 재사용할 수 있다.
- 식별자(ID/컬럼명/변수명) → 한글 라벨 변환, 정규화 키 생성, 조사 처리 등.
"""
import re

# ---------------------------------------------------------------------------
# Fact / Source
# ---------------------------------------------------------------------------

def src(file_name, file_type, line=None, detail=""):
    """근거 자료 정보."""
    return {"file": file_name, "type": file_type, "line": line, "detail": (detail or "")[:200]}


def fact(kind, source, **data):
    d = {"kind": kind, "src": source}
    d.update(data)
    return d


class AnalysisResult:
    def __init__(self, file_name, file_type):
        self.file_name = file_name
        self.file_type = file_type
        self.facts = []
        self.warnings = []   # [{"file","line","message"}]
        self.summary = {}

    def add(self, f):
        self.facts.append(f)
        return f

    def warn(self, message, line=None):
        self.warnings.append({"file": self.file_name, "line": line, "message": message})

    def to_dict(self):
        return {"file": self.file_name, "type": self.file_type, "factCount": len(self.facts),
                "summary": self.summary, "warnings": self.warnings}


class AnalyzeError(Exception):
    """파일 단위 분석 실패 (파일명/위치 포함)."""

    def __init__(self, message, line=None, column=None):
        super().__init__(message)
        self.line = line
        self.column = column


# ---------------------------------------------------------------------------
# 약어 사전: 식별자 → 한글
# ---------------------------------------------------------------------------

ABBR = {
    "req": "신청", "request": "신청", "appl": "신청", "aply": "신청", "apply": "신청",
    "sts": "상태", "stat": "상태", "status": "상태", "state": "상태", "prgs": "진행",
    "cd": "코드", "code": "코드",
    "dt": "일자", "de": "일자", "date": "일자", "ymd": "일자", "dttm": "일시", "dtm": "일시", "ym": "년월",
    "st": "시작", "strt": "시작", "start": "시작", "from": "시작", "fr": "시작", "bgn": "시작", "beg": "시작",
    "end": "종료", "ed": "종료", "to": "종료", "fin": "종료",
    "nm": "명", "name": "명", "no": "번호", "nos": "번호목록", "ids": "ID목록", "num": "번호", "seq": "순번", "sn": "순번", "id": "ID",
    "user": "사용자", "usr": "사용자", "mbr": "회원", "cust": "고객",
    "submit": "제출", "sbmt": "제출", "sbmsn": "제출", "prsntn": "제출",
    "amt": "금액", "amount": "금액", "price": "가격", "cnt": "건수", "count": "건수", "qty": "수량",
    "tel": "전화번호", "phone": "전화번호", "mobile": "휴대폰", "email": "이메일", "addr": "주소",
    "rmk": "비고", "remark": "비고", "memo": "메모", "note": "비고", "desc": "설명",
    "yn": "여부", "type": "유형", "tp": "유형", "gb": "구분", "div": "구분", "se": "구분", "kind": "종류",
    "dept": "부서", "emp": "사원", "org": "기관", "inst": "기관", "corp": "법인", "biz": "사업",
    "reg": "등록", "regist": "등록", "ins": "등록", "insert": "등록", "mod": "수정", "upd": "수정",
    "update": "수정", "del": "삭제", "delete": "삭제", "aprv": "승인", "apprv": "승인", "rjct": "반려",
    "cncl": "취소", "cancel": "취소", "wthdr": "취하", "wdrw": "취하", "obj": "부인", "objc": "부인",
    "rsn": "사유", "reason": "사유", "file": "파일", "title": "제목", "ttl": "제목", "cont": "내용",
    "cn": "내용", "content": "내용", "search": "조회", "srch": "조회", "inq": "조회", "list": "목록",
    "save": "저장", "excel": "엑셀", "down": "다운로드", "prd": "기간", "period": "기간", "term": "기간",
    "yr": "연도", "year": "연도", "mm": "월", "mon": "월", "day": "일", "tm": "시간", "time": "시간",
    "trgt": "대상", "target": "대상", "tgt": "대상", "rslt": "결과", "result": "결과", "err": "오류",
    "msg": "메시지", "pwd": "비밀번호", "pw": "비밀번호", "use": "사용", "auth": "권한", "role": "역할",
    "grp": "그룹", "group": "그룹", "doc": "문서", "atch": "첨부", "attach": "첨부", "bat": "배치",
    "batch": "배치", "job": "작업", "proc": "처리", "chg": "변경", "rcpt": "접수", "rcv": "수신",
    "snd": "발송", "send": "발송", "pay": "지급", "tax": "세금", "rate": "비율", "sum": "합계",
    "tot": "합계", "total": "합계", "max": "최대", "min": "최소", "page": "페이지", "size": "크기",
    "lst": "최종", "last": "최종", "frst": "최초", "first": "최초", "info": "정보", "dtl": "상세",
    "detail": "상세", "hist": "이력", "history": "이력", "ver": "버전", "lang": "언어", "img": "이미지",
}

# WebSquare 컴포넌트 ID 접두어
COMPONENT_PREFIX = re.compile(
    r"^(ibx|ica|icl|sbx|sel|cbx|chk|ckb|rad|rdo|txa|tta|btn|trg|grd|gvw|tbx|txt|spn|udc|acb|cal|edt|inp|ipt|"
    r"dma|dlt|sbm|grp|wfm|tac|tab|anc|img|lbl|sec|scr|out)_", re.I)


def split_identifier(ident):
    s = COMPONENT_PREFIX.sub("", ident or "")
    s = re.sub(r"^[#:$@]+|[{}]", "", s)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return [t for t in re.split(r"[\s_.\-]+", s) if t]


def labelize(ident):
    """'reqStsCd' → '신청상태코드', 'ibx_startDt' → '시작일자'. 변환 불가 시 원문 반환."""
    if not ident:
        return ""
    if re.search(r"[가-힣]", ident):
        return ident.strip()
    tokens = split_identifier(ident)
    if not tokens:
        return ident
    out, mapped = [], 0
    for t in tokens:
        k = ABBR.get(t.lower())
        if k:
            out.append(k)
            mapped += 1
        else:
            out.append(t)
    if mapped == 0:
        return ident
    return "".join(out)


def canonical(label):
    """서로 다른 자료(요구사항/XML/SQL)에서 같은 항목을 인식하기 위한 정규화 키."""
    s = re.sub(r"\s+|\(.*?\)", "", label or "")
    s = s.replace("일자", "일").replace("날짜", "일").replace("일시", "일")
    s = re.sub(r"(코드|값|항목|여부)$", "", s)
    s = s.replace("기간시작일", "시작일").replace("기간종료일", "종료일")
    return s.lower()


# ---------------------------------------------------------------------------
# 항목 유형 추정
# ---------------------------------------------------------------------------

def guess_field_type(label, ident=""):
    lab = label or ""
    idl = (ident or "").lower()
    if re.search(r"(일|일자|날짜|일시|년월|연월|기간)$", lab) or re.search(r"(dt|date|ymd|dttm|de)$", idl):
        return "date"
    if re.search(r"(금액|수량|건수|횟수|나이|비율|율|점수|순번|합계)$", lab) or re.search(r"(amt|cnt|qty|rate|seq|sum)$", idl):
        return "number"
    if re.search(r"(상태|구분|유형|코드|종류|여부|등급)$", lab) or re.search(r"(cd|yn|gb|tp|type|sts)$", idl):
        return "code"
    return "text"


# ---------------------------------------------------------------------------
# 한국어 조사
# ---------------------------------------------------------------------------

def _has_batchim(word):
    if not word:
        return False
    w = re.sub(r"\s*\([^)]*\)$", "", word).rstrip("'\" ]") or word
    ch = w[-1]
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    return ch.lower() in "013678lmnr"


def josa(word, pair):
    """josa('시작일', '을/를') → '시작일을'"""
    a, b = pair.split("/")
    if pair == "으로/로" and word:
        ch = word[-1]
        if "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 == 8:
            return word + b
    return word + (a if _has_batchim(word) else b)


# ---------------------------------------------------------------------------
# 텍스트 디코딩 (인코딩 오류 처리)
# ---------------------------------------------------------------------------

def decode_bytes(data):
    """UTF-8(BOM) → CP949(EUC-KR) → UTF-16 순으로 시도. 실패 시 AnalyzeError."""
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        try:
            return data.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            pass
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc), enc.replace("-sig", "")
        except UnicodeDecodeError:
            continue
    raise AnalyzeError("파일 인코딩을 인식할 수 없습니다. UTF-8 또는 EUC-KR(CP949)로 저장해 주세요.")


def line_of(text, index):
    return text.count("\n", 0, index) + 1
