"""Persistent queue admission and execution coordination.

The scheduler is deliberately small: SQLite remains the source of truth for
queue/run state while this process owns only the active execution handles.
Executors are injected in tests and can be replaced by the production Taichi
executor without changing queue semantics.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Callable, Dict, Optional, Protocol

from api.services.runtime_session import (
    PreparedRuntime,
    RuntimeSession,
    prepare_runtime_from_payload,
)
from api.services.workbench_store import WorkbenchError, WorkbenchStore


logger = logging.getLogger(__name__)


class RunExecutor(Protocol):
    def signature(self, context: Dict[str, Any]) -> str:
        ...

    def execute(
        self,
        context: Dict[str, Any],
        on_update: Callable[[Dict[str, Any]], None],
        stop_event: Event,
    ) -> Dict[str, Any]:
        ...

    def request_stop(self, simulation_id: str) -> None:
        ...


class _ObservableState(dict):
    """Dict used by RuntimeSession to publish only JSON-safe state changes."""

    def __init__(self, *args: Any, on_change: Callable[[Dict[str, Any]], None], **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._on_change = on_change

    @staticmethod
    def _safe(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): _ObservableState._safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_ObservableState._safe(item) for item in value]
        return None

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        if key in {
            "status",
            "progress",
            "current_time",
            "end_time",
            "step_count",
            "output_count",
            "start_time",
            "end_time_actual",
            "error",
        }:
            self._on_change({key: self._safe(value)})

    def update(self, *args: Any, **kwargs: Any) -> None:
        payload = dict(*args, **kwargs)
        super().update(payload)
        selected = {
            key: self._safe(value)
            for key, value in payload.items()
            if key
            in {
                "status",
                "progress",
                "current_time",
                "end_time",
                "step_count",
                "output_count",
                "start_time",
                "end_time_actual",
                "error",
            }
        }
        if selected:
            self._on_change(selected)


class RuntimeRunExecutor:
    """Adapter from a persisted queue context to the existing Taichi runtime."""

    def __init__(self, *, solver_factory: Any = None, reset_runtime_on_dispose: bool = True) -> None:
        self.solver_factory = solver_factory
        self.reset_runtime_on_dispose = reset_runtime_on_dispose
        self._sessions: Dict[str, RuntimeSession] = {}
        self._lock = Lock()

    def signature(self, context: Dict[str, Any]) -> str:
        return str(context.get("runtime_profile") or "cuda_production_default")

    def request_stop(self, simulation_id: str) -> None:
        with self._lock:
            session = self._sessions.get(simulation_id)
        if session is not None:
            session.request_stop()

    def execute(
        self,
        context: Dict[str, Any],
        on_update: Callable[[Dict[str, Any]], None],
        stop_event: Event,
    ) -> Dict[str, Any]:
        prepared: Optional[PreparedRuntime] = None
        session: Optional[RuntimeSession] = None
        stop_thread: Optional[Thread] = None
        simulation_id = str(context["simulation_id"])

        def request_session_stop() -> None:
            stop_event.wait()
            if stop_event.is_set() and session is not None:
                session.request_stop()

        try:
            prepared = prepare_runtime_from_payload(
                app_output_dir=Path(context["project_root"]) / "outputs",
                dem_file=context.get("dem_file"),
                rainfall_file=context.get("rainfall_file"),
                soil_zones_file=context.get("soil_zones_file"),
                boundary_file=context.get("boundary_file"),
                output_dir=context.get("output_dir"),
                overrides=context.get("overrides") or {},
                case_config_file=context.get("case_config_file"),
                case_base_dir=context.get("case_base_dir"),
                case_input_files=context.get("case_input_files") or {},
                runtime_profile_name=context.get("runtime_profile"),
                session_id=simulation_id,
            )
            # The queue id is the durable identity; preparation creates a
            # transient UUID for standalone legacy calls, so replace it here.
            prepared.simulation_id = simulation_id
            prepared.job_metadata["simulation_id"] = simulation_id
            session = RuntimeSession(
                prepared,
                solver_factory=self.solver_factory,
                reset_runtime_on_dispose=self.reset_runtime_on_dispose,
            )
            with self._lock:
                self._sessions[simulation_id] = session
            stop_thread = Thread(target=request_session_stop, name=f"taichi-flow-stop-{simulation_id}", daemon=True)
            stop_thread.start()
            initial_state = session.initialize()
            observed = _ObservableState(initial_state, on_change=on_update)
            observed["solver"] = session.solver
            on_update({"status": "starting", "end_time": float(prepared.config.time.t_end)})
            session.run_to_completion({"simulations": {simulation_id: observed}})
            return {
                "status": str(observed.get("status") or "failed"),
                "progress": float(observed.get("progress") or 0),
                "current_time": float(observed.get("current_time") or 0),
                "end_time": float(observed.get("end_time") or 0),
                "step_count": int(observed.get("step_count") or 0),
                "output_count": int(observed.get("output_count") or 0),
                "error": observed.get("error"),
                "resource_summary": observed.get("resource_summary") or {},
            }
        except Exception as exc:  # noqa: BLE001 - persist the execution failure
            logger.exception("Taichi run %s failed before completion", simulation_id)
            if session is not None and session._registered_active:
                session.dispose()
            return {"status": "failed", "error": str(exc), "resource_summary": {"children": 0}}
        finally:
            if stop_thread is not None and stop_thread.is_alive():
                stop_event.set()
                stop_thread.join(timeout=1.5)
            with self._lock:
                self._sessions.pop(simulation_id, None)


@dataclass
class _ActiveJob:
    project_id: str
    simulation_id: str
    signature: str
    stop_event: Event
    task: asyncio.Task


class SimulationCoordinator:
    """Admit one FIFO head per project and at most N compatible projects."""

    def __init__(
        self,
        store: WorkbenchStore,
        executor: RunExecutor,
        *,
        max_concurrent_projects: int = 2,
        poll_interval: float = 0.1,
    ) -> None:
        self.store = store
        self.executor = executor
        self.max_concurrent_projects = max(1, int(max_concurrent_projects))
        self.poll_interval = max(0.01, float(poll_interval))
        self._stop_event: Optional[asyncio.Event] = None
        self._loop_task: Optional[asyncio.Task] = None
        self._active: Dict[str, _ActiveJob] = {}

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def active_simulation_ids(self) -> set[str]:
        return {job.simulation_id for job in self._active.values()}

    async def start(self) -> None:
        if self._loop_task is not None and not self._loop_task.done():
            return
        self._stop_event = asyncio.Event()
        self._loop_task = asyncio.create_task(self._run_loop(), name="taichi-flow-scheduler")

    async def stop(self) -> None:
        if self._stop_event is None:
            return
        self._stop_event.set()
        for job in list(self._active.values()):
            job.stop_event.set()
            try:
                self.executor.request_stop(job.simulation_id)
            except Exception:
                logger.debug("Executor stop request failed", exc_info=True)
        tasks = [job.task for job in list(self._active.values()) if not job.task.done()]
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=1.5)
            except asyncio.TimeoutError:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        if self._loop_task is not None and not self._loop_task.done():
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
        self._loop_task = None
        self._stop_event = None

    def request_stop(self, simulation_id: str) -> bool:
        for job in self._active.values():
            if job.simulation_id == simulation_id:
                job.stop_event.set()
                try:
                    self.executor.request_stop(simulation_id)
                except Exception:
                    logger.debug("Executor stop request failed", exc_info=True)
                return True
        return False

    async def _run_loop(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            await self._dispatch_available()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                continue

    async def _dispatch_available(self) -> None:
        active_projects = set(self._active)
        if len(active_projects) >= self.max_concurrent_projects:
            return
        candidates = self.store.queue_candidates(active_projects)
        active_signatures = {job.signature for job in self._active.values()}
        for candidate in candidates:
            if len(self._active) >= self.max_concurrent_projects:
                break
            project_id = str(candidate["project_id"])
            if project_id in self._active:
                continue
            signature = str(self.executor.signature(candidate))
            if active_signatures and signature not in active_signatures:
                continue
            try:
                context = self.store.claim_queue_item(project_id, str(candidate["queue_item_id"]))
            except WorkbenchError:
                continue
            stop_event = Event()
            task = asyncio.create_task(
                self._execute_claimed(context, signature, stop_event),
                name=f"taichi-flow-run-{context['simulation_id']}",
            )
            self._active[project_id] = _ActiveJob(
                project_id=project_id,
                simulation_id=str(context["simulation_id"]),
                signature=signature,
                stop_event=stop_event,
                task=task,
            )
            active_signatures.add(signature)

    async def _execute_claimed(self, context: Dict[str, Any], signature: str, stop_event: Event) -> None:
        project_id = str(context["project_id"])
        simulation_id = str(context["simulation_id"])

        def on_update(update: Dict[str, Any]) -> None:
            safe: Dict[str, Any] = {}
            for key in (
                "status",
                "progress",
                "current_time",
                "end_time",
                "step_count",
                "output_count",
                "start_time",
                "end_time_actual",
                "error",
            ):
                if key in update:
                    safe[key] = update[key]
            if safe:
                self.store.update_run(project_id, simulation_id, safe)

        try:
            self.store.update_run(
                project_id,
                simulation_id,
                {"status": "starting", "runtime_profile_json": json.dumps({"signature": signature})},
            )
            result = await asyncio.to_thread(self.executor.execute, context, on_update, stop_event)
            if not isinstance(result, dict):
                result = {"status": "failed", "error": "executor returned a non-object result"}
        except asyncio.CancelledError:
            result = {"status": "interrupted", "error": "scheduler_shutdown"}
            raise
        except Exception as exc:  # noqa: BLE001 - domain state must record worker errors
            logger.exception("Queued simulation %s failed", simulation_id)
            result = {"status": "failed", "error": str(exc)}
        finally:
            try:
                self.store.finish_run(project_id, simulation_id, locals().get("result", {"status": "failed"}))
            except Exception:
                logger.exception("Could not finalize queued simulation %s", simulation_id)
            active = self._active.get(project_id)
            if active is not None and active.simulation_id == simulation_id:
                self._active.pop(project_id, None)


def default_max_concurrent_projects() -> int:
    try:
        return max(1, int(os.environ.get("TAICHI_FLOW_MAX_CONCURRENT_PROJECTS", "2")))
    except ValueError:
        return 2


__all__ = ["RunExecutor", "RuntimeRunExecutor", "SimulationCoordinator", "default_max_concurrent_projects"]
