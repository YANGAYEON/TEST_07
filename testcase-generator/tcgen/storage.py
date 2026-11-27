"""프로젝트 저장소 — 로컬 JSON 파일.

data/projects/<id>.json          프로젝트 메타 + 테스트 케이스 + 분석 이력
data/projects/<id>/files/<fid>   업로드된 분석 자료 사본 (원본 파일은 읽기만 하고 수정하지 않음)

저장은 임시 파일에 쓴 뒤 os.replace 로 교체(원자적)하여 저장 중 오류/종료 시 기존 파일을 보호한다.
"""
import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime


class StorageError(Exception):
    pass


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class ProjectStore:
    def __init__(self, data_dir):
        self.root = os.path.join(data_dir, "projects")
        os.makedirs(self.root, exist_ok=True)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ paths
    def _json(self, pid):
        if not re.fullmatch(r"[a-f0-9]{8,32}", pid or ""):
            raise StorageError("잘못된 프로젝트 ID 입니다.")
        return os.path.join(self.root, f"{pid}.json")

    def _files_dir(self, pid):
        return os.path.join(self.root, pid, "files")

    # ------------------------------------------------------------------ basic
    def lock(self):
        return self._lock

    def list(self):
        out = []
        for fn in os.listdir(self.root):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.root, fn), encoding="utf-8") as f:
                    p = json.load(f)
            except (OSError, ValueError):
                continue
            cases = p.get("testCases", [])
            out.append({"id": p["id"], "name": p.get("name", ""), "description": p.get("description", ""),
                        "createdAt": p.get("createdAt"), "updatedAt": p.get("updatedAt"),
                        "caseCount": len(cases), "fileCount": len(p.get("files", [])),
                        "failCount": sum(1 for c in cases if c.get("status") == "실패"),
                        "passCount": sum(1 for c in cases if c.get("status") == "성공")})
        out.sort(key=lambda x: x.get("updatedAt") or "", reverse=True)
        return out

    def get(self, pid):
        path = self._json(pid)
        if not os.path.exists(path):
            raise StorageError("프로젝트를 찾을 수 없습니다.")
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except ValueError as e:
            raise StorageError(f"프로젝트 파일이 손상되었습니다: {e}")

    def save(self, project, touch=True):
        if touch:
            project["updatedAt"] = now()
        path = self._json(project["id"])
        tmp = f"{path}.{uuid.uuid4().hex[:6]}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(project, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        except OSError as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise StorageError(f"저장 중 오류가 발생했습니다: {e}")
        return project

    def create(self, name, description=""):
        name = (name or "").strip()
        if not name:
            raise StorageError("프로젝트명을 입력해 주세요.")
        if len(name) > 100:
            raise StorageError("프로젝트명은 100자 이내로 입력해 주세요.")
        with self._lock:
            if any(p["name"] == name for p in self.list()):
                raise StorageError(f"같은 이름의 프로젝트가 이미 있습니다: {name}")
            p = {"id": uuid.uuid4().hex[:16], "name": name, "description": (description or "").strip(),
                 "createdAt": now(), "updatedAt": now(), "requirementText": "", "files": [],
                 "testCases": [], "analysis": None, "version": 1}
            return self.save(p)

    def delete(self, pid):
        with self._lock:
            path = self._json(pid)
            if not os.path.exists(path):
                raise StorageError("프로젝트를 찾을 수 없습니다.")
            os.remove(path)
            shutil.rmtree(os.path.join(self.root, pid), ignore_errors=True)

    # ------------------------------------------------------------------ files
    def add_file(self, project, name, data, file_type, type_label):
        d = self._files_dir(project["id"])
        os.makedirs(d, exist_ok=True)
        digest = hashlib.sha256(data).hexdigest()[:16]
        existing = next((f for f in project["files"] if f["name"] == name), None)
        if existing:
            fid = existing["id"]
        else:
            fid = uuid.uuid4().hex[:12]
        with open(os.path.join(d, fid), "wb") as f:
            f.write(data)
        meta = {"id": fid, "name": name, "type": file_type, "typeLabel": type_label, "size": len(data),
                "hash": digest, "uploadedAt": now(), "enabled": True}
        if existing:
            meta["enabled"] = existing.get("enabled", True)
            meta["analyzedHash"] = existing.get("analyzedHash")
            existing.clear()
            existing.update(meta)
            return existing, True
        project["files"].append(meta)
        return meta, False

    def read_file(self, pid, fid):
        path = os.path.join(self._files_dir(pid), fid)
        if not re.fullmatch(r"[a-f0-9]{12}", fid or "") or not os.path.exists(path):
            raise StorageError("파일을 찾을 수 없습니다.")
        with open(path, "rb") as f:
            return f.read()

    def remove_file(self, project, fid):
        project["files"] = [f for f in project["files"] if f["id"] != fid]
        try:
            os.remove(os.path.join(self._files_dir(project["id"]), fid))
        except OSError:
            pass
