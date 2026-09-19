from pathlib import Path
import shutil
import threading
import pytest
from api.services.workbench_store import WorkbenchStore, WorkbenchError


@pytest.fixture
def project(tmp_path):
    store = WorkbenchStore(tmp_path / "state")
    root = tmp_path / "disposable"
    info = store.create_or_open_project(name="Disposable", root_path=str(root))
    return store, root, info["project_id"]


def execute(store, pid, mode, name="Disposable"):
    preview = store.project_lifecycle.preview(pid, mode)
    assert preview["allowed"], preview
    return store.project_lifecycle.execute(pid, mode, preview["confirmation_token"], name)


def test_unregister_and_reopen(project):
    store, root, pid = project
    execute(store, pid, "unregister")
    assert root.is_dir() and store.list_projects() == []
    assert store.create_or_open_project(name="Disposable", root_path=str(root))["project_id"] == pid


def test_unregister_missing_directory(project):
    store, root, pid = project
    root.rename(root.with_name("moved"))
    execute(store, pid, "unregister")
    assert not store.list_projects()


def test_permanent_includes_unrelated_files(project):
    store, root, pid = project
    (root / "other.txt").write_text("extra file")
    execute(store, pid, "permanent")
    assert not root.exists() and not store.list_projects()


def test_name_and_token_are_bound(project):
    store, root, pid = project
    preview = store.project_lifecycle.preview(pid, "permanent")
    with pytest.raises(WorkbenchError, match="名称"):
        store.project_lifecycle.execute(pid, "permanent", preview["confirmation_token"], "wrong")
    with pytest.raises(WorkbenchError):
        store.project_lifecycle.execute(pid, "unregister", preview["confirmation_token"], "")
    assert root.exists()


def test_changed_identity_rejected(project):
    store, root, pid = project
    preview = store.project_lifecycle.preview(pid, "permanent")
    original = root.with_name("original")
    root.rename(original)
    shutil.copytree(original, root)
    with pytest.raises(WorkbenchError, match="变化"):
        store.project_lifecycle.execute(pid, "permanent", preview["confirmation_token"], "Disposable")
    assert root.exists() and original.exists()


def test_nested_project_rejected(project):
    store, root, pid = project
    store.create_or_open_project(name="Nested", root_path=str(root / "nested"))
    assert not store.project_lifecycle.preview(pid, "permanent")["allowed"]


def test_identity_mismatch_rejected(project):
    store, root, pid = project
    with store.project_database(pid).connect() as db:
        db.execute("UPDATE project_metadata SET project_id='different'")
    assert not store.project_lifecycle.preview(pid, "permanent")["allowed"]
    assert store.project_lifecycle.preview(pid, "unregister")["allowed"]


def test_protected_ancestor_rejected(project):
    store, root, pid = project
    for protected in (Path.home(), Path(root.anchor), store.state_dir, Path(__file__).resolve().parents[1]):
        with pytest.raises(WorkbenchError):
            store.project_lifecycle.check_target(protected, pid)


def test_link_rejected(project, monkeypatch):
    store, root, pid = project
    link = root / "untrusted"
    link.mkdir()
    original = store.project_lifecycle.is_link
    monkeypatch.setattr(store.project_lifecycle, "is_link", lambda path: path == link or original(path))
    assert not store.project_lifecycle.preview(pid, "permanent")["allowed"]


def test_partial_failure_restart_and_retry(project, monkeypatch):
    store, root, pid = project
    (root / "extra.txt").write_text("keep until deletion")
    original = shutil.rmtree
    def partial(path):
        (path / "extra.txt").unlink()
        raise PermissionError("file busy")
    monkeypatch.setattr(shutil, "rmtree", partial)
    with pytest.raises(WorkbenchError, match="未完成"):
        execute(store, pid, "permanent")
    assert not root.exists()
    assert store.list_projects()[0]["deletion_status"] == "failed"
    with pytest.raises(WorkbenchError):
        store.project_database(pid)
    with pytest.raises(WorkbenchError):
        store.create_or_open_project(name="Replacement", root_path=str(root))
    monkeypatch.setattr(shutil, "rmtree", original)
    resumed = WorkbenchStore(store.state_dir)
    execute(resumed, pid, "permanent")
    assert not resumed.list_projects()
    assert not list(root.parent.glob(".*.taichi-delete-*"))


def test_rename_failure_is_retryable(project, monkeypatch):
    store, root, pid = project
    original = Path.rename
    def locked(path, target):
        if path == root:
            raise PermissionError("directory in use")
        return original(path, target)
    monkeypatch.setattr(Path, "rename", locked)
    with pytest.raises(WorkbenchError):
        execute(store, pid, "permanent")
    assert root.exists() and store.project_lifecycle.journal(pid)
    monkeypatch.setattr(Path, "rename", original)
    execute(store, pid, "permanent")
    assert not root.exists()


def test_active_runtime_blocks_even_if_directory_went_missing(project):
    store, root, pid = project
    root.rename(root.with_name("moved"))
    store.project_lifecycle.active_projects = lambda: {pid}
    assert not store.project_lifecycle.preview(pid, "unregister")["allowed"]


def test_delete_and_enqueue_are_serialized(tmp_path):
    import asyncio
    import httpx
    from fastapi.testclient import TestClient
    from api.app import create_app
    from tests.test_workbench_domain_api import _create_project, _create_ready_scenario
    app = create_app(state_dir=tmp_path / "state", scheduler_enabled=False)
    with TestClient(app) as client:
        project = _create_project(client, tmp_path / "concurrent")
        scenario = _create_ready_scenario(client, project, "Concurrent")
        base = f"/api/projects/{project['project_id']}"
        preview = client.post(base + "/delete-preview", json={"mode": "unregister"}).json()
    async def race():
        lock = app.state.coordinator.project_lock(project["project_id"])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await lock.acquire()
            deletion = asyncio.create_task(client.request("DELETE", base, json={"mode": "unregister", "confirmation_token": preview["confirmation_token"]}))
            enqueue = asyncio.create_task(client.post(base + "/queue", json={"scenario_id": scenario["scenario_id"]}))
            await asyncio.sleep(0.02)
            assert not deletion.done() and not enqueue.done()
            lock.release()
            return await asyncio.gather(deletion, enqueue)
    deleted, queued = asyncio.run(race())
    assert (deleted.status_code, queued.status_code) in {(200, 404), (409, 201)}


def test_concurrent_previews_do_not_discard_another_project_token(project):
    store, _root, _pid = project
    lifecycle = store.project_lifecycle
    first_snapshot = threading.Event()
    release_first = threading.Event()
    calls_lock = threading.Lock()
    calls = 0

    class PausedSnapshot(dict):
        def items(self):
            nonlocal calls
            with calls_lock:
                calls += 1
                call = calls
            snapshot = list(super().items())
            if call == 1:
                first_snapshot.set()
                assert release_first.wait(timeout=5)
            return snapshot

    lifecycle._previews = PausedSnapshot()
    lifecycle.inspect = lambda project_id, mode: {
        "project_id": project_id,
        "name": project_id,
        "root_path": str(Path("C:/preview") / project_id),
        "mode": mode,
        "scenario_count": 0,
        "run_count": 0,
        "staging_path": None,
        "last_error": None,
        "blocked_reasons": [],
        "retry": False,
        "identity": None,
    }
    previews = {}

    def make_preview(project_id):
        previews[project_id] = lifecycle.preview(project_id, "unregister")

    first = threading.Thread(target=make_preview, args=("first",))
    second = threading.Thread(target=make_preview, args=("second",))
    first.start()
    assert first_snapshot.wait(timeout=5)
    second.start()
    release_first.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive() and not second.is_alive()
    assert {preview["confirmation_token"] for preview in previews.values()} <= set(lifecycle._previews)


def test_preview_token_is_consumed_once_under_concurrent_execute(project):
    store, _root, pid = project
    lifecycle = store.project_lifecycle
    preview = lifecycle.preview(pid, "unregister")
    barrier = threading.Barrier(2)
    errors = []

    def consume_with_wrong_target():
        barrier.wait(timeout=5)
        try:
            lifecycle.execute("different-project", "unregister", preview["confirmation_token"], "")
        except WorkbenchError as error:
            errors.append(error.code)

    threads = [threading.Thread(target=consume_with_wrong_target) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert sorted(errors) == ["project_delete_preview_expired", "project_delete_target_mismatch"]
