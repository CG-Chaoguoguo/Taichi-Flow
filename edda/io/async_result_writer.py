"""Bounded background writer for GeoTIFF / ASCII result families.

The solver thread only copies host arrays and enqueues jobs.  Encoding and
disk I/O run on a single dedicated thread so GDAL stays single-threaded while
the next physics step can proceed.  A full queue applies back-pressure instead
of unbounded host memory growth.
"""
from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from edda.io.result_exporter import ResultExporter

logger = logging.getLogger(__name__)

_SENTINEL = object()


@dataclass
class GridWriteJob:
    kind: str
    path: str
    data: np.ndarray
    transform: Any = None
    crs: Any = None
    nodata_value: float = -9999.0


class AsyncResultWriter:
    """Single-thread result encoder with a bounded work queue."""

    def __init__(self, *, max_queued_frames: int = 4):
        self._queue: queue.Queue = queue.Queue(maxsize=max(1, int(max_queued_frames)))
        self._error: Optional[BaseException] = None
        self._error_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run,
            name="edda-result-writer",
            daemon=True,
        )
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._thread.start()
        self._started = True

    def submit(self, job: GridWriteJob) -> None:
        self.raise_if_failed()
        self._queue.put(job)

    def flush(self) -> None:
        self._queue.join()
        self.raise_if_failed()

    def close(self) -> None:
        if not self._started:
            return
        self._queue.put(_SENTINEL)
        self._thread.join()
        self.raise_if_failed()

    def raise_if_failed(self) -> None:
        with self._error_lock:
            error = self._error
        if error is not None:
            raise RuntimeError(f"Async result writer failed: {error}") from error

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job is _SENTINEL:
                    return
                self._write(job)
            except BaseException as exc:  # noqa: BLE001 - persist and drain
                with self._error_lock:
                    if self._error is None:
                        self._error = exc
                logger.exception("Async result write failed for %s", getattr(job, "path", job))
            finally:
                self._queue.task_done()

    @staticmethod
    def _write(job: GridWriteJob) -> None:
        exporter = ResultExporter(
            data=job.data,
            transform=job.transform,
            crs=job.crs,
            nodata_value=job.nodata_value,
        )
        if job.kind == "geotiff":
            exporter.to_geotiff(job.path)
            return
        if job.kind == "ascii":
            exporter.to_ascii_grid(job.path)
            return
        raise ValueError(f"Unsupported result write kind: {job.kind}")
