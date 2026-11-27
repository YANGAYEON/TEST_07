"""로컬 웹 서버 (표준 라이브러리 http.server) — REST API + 정적 파일 제공.

기본 바인딩은 127.0.0.1 (사용자 PC 내부에서만 접속 가능). 외부로 어떤 요청도 보내지 않는다.
"""
import base64
import json
import logging
import mimetypes
import os
import re
import traceback
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

from .analyzers import detect_type, TYPE_LABELS, SUPPORTED_EXT
from .analyzers.common import decode_bytes, AnalyzeError
from .excel_writer import build_xlsx
from .generator import CATEGORIES, STATUSES, PRIORITIES, next_test_id
from .generator.merge import blank_case, CONTENT_FIELDS, RESULT_FIELDS, now
from .jobs import JobManager
from .storage import ProjectStore, StorageError

log = logging.getLogger("tcgen")
MAX_BODY = 80 * 1024 * 1024
MAX_FILE = 20 * 1024 * 1024
EDITABLE = CONTENT_FIELDS + RESULT_FIELDS + ["testId"]


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class App:
    def __init__(self, data_dir, static_dir, samples_dir=None):
        self.samples_dir = samples_dir
        self.store = ProjectStore(data_dir)
        self.jobs = JobManager(self.store)
        self.static_dir = static_dir
        self.routes = []
        r = self.route
        r("GET", r"/api/meta", self.meta)
        r("GET", r"/api/projects", lambda h, q, b: self.store.list())
        r("POST", r"/api/projects", self.create_project)
        r("GET", r"/api/projects/(\w+)", lambda h, q, b, pid: self.store.get(pid))
        r("PUT", r"/api/projects/(\w+)", self.update_project)
        r("DELETE", r"/api/projects/(\w+)", self.delete_project)
        r("POST", r"/api/projects/(\w+)/files", self.upload_files)
        r("PATCH", r"/api/projects/(\w+)/files/(\w+)", self.patch_file)
        r("DELETE", r"/api/projects/(\w+)/files/(\w+)", self.delete_file)
        r("GET", r"/api/projects/(\w+)/files/(\w+)", self.preview_file)
        r("POST", r"/api/projects/(\w+)/analyze", lambda h, q, b, pid: self.jobs.start(pid))
        r("GET", r"/api/jobs/(\w+)", lambda h, q, b, jid: self.jobs.get(jid))
        r("POST", r"/api/jobs/(\w+)/cancel", lambda h, q, b, jid: self.jobs.cancel(jid))
        r("POST", r"/api/projects/(\w+)/testcases", self.add_case)
        r("POST", r"/api/projects/(\w+)/testcases/bulk", self.bulk_cases)
        r("PUT", r"/api/projects/(\w+)/testcases/(\w+)", self.update_case)
        r("DELETE", r"/api/projects/(\w+)/testcases/(\w+)", self.delete_case)
        r("POST", r"/api/projects/(\w+)/testcases/(\w+)/copy", self.copy_case)
        r("GET", r"/api/projects/(\w+)/export\.xlsx", self.export)
        r("GET", r"/api/samples", self.list_samples)
        r("POST", r"/api/projects/(\w+)/samples", self.load_samples)

    def route(self, method, pattern, fn):
        self.routes.append((method, re.compile("^" + pattern + "$"), fn))

    # ------------------------------------------------------------------ helpers
    def _mutate(self, pid, fn):
        with self.store.lock():
            p = self.store.get(pid)
            res = fn(p)
            self.store.save(p)
            return res

    @staticmethod
    def _find_case(p, uid):
        c = next((c for c in p["testCases"] if c["uid"] == uid), None)
        if not c:
            raise ApiError("테스트 케이스를 찾을 수 없습니다.", 404)
        return c

    @staticmethod
    def _check_id(p, test_id, uid=None):
        test_id = (test_id or "").strip()
        if not test_id:
            raise ApiError("테스트 ID를 입력해 주세요.")
        if any(c["testId"] == test_id and c["uid"] != uid for c in p["testCases"]):
            raise ApiError(f"테스트 ID '{test_id}'가 이미 존재합니다. 다른 ID를 입력해 주세요.", 409)
        return test_id

    @staticmethod
    def _clean(fields):
        out = {}
        for k in EDITABLE:
            if k in fields:
                v = fields[k]
                out[k] = "" if v is None else str(v)[:20000]
        if "category" in out and out["category"] not in CATEGORIES:
            raise ApiError("알 수 없는 테스트 분류입니다.")
        if "status" in out and out["status"] not in STATUSES:
            raise ApiError("알 수 없는 테스트 상태입니다.")
        if "priority" in out and out["priority"] not in PRIORITIES:
            raise ApiError("알 수 없는 중요도입니다.")
        return out

    # ------------------------------------------------------------------ handlers
    def meta(self, h, q, b):
        return {"categories": CATEGORIES, "statuses": STATUSES, "priorities": PRIORITIES,
                "supported": sorted(SUPPORTED_EXT), "typeLabels": TYPE_LABELS, "version": "1.0.0"}

    def create_project(self, h, q, b):
        return self.store.create(b.get("name"), b.get("description", ""))

    def update_project(self, h, q, b, pid):
        def fn(p):
            if "name" in b:
                name = (b["name"] or "").strip()
                if not name:
                    raise ApiError("프로젝트명을 입력해 주세요.")
                if any(x["name"] == name and x["id"] != pid for x in self.store.list()):
                    raise ApiError(f"같은 이름의 프로젝트가 이미 있습니다: {name}", 409)
                p["name"] = name[:100]
            if "description" in b:
                p["description"] = (b["description"] or "")[:2000]
            if "requirementText" in b:
                p["requirementText"] = (b["requirementText"] or "")[:500000]
            return p
        return self._mutate(pid, fn)

    def delete_project(self, h, q, b, pid):
        if self.jobs.running_for(pid):
            raise ApiError("분석이 진행 중인 프로젝트는 삭제할 수 없습니다.", 409)
        self.store.delete(pid)
        return {"deleted": pid}

    def upload_files(self, h, q, b, pid):
        files = b.get("files") or []
        if not files:
            raise ApiError("업로드할 파일을 선택해 주세요.")
        added, rejected = [], []

        def fn(p):
            for f in files:
                name = os.path.basename((f.get("name") or "").replace("\\", "/"))[:200]
                try:
                    data = base64.b64decode(f.get("content") or "", validate=False)
                except (ValueError, TypeError):
                    rejected.append({"name": name, "reason": "파일 데이터를 읽을 수 없습니다."})
                    continue
                ext = name.lower()[name.rfind("."):] if "." in name else ""
                if ext not in SUPPORTED_EXT:
                    rejected.append({"name": name, "reason": f"지원하지 않는 파일 형식입니다 ({ext or '확장자 없음'}). 지원: {', '.join(sorted(SUPPORTED_EXT))}"})
                    continue
                if len(data) > MAX_FILE:
                    rejected.append({"name": name, "reason": f"파일 크기가 {MAX_FILE // 1024 // 1024}MB를 초과합니다."})
                    continue
                if not data:
                    rejected.append({"name": name, "reason": "빈 파일입니다."})
                    continue
                ftype = detect_type(name, data)
                meta, replaced = self.store.add_file(p, name, data, ftype, TYPE_LABELS.get(ftype, ftype))
                added.append(dict(meta, replaced=replaced))
            return {"added": added, "rejected": rejected, "files": p["files"]}
        return self._mutate(pid, fn)

    def patch_file(self, h, q, b, pid, fid):
        def fn(p):
            f = next((x for x in p["files"] if x["id"] == fid), None)
            if not f:
                raise ApiError("파일을 찾을 수 없습니다.", 404)
            if "enabled" in b:
                f["enabled"] = bool(b["enabled"])
            return f
        return self._mutate(pid, fn)

    def delete_file(self, h, q, b, pid, fid):
        return self._mutate(pid, lambda p: (self.store.remove_file(p, fid), {"files": p["files"]})[1])

    def preview_file(self, h, q, b, pid, fid):
        p = self.store.get(pid)
        f = next((x for x in p["files"] if x["id"] == fid), None)
        if not f:
            raise ApiError("파일을 찾을 수 없습니다.", 404)
        data = self.store.read_file(pid, fid)
        if f["type"] == "EXCEL":
            from .analyzers.excel_reader import read_xlsx_text
            try:
                text, _ = read_xlsx_text(data)
                enc = "xlsx"
            except AnalyzeError as e:
                return {"name": f["name"], "text": "", "error": str(e)}
        else:
            try:
                text, enc = decode_bytes(data)
            except AnalyzeError as e:
                return {"name": f["name"], "text": "", "error": str(e)}
        limit = 200000
        return {"name": f["name"], "encoding": enc, "truncated": len(text) > limit, "text": text[:limit]}

    def add_case(self, h, q, b, pid):
        def fn(p):
            fields = self._clean(b)
            tid = self._check_id(p, fields.get("testId") or next_test_id(p["testCases"]))
            fields["testId"] = tid
            c = blank_case(**fields)
            c["sourceText"] = "[수동 작성]"
            if c["status"] in ("성공", "실패") and not c["executedAt"]:
                c["executedAt"] = datetime.now().strftime("%Y-%m-%d")
            p["testCases"].append(c)
            return c
        return self._mutate(pid, fn)

    def update_case(self, h, q, b, pid, uid):
        def fn(p):
            c = self._find_case(p, uid)
            fields = self._clean(b)
            if "testId" in fields:
                fields["testId"] = self._check_id(p, fields["testId"], uid)
            changed = [k for k in CONTENT_FIELDS if k in fields and fields[k] != (c.get(k) or "")]
            if changed and c.get("origin") == "auto":
                c["modified"] = True
                c["modifiedFields"] = sorted(set(c.get("modifiedFields", [])) | set(changed))
            if b.get("resolveReview"):
                c["needsReview"] = False
            c.update(fields)
            if fields.get("status") in ("성공", "실패") and not c.get("executedAt"):
                c["executedAt"] = datetime.now().strftime("%Y-%m-%d")
            if fields.get("status") == "미실행":
                c["executedAt"] = fields.get("executedAt", "")
            c["updatedAt"] = now()
            return c
        return self._mutate(pid, fn)

    def delete_case(self, h, q, b, pid, uid):
        def fn(p):
            self._find_case(p, uid)
            p["testCases"] = [c for c in p["testCases"] if c["uid"] != uid]
            return {"deleted": uid}
        return self._mutate(pid, fn)

    def copy_case(self, h, q, b, pid, uid):
        def fn(p):
            src = self._find_case(p, uid)
            c = blank_case(**{k: src.get(k, "") for k in CONTENT_FIELDS})
            c["testId"] = next_test_id(p["testCases"])
            c["scenario"] = (src.get("scenario") or "") + " (복사)"
            c["sourceText"] = f"[{src['testId']} 에서 복사]\n" + (src.get("sourceText") or "")
            idx = p["testCases"].index(src)
            p["testCases"].insert(idx + 1, c)
            return c
        return self._mutate(pid, fn)

    def bulk_cases(self, h, q, b, pid):
        action, uids, value = b.get("action"), set(b.get("uids") or []), b.get("value")
        if not uids:
            raise ApiError("선택된 테스트 케이스가 없습니다.")

        def fn(p):
            n = 0
            if action == "delete":
                before = len(p["testCases"])
                p["testCases"] = [c for c in p["testCases"] if c["uid"] not in uids]
                n = before - len(p["testCases"])
            elif action in ("status", "priority", "category"):
                allowed = {"status": STATUSES, "priority": PRIORITIES, "category": CATEGORIES}[action]
                if value not in allowed:
                    raise ApiError("잘못된 값입니다.")
                for c in p["testCases"]:
                    if c["uid"] in uids:
                        if action != "status" and c.get("origin") == "auto" and c.get(action) != value:
                            c["modified"] = True
                            c["modifiedFields"] = sorted(set(c.get("modifiedFields", [])) | {action})
                        c[action] = value
                        if action == "status" and value in ("성공", "실패") and not c.get("executedAt"):
                            c["executedAt"] = datetime.now().strftime("%Y-%m-%d")
                        c["updatedAt"] = now()
                        n += 1
            elif action == "tester":
                for c in p["testCases"]:
                    if c["uid"] in uids:
                        c["tester"] = str(value or "")[:50]
                        n += 1
            else:
                raise ApiError("알 수 없는 작업입니다.")
            return {"affected": n}
        return self._mutate(pid, fn)

    def _sample_files(self):
        d = self.samples_dir
        if not d or not os.path.isdir(d):
            return []
        return sorted(f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))
                      and os.path.splitext(f)[1].lower() in SUPPORTED_EXT)

    def list_samples(self, h, q, b):
        return self._sample_files()

    def load_samples(self, h, q, b, pid):
        names = self._sample_files()
        if not names:
            raise ApiError("샘플 파일이 없습니다.", 404)
        files = []
        for n in names:
            with open(os.path.join(self.samples_dir, n), "rb") as f:
                files.append({"name": n, "content": base64.b64encode(f.read()).decode("ascii")})
        return self.upload_files(h, q, {"files": files}, pid)

    def export(self, h, q, b, pid):
        p = self.store.get(pid)
        cases = p["testCases"]
        if q.get("uids"):
            want = set(q["uids"][0].split(","))
            cases = [c for c in cases if c["uid"] in want]
        if q.get("status"):
            cases = [c for c in cases if c.get("status") == q["status"][0]]
        try:
            data = build_xlsx(p, cases)
        except Exception as e:
            log.error("excel export failed: %s", type(e).__name__)
            raise ApiError(f"Excel 파일 생성 중 오류가 발생했습니다: {e}", 500)
        safe = re.sub(r'[\\/:*?"<>|]', "_", p["name"])
        fname = f"테스트케이스_{safe}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        return RawResponse(data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"})


class RawResponse:
    def __init__(self, body, ctype, headers=None):
        self.body, self.ctype, self.headers = body, ctype, headers or {}


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TCGen/1.0"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # 요청 로그에 본문(업무 데이터)을 남기지 않음
            log.debug("%s %s", self.command, self.path.split("?")[0])

        def _send(self, status, body, ctype="application/json; charset=utf-8", headers=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _dispatch(self):
            url = urlparse(self.path)
            path = url.path
            if not path.startswith("/api/"):
                return self._static(path)
            body = {}
            if self.command in ("POST", "PUT", "PATCH"):
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    return self._send(413, {"ok": False, "error": "요청 크기가 너무 큽니다."})
                raw = self.rfile.read(length) if length else b""
                if raw:
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except ValueError:
                        return self._send(400, {"ok": False, "error": "잘못된 요청 형식입니다."})
            q = parse_qs(url.query)
            for method, rx, fn in app.routes:
                if method != self.command:
                    continue
                m = rx.match(path)
                if not m:
                    continue
                try:
                    res = fn(self, q, body, *m.groups())
                    if isinstance(res, RawResponse):
                        return self._send(200, res.body, res.ctype, res.headers)
                    return self._send(200, {"ok": True, "data": res})
                except ApiError as e:
                    return self._send(e.status, {"ok": False, "error": str(e)})
                except StorageError as e:
                    return self._send(404 if "찾을 수 없" in str(e) else 400, {"ok": False, "error": str(e)})
                except (KeyError, ValueError) as e:
                    msg = e.args[0] if e.args else str(e)
                    return self._send(409 if "진행 중" in str(msg) else 404, {"ok": False, "error": str(msg)})
                except Exception as e:
                    log.error("unhandled %s %s: %s", self.command, path, type(e).__name__)
                    log.debug(traceback.format_exc())
                    return self._send(500, {"ok": False, "error": f"처리 중 오류가 발생했습니다: {type(e).__name__}"})
            return self._send(404, {"ok": False, "error": "요청한 API를 찾을 수 없습니다."})

        def _static(self, path):
            if path in ("", "/"):
                path = "/index.html"
            full = os.path.normpath(os.path.join(app.static_dir, path.lstrip("/")))
            if not full.startswith(os.path.normpath(app.static_dir)) or not os.path.isfile(full):
                return self._send(404, "Not Found", "text/plain; charset=utf-8")
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            with open(full, "rb") as f:
                self._send(200, f.read(), ctype)

        def do_GET(self):
            self._dispatch()

        def do_HEAD(self):
            self._dispatch()

        def do_POST(self):
            self._dispatch()

        def do_PUT(self):
            self._dispatch()

        def do_PATCH(self):
            self._dispatch()

        def do_DELETE(self):
            self._dispatch()

    return Handler


def serve(host, port, data_dir, static_dir, samples_dir=None):
    app = App(data_dir, static_dir, samples_dir)
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    httpd.daemon_threads = True
    return httpd
