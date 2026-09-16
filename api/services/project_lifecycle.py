"""Project removal with server-owned targets and durable deletion recovery.

The catalog journal lives outside project directories. An interrupted purge can
therefore be retried without opening the (possibly already deleted) project DB.
"""
from __future__ import annotations
from contextlib import closing

import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import stat
import time
from typing import Any
from uuid import uuid4


class ProjectLifecycle:
    def __init__(self, store):
        self.store = store
        self._previews: dict[str, tuple[float, dict[str, Any]]] = {}
        self.active_projects = lambda: set()
        with store.catalog() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS project_deletions (
                project_id TEXT PRIMARY KEY, root_path TEXT NOT NULL,
                staging_path TEXT NOT NULL, identity_json TEXT NOT NULL,
                status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '')""")

    @staticmethod
    def fail(code: str, message: str, details=None):
        from api.services.workbench_store import WorkbenchError
        raise WorkbenchError(code, message, status_code=409, details=details)

    def journal(self, project_id: str):
        with self.store.catalog() as db:
            row = db.execute("SELECT * FROM project_deletions WHERE project_id=?", (project_id,)).fetchone()
        return dict(row) if row else None

    def assert_available(self, project_id: str):
        record = self.journal(project_id)
        if record:
            self.fail("project_deleting", "项目正在删除或等待重试，请返回项目列表处理。", record)

    @staticmethod
    def identity(root: Path):
        info = root.lstat()
        return {"device": info.st_dev, "inode": info.st_ino, "created_ns": info.st_ctime_ns}

    @staticmethod
    def is_link(path: Path):
        info = path.lstat()
        return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)

    def check_target(self, root: Path, project_id: str, *, retry=False):
        # Inspect before resolve(), so a junction cannot silently become a target.
        for path in [root, *root.parents]:
            if path.exists() and self.is_link(path):
                self.fail("project_unsafe_path", "目标路径包含链接或重解析点，禁止彻底删除。")
        resolved = root.resolve()
        repo = Path(__file__).resolve().parents[2]
        protected = [Path(root.anchor), Path.home(), repo, self.store.state_dir.resolve()]
        for name in ("USERPROFILE", "SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "LOCALAPPDATA", "APPDATA"):
            if os.environ.get(name):
                protected.append(Path(os.environ[name]).resolve())
        for path in protected:
            if resolved == path or resolved in path.parents:
                self.fail("project_unsafe_path", "目标是受保护目录或其祖先，禁止彻底删除。")
        forbidden_trees = [Path(os.environ.get("SystemRoot", "C:/Windows")).resolve(), self.store.state_dir.resolve()]
        forbidden_trees.extend(Path(os.environ[name]).resolve() for name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramData") if os.environ.get(name))
        if any(path in resolved.parents for path in forbidden_trees):
            self.fail("project_unsafe_path", "不能删除系统目录或共享状态目录中的项目。")
        with self.store.catalog() as db:
            others = db.execute("SELECT project_id, root_path FROM projects WHERE project_id<>?", (project_id,)).fetchall()
        for other in others:
            path = Path(other["root_path"]).resolve()
            if path == resolved or resolved in path.parents or path in resolved.parents:
                self.fail("project_nested", "目标与其他已登记项目存在包含关系，禁止彻底删除。")
        if not resolved.is_dir():
            self.fail("project_unavailable", "无法核验项目目录；可以从列表移除。")
        def walk_error(error):
            raise error
        for directory, dirs, files in os.walk(resolved, followlinks=False, onerror=walk_error):
            for name in dirs + files:
                path = Path(directory) / name
                if self.is_link(path):
                    self.fail("project_unsafe_link", "项目包含链接或重解析点，禁止彻底删除。", {"path": str(path)})
            if Path(directory) != resolved and ".taichi-flow" in dirs:
                self.fail("project_nested", "项目目录中包含另一个本地项目。")
        if not retry:
            database = resolved / ".taichi-flow" / "state.sqlite3"
            if not database.is_file():
                self.fail("project_identity_mismatch", "缺少项目身份文件，禁止彻底删除。")
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                row = db.execute("SELECT project_id FROM project_metadata WHERE singleton=1").fetchone()
            if not row or row[0] != project_id:
                self.fail("project_identity_mismatch", "磁盘项目身份与登记不一致。")
        return resolved

    def inspect(self, project_id: str, mode: str):
        project = self.store.get_project(project_id)
        record = self.journal(project_id)
        root = Path(project["root_path"])
        result = {"project_id": project_id, "name": project["name"], "root_path": str(root.resolve()),
                  "mode": mode, "scenario_count": 0, "run_count": 0,
                  "staging_path": record["staging_path"] if record else None,
                  "last_error": record["error"] if record else None,
                  "blocked_reasons": [], "retry": bool(record), "identity": None}
        try:
            if project_id in self.active_projects():
                self.fail("project_busy", "项目仍有活动任务，请等待停止完成后再操作。")
            if record:
                if mode != "permanent":
                    self.fail("project_delete_pending", "存在未完成的彻底删除，请重试以完成清理。")
                staged = Path(record["staging_path"])
                candidate = staged if staged.exists() else root
                if candidate.exists():
                    self.check_target(candidate, project_id, retry=True)
                    identity = self.identity(candidate)
                    expected = json.loads(record["identity_json"])
                    if (identity["device"], identity["inode"]) != (expected["device"], expected["inode"]):
                        self.fail("project_identity_mismatch", "删除目标身份已改变，不能重试。")
                result["identity"] = json.loads(record["identity_json"])
                return result
            if mode == "permanent":
                root = self.check_target(root, project_id)
                result["identity"] = self.identity(root)
            database = root / ".taichi-flow" / "state.sqlite3"
            if database.exists():
                with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                    result["scenario_count"] = db.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0]
                    result["run_count"] = db.execute("SELECT COUNT(*) FROM simulation_runs").fetchone()[0]
                    queued = db.execute("SELECT COUNT(*) FROM queue_items WHERE status IN ('queued','waiting','starting','running','stopping')").fetchone()[0]
                    running = db.execute("SELECT COUNT(*) FROM simulation_runs WHERE status IN ('starting','running','stopping')").fetchone()[0]
                    exporting = db.execute("SELECT COUNT(*) FROM export_jobs WHERE status IN ('queued','pending','running','building')").fetchone()[0]
                    if queued or running or exporting:
                        self.fail("project_busy", "项目有等待、运行或导出任务；请先处理队列后再操作。")
        except Exception as error:
            result["blocked_reasons"].append(str(error))
        return result

    def preview(self, project_id: str, mode: str):
        if mode not in {"unregister", "permanent"}:
            self.fail("project_delete_mode", "无效的项目操作。")
        result = self.inspect(project_id, mode)
        now = time.monotonic()
        self._previews = {key: item for key, item in self._previews.items() if item[0] > now}
        token = secrets.token_urlsafe(32)
        self._previews[token] = (now + 600, result.copy())
        return {**result, "confirmation_token": token, "allowed": not result["blocked_reasons"]}

    def execute(self, project_id: str, mode: str, token: str, confirmed_name: str):
        item = self._previews.pop(token, None)
        if not item or item[0] < time.monotonic():
            self.fail("project_delete_preview_expired", "确认已过期，请重新预览。")
        expected = item[1]
        if expected["project_id"] != project_id or expected["mode"] != mode:
            self.fail("project_delete_target_mismatch", "确认凭据不属于当前操作。")
        current = self.inspect(project_id, mode)
        if current["blocked_reasons"]:
            self.fail("project_delete_blocked", "；".join(current["blocked_reasons"]))
        for key in ("root_path", "name", "identity", "retry"):
            if current[key] != expected[key]:
                self.fail("project_delete_target_changed", "项目在预览后发生变化，请重新确认。")
        if mode == "unregister":
            with self.store.catalog() as db:
                db.execute("DELETE FROM projects WHERE project_id=?", (project_id,))
            return {"project_id": project_id, "mode": mode, "deleted": True}
        if confirmed_name != current["name"]:
            self.fail("project_delete_name_mismatch", "请输入完整项目名称确认彻底删除。")
        root = Path(current["root_path"])
        record = self.journal(project_id)
        staging = Path(record["staging_path"]) if record else root.parent / f".{root.name}.taichi-delete-{uuid4().hex}"
        if not record:
            with self.store.catalog() as db:
                db.execute("INSERT INTO project_deletions VALUES(?,?,?,?,?,?)", (
                    project_id, str(root), str(staging), json.dumps(current["identity"]), "deleting", ""))
        try:
            if not staging.exists() and root.exists():
                self.check_target(root, project_id)
                root.rename(staging)
            if staging.exists():
                self.check_target(staging, project_id, retry=True)
                # A retry never traverses the original path if it was replaced.
                identity = self.identity(staging)
                expected_identity = current["identity"]
                if (identity["device"], identity["inode"]) != (expected_identity["device"], expected_identity["inode"]):
                    self.fail("project_identity_mismatch", "暂存目录身份不匹配。")
                shutil.rmtree(staging)
            with self.store.catalog() as db:
                db.execute("DELETE FROM projects WHERE project_id=?", (project_id,))
                db.execute("DELETE FROM project_deletions WHERE project_id=?", (project_id,))
            return {"project_id": project_id, "mode": mode, "deleted": True}
        except Exception as error:
            with self.store.catalog() as db:
                db.execute("UPDATE project_deletions SET status='failed', error=? WHERE project_id=?", (str(error), project_id))
            self.fail("project_delete_failed", "删除未完成，记录已保留。解除文件占用后可重试彻底删除。", {"error": str(error), "staging_path": str(staging)})
