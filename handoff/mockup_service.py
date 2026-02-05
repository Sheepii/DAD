from __future__ import annotations

from typing import Optional

from .mockup_generator import generate_mockup_for_template
from .models import AppSettings, Attachment, MockupSlot, Task


def run_mockup_generation(task: Task) -> int:
    if not task.template or not task.template.mockup_templates.exists():
        return 0
    if not task.drive_design_file_id:
        return 0

    templates = task.template.mockup_templates.all().order_by("order")
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
