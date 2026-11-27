"""분석 작업 관리 — 백그라운드 스레드에서 실행, 진행률/취소/오류 수집.

입력 : 프로젝트 ID
처리 : 요구사항 텍스트 + 활성화된 파일 → 분석기 → 테스트 케이스 생성 → 기존 케이스와 병합 → 저장
출력 : 작업 상태 {status, progress, step, logs[], errors[], stats}
  - 파일 하나의 분석 오류는 해당 파일만 실패 처리하고 나머지는 계속 진행한다.
  - 취소 시 프로젝트는 변경되지 않는다.
"""
import logging
import threading
import time
import traceback
import uuid

from .analyzers import analyze_file, ANALYZERS, TYPE_LABELS
from .analyzers.common import AnalyzeError
from .generator import generate, merge_cases
from .storage import now

log = logging.getLogger("tcgen")
MAX_ANALYZE_BYTES = 5 * 1024 * 1024


class Cancelled(Exception):
    pass


class JobManager:
    def __init__(self, store):
        self.store = store
        self.jobs = {}
        self._lock = threading.Lock()

    def running_for(self, pid):
        return next((j for j in self.jobs.values() if j["projectId"] == pid and j["status"] in ("queued", "running")), None)

    def start(self, pid):
        self.store.get(pid)  # 존재 확인
        with self._lock:
            if self.running_for(pid):
                raise ValueError("이미 분석이 진행 중입니다.")
            jid = uuid.uuid4().hex[:12]
            job = {"id": jid, "projectId": pid, "status": "queued", "progress": 0, "step": "대기 중",
                   "logs": [], "errors": [], "warnings": [], "stats": None, "startedAt": now(), "finishedAt": None,
                   "_cancel": threading.Event()}
            self.jobs[jid] = job
        t = threading.Thread(target=self._run, args=(job,), daemon=True)
        t.start()
        return self.public(job)

    def cancel(self, jid):
        job = self.jobs.get(jid)
        if not job:
            raise KeyError("작업을 찾을 수 없습니다.")
        if job["status"] in ("queued", "running"):
            job["_cancel"].set()
            job["step"] = "취소 요청됨…"
        return self.public(job)

    def get(self, jid):
        job = self.jobs.get(jid)
        if not job:
            raise KeyError("작업을 찾을 수 없습니다.")
        return self.public(job)

    @staticmethod
    def public(job):
        return {k: v for k, v in job.items() if not k.startswith("_")}

    # ------------------------------------------------------------------
    def _run(self, job):
        cancelled = job["_cancel"].is_set
        t0 = time.time()

        def logline(msg):
            job["logs"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")

        def check():
            if cancelled():
                raise Cancelled()

        try:
            job["status"] = "running"
            project = self.store.get(job["projectId"])
            sources = []
            if (project.get("requirementText") or "").strip():
                sources.append(("REQ_TEXT", "요구사항(직접 입력)", None))
            for f in project.get("files", []):
                if f.get("enabled", True):
                    sources.append((f["type"], f["name"], f))
            if not sources:
                raise AnalyzeError("분석할 자료가 없습니다. 요구사항을 입력하거나 파일을 업로드한 뒤 분석 대상으로 선택해 주세요.")
            total = len(sources) + 2
            results, file_reports = [], []
            for i, (ftype, name, meta) in enumerate(sources):
                check()
                job["progress"] = int(i / total * 100)
                job["step"] = f"분석 중: {name}"
                logline(f"{name} ({TYPE_LABELS.get(ftype, '요구사항')}) 분석 시작")
                try:
                    if ftype == "REQ_TEXT":
                        r = ANALYZERS["REQ"].analyze(project["requirementText"], name, cancelled)
                    else:
                        data = self.store.read_file(project["id"], meta["id"])
                        if len(data) > MAX_ANALYZE_BYTES:
                            raise AnalyzeError(f"파일이 너무 큽니다 ({len(data) // 1024:,}KB). "
                                               f"{MAX_ANALYZE_BYTES // 1024 // 1024}MB 이하로 분할해 주세요.")
                        r = analyze_file(ftype, name, data, cancelled)
                    check()
                    results.append(r)
                    job["warnings"].extend(r.warnings)
                    file_reports.append({"file": name, "type": ftype, "ok": True, "facts": len(r.facts),
                                         "summary": r.summary, "warnings": r.warnings})
                    logline(f"{name}: 분석 요소 {len(r.facts)}건 추출" + (f", 경고 {len(r.warnings)}건" if r.warnings else ""))
                except Cancelled:
                    raise
                except AnalyzeError as e:
                    err = {"file": name, "line": e.line, "column": e.column, "message": str(e)}
                    job["errors"].append(err)
                    file_reports.append({"file": name, "type": ftype, "ok": False, "error": err})
                    logline(f"{name}: 오류 — {e}" + (f" (라인 {e.line})" if e.line else ""))
                except Exception as e:  # 예상치 못한 분석기 오류도 파일 단위로 격리
                    log.error("analyze failed: %s (%s)", name, type(e).__name__)
                    log.debug(traceback.format_exc())
                    err = {"file": name, "line": None, "column": None, "message": f"분석 중 내부 오류: {type(e).__name__}: {e}"}
                    job["errors"].append(err)
                    file_reports.append({"file": name, "type": ftype, "ok": False, "error": err})
                    logline(f"{name}: 내부 오류 — {e}")

            if not results:
                raise AnalyzeError("모든 자료의 분석에 실패했습니다. 오류 내용을 확인해 주세요.")
            check()
            job["progress"] = int((total - 2) / total * 100)
            job["step"] = "테스트 케이스 생성 중"
            changed = [f["name"] for _, _, f in sources if f and f.get("analyzedHash") and f["analyzedHash"] != f["hash"]]
            generated, ctx_summary = generate(results, project.get("name", ""), changed)
            logline(f"테스트 케이스 초안 {len(generated)}건 생성 (중복 제거 후)")
            check()
            job["step"] = "기존 테스트 케이스와 병합 중"
            job["progress"] = int((total - 1) / total * 100)
            with self.store.lock():
                project = self.store.get(job["projectId"])   # 분석 중 편집 내용 반영을 위해 다시 읽음
                check()
                merged, stats = merge_cases(project.get("testCases", []), generated)
                project["testCases"] = merged
                analyzed = {name for (_, name, _f), rep in zip(sources, file_reports) if rep.get("ok")}
                for f in project.get("files", []):
                    if f["name"] in analyzed:
                        f["analyzedHash"] = f["hash"]
                project["analysis"] = {"lastRunAt": now(), "durationSec": round(time.time() - t0, 2),
                                       "generated": len(generated), "stats": stats, "files": file_reports,
                                       "errors": job["errors"], "warnings": job["warnings"][:200],
                                       "context": ctx_summary}
                self.store.save(project)
            stats["generated"] = len(generated)
            stats["total"] = len(merged)
            job["stats"] = stats
            logline(f"병합 완료 — 신규 {stats['added']}, 갱신 {stats['updated']}, 수정 보존 {stats['kept']}, "
                    f"삭제 {stats['removed']}, 근거 소실 {stats['stale']}")
            job["status"] = "done"
            job["step"] = "완료"
            job["progress"] = 100
            log.info("analysis done project=%s files=%d cases=%d", job["projectId"], len(sources), len(merged))
        except Cancelled:
            job["status"] = "cancelled"
            job["step"] = "취소됨 — 프로젝트는 변경되지 않았습니다."
            logline("사용자가 분석을 취소했습니다.")
        except AnalyzeError as e:
            job["status"] = "error"
            job["step"] = str(e)
            job["errors"].append({"file": None, "line": None, "column": None, "message": str(e)})
            logline(f"오류: {e}")
        except Exception as e:
            log.error("job failed: %s", type(e).__name__)
            log.debug(traceback.format_exc())
            job["status"] = "error"
            job["step"] = f"분석 중 오류가 발생했습니다: {e}"
            job["errors"].append({"file": None, "line": None, "column": None, "message": str(e)})
        finally:
            job["finishedAt"] = now()
