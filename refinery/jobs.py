"""In-memory background-job registry with progress tracking.

Long-running work (bulk imports, connector pulls, bulk metadata updates) runs in a
daemon thread and reports progress into a shared, thread-safe registry. Every page
polls ``/jobs/active`` and renders a progress tray, so a running job is visible (and
keeps updating) no matter which page the operator navigates to.

State is process-local and intentionally ephemeral: it does not survive a restart or
an autoreload, which is fine for an operator workbench — a reload means the worker
thread is gone too. SQLite writes from the worker are safe because Store serialises
them behind its own lock (check_same_thread=False).
"""
from __future__ import annotations
import itertools, threading, time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

_ids = itertools.count(1)


@dataclass
class Job:
    id: int
    kind: str                          # 'import' | 'connector' | 'bulk' — drives an icon/label
    label: str                         # human title shown in the tray
    total: Optional[int] = None        # None => indeterminate (animated bar, no %)
    done: int = 0
    status: str = 'running'            # 'running' | 'done' | 'error'
    message: str = ''                  # latest sub-status (e.g. current file)
    href: Optional[str] = None         # where "View results" should point once done
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def advance(self, n: int = 1, message: str = '') -> None:
        with self._lock:
            self.done += n
            if message:
                self.message = message

    def finish(self, message: str = '', href: Optional[str] = None) -> None:
        with self._lock:
            self.status = 'done'
            self.finished_at = time.time()
            if message:
                self.message = message
            if href:
                self.href = href

    def fail(self, error: object) -> None:
        with self._lock:
            self.status = 'error'
            self.finished_at = time.time()
            self.message = str(error) or 'failed'

    def to_dict(self) -> dict:
        with self._lock:
            return {
                'id': self.id, 'kind': self.kind, 'label': self.label,
                'total': self.total, 'done': self.done, 'status': self.status,
                'message': self.message, 'href': self.href,
            }


class JobRegistry:
    """Holds active jobs plus recently finished ones (so the tray can show a brief
    'Done'/'Failed' state) and prunes the stale finished ones on each read."""

    def __init__(self, keep_finished_seconds: float = 25.0):
        self._jobs: Dict[int, Job] = {}
        self._lock = threading.Lock()
        self.keep = keep_finished_seconds

    def create(self, kind: str, label: str, total: Optional[int] = None, href: Optional[str] = None) -> Job:
        job = Job(id=next(_ids), kind=kind, label=label, total=total, href=href)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def run(self, kind: str, label: str, work: Callable[[Job], None],
            total: Optional[int] = None, href: Optional[str] = None) -> Job:
        """Register a job and run ``work(job)`` in a daemon thread. The worker reports
        progress via ``job.advance``; this wrapper handles completion and errors so a
        crash surfaces as a failed job in the tray instead of an unseen traceback."""
        job = self.create(kind, label, total=total, href=href)

        def _runner() -> None:
            try:
                work(job)
                if job.status == 'running':
                    job.finish(href=href)
            except Exception as exc:  # noqa: BLE001 - any failure becomes a visible job error
                job.fail(exc)

        threading.Thread(target=_runner, name=f'job-{job.id}', daemon=True).start()
        return job

    def visible(self) -> List[dict]:
        now = time.time()
        with self._lock:
            for jid in list(self._jobs):
                j = self._jobs[jid]
                if j.finished_at is not None and (now - j.finished_at) > self.keep:
                    del self._jobs[jid]
            jobs = sorted(self._jobs.values(), key=lambda j: j.id)
        return [j.to_dict() for j in jobs]


JOBS = JobRegistry()
