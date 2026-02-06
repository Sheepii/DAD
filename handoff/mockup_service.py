from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock, Thread
import time
from typing import Callable, Optional
from uuid import uuid4

from django.db import close_old_connections

from .mockup_generator import generate_mockup_for_template
from .models import AppSettings, Attachment, MockupSlot, Task


ProgressCallback = Callable[[int, int], None]


@dataclass
class MockupJob:
    job_id: str
    task_id: int
    total: int = 0
    done: int = 0
    status: str = "running"
    error: str = ""
    updated_at: float = field(default_factory=time.time)


_mockup_jobs: dict[str, MockupJob] = {}
_mockup_jobs_lock = Lock()


def _set_job(job: MockupJob) -> None:
    with _mockup_jobs_lock:
        _mockup_jobs[job.job_id] = job


def _update_job(job_id: str, **updates) -> None:
    with _mockup_jobs_lock:
        job = _mockup_jobs.get(job_id)
        if not job:
            return
        for key, value in updates.items():
            setattr(job, key, value)
        job.updated_at = time.time()


def get_mockup_job(job_id: str) -> Optional[MockupJob]:
    now = time.time()
    with _mockup_jobs_lock:
        job = _mockup_jobs.get(job_id)
        if not job:
            return None
        if job.status in {"done", "error"} and now - job.updated_at > 900:
            _mockup_jobs.pop(job_id, None)
            return None
        return MockupJob(
            job_id=job.job_id,
            task_id=job.task_id,
            total=job.total,
            done=job.done,
            status=job.status,
            error=job.error,
            updated_at=job.updated_at,
        )


def start_mockup_generation_job(task_id: int) -> str:
    job_id = uuid4().hex
    job = MockupJob(job_id=job_id, task_id=task_id)
    _set_job(job)

    def worker() -> None:
        close_old_connections()
        try:
            task = Task.objects.get(pk=task_id)

            def progress_cb(done: int, total: int) -> None:
                _update_job(job_id, done=done, total=total, status="running")

            run_mockup_generation(task, progress_cb=progress_cb)
            _update_job(job_id, status="done")
        except Exception as exc:
            _update_job(job_id, status="error", error=str(exc))
        finally:
            close_old_connections()

    Thread(target=worker, daemon=True).start()
    return job_id


def run_mockup_generation(task: Task, progress_cb: ProgressCallback | None = None) -> int:
    if not task.template or not task.template.mockup_templates.exists():
        return 0
    if not task.drive_design_file_id:
        return 0

    templates = task.template.mockup_templates.all().order_by("order")
    total = templates.count()
    slot_count = max(6, templates.count())
    task.ensure_mockup_slots(slot_count)

    generated = 0
    for tmpl in templates:
        file_id, filename = generate_mockup_for_template(task, tmpl)
        slot, _ = MockupSlot.objects.get_or_create(
            task=task, order=tmpl.order, defaults={"label": tmpl.label}
        )
        slot.drive_file_id = file_id
        slot.filename = filename
        if tmpl.label and not slot.label:
            slot.label = tmpl.label
        slot.save(update_fields=["drive_file_id", "filename", "label", "updated_at"])
        Attachment.objects.create(
            task=task,
            kind=Attachment.KIND_MOCKUP,
            drive_file_id=file_id,
            filename=filename,
        )
        generated += 1
        if progress_cb:
            progress_cb(generated, total)

    task.mockups_generated_design_id = task.drive_design_file_id
    task.save(update_fields=["mockups_generated_design_id", "updated_at"])
    task.refresh_status()
    return generated


def maybe_autogenerate_mockups(task: Task) -> tuple[int, Optional[str]]:
    settings_obj = AppSettings.objects.first()
    if settings_obj and not settings_obj.auto_generate_mockups:
        return 0, None
    if not task.drive_design_file_id:
        return 0, None
    if not task.template_id or not task.template.mockup_templates.exists():
        return 0, None
    if task.mockups_generated_design_id == task.drive_design_file_id:
        return 0, None
    try:
        generated = run_mockup_generation(task)
        return generated, None
    except Exception as exc:
        return 0, str(exc)
