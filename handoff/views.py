import os
import tempfile

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

import io
import zipfile

from django.http import HttpResponse
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required

from .drive import (
    download_file_bytes,
    get_mockups_folder_id,
    list_folder_images,
    upload_design_file,
    upload_mockup_file,
)
from .forms import TaskCreateForm
from .mockup_generator import convert_svg_bytes, preview_mockup_for_template
from .mockup_service import maybe_autogenerate_mockups, run_mockup_generation
from .models import Attachment, MockupSlot, RecurringTask, ScheduledDesign, Task, TaskStep


def home(request):
    return redirect("handoff:today")


def today(request):
    assignee = request.GET.get("assignee", "Dad")
    today_date = timezone.localdate()
    RecurringTask.generate_for_date(today_date, assignee=assignee)
    tasks = (
        Task.objects.filter(due_date=today_date, assigned_to=assignee)
        .order_by("status", "title")
        .prefetch_related("steps")
    )
    for task in tasks:
        scheduled = _get_scheduled_design_for_task(task, today_date)
        if scheduled and task.drive_design_file_id != scheduled.drive_design_file_id:
            task.drive_design_file_id = scheduled.drive_design_file_id
            task.save(update_fields=["drive_design_file_id", "updated_at"])
            latest = (
                task.attachments.filter(kind=Attachment.KIND_DESIGN)
                .order_by("-created_at")
                .first()
            )
            if not latest or latest.drive_file_id != scheduled.drive_design_file_id:
                Attachment.objects.create(
                    task=task,
                    kind=Attachment.KIND_DESIGN,
                    drive_file_id=scheduled.drive_design_file_id,
                    filename="Scheduled design",
                )
            # Skip auto-generation here to avoid blocking page loads.
    return render(
        request,
        "handoff/today.html",
        {
            "tasks": tasks,
            "assignee": assignee,
            "today_date": today_date,
        },
    )


def summary(request):
    assignee = request.GET.get("assignee", "Dad")
    today_date = timezone.localdate()
    RecurringTask.generate_for_date(today_date, assignee=assignee)
    tasks = (
        Task.objects.filter(due_date=today_date, assigned_to=assignee)
        .order_by("status", "title")
        .prefetch_related("steps")
    )
    total = tasks.count()
    done = tasks.filter(status=Task.STATUS_DONE).count()
    in_progress = tasks.filter(status=Task.STATUS_IN_PROGRESS).count()
    new = tasks.filter(status=Task.STATUS_NEW).count()
    return render(
        request,
        "handoff/summary.html",
        {
            "tasks": tasks,
            "assignee": assignee,
            "today_date": today_date,
            "total": total,
            "done": done,
            "in_progress": in_progress,
            "new": new,
        },
    )


def _build_mockup_context(task: Task) -> dict:
    folder_images = []
    folder_error = ""
    if task.drive_mockup_folder_id:
        try:
            folder_images = list_folder_images(task.drive_mockup_folder_id)
        except Exception as exc:
            folder_error = f"Folder load failed: {exc}"
    template_count = 0
    if task.template_id:
        template_count = task.template.mockup_templates.count()
    slot_count = max(6, len(folder_images), template_count) if folder_images else max(6, template_count)
    task.ensure_mockup_slots(slot_count)
    slot_images = {
        idx + 1: image["id"] for idx, image in enumerate(folder_images)
    }
    has_mockup_templates = False
    if task.template_id:
        has_mockup_templates = task.template.mockup_templates.exists()
    mockups_folder_id = ""
    try:
        mockups_folder_id = get_mockups_folder_id(task.due_date)
    except Exception:
        mockups_folder_id = ""
    return {
        "slot_images": slot_images,
        "folder_error": folder_error,
        "required_orders": {order: True for order in task.required_mockup_orders()},
        "has_mockup_templates": has_mockup_templates,
        "mockups_folder_id": mockups_folder_id,
    }


def _maybe_autogenerate_mockups(request, task: Task) -> None:
    generated, error = maybe_autogenerate_mockups(task)
    if error and request is not None:
        messages.error(request, f"Auto-generate failed: {error}")
    elif generated and request is not None:
        messages.success(request, "Mockups auto-generated from design.")


def _get_scheduled_design_for_task(task: Task, date) -> ScheduledDesign | None:
    scheduled = None
    if task.recurring_task_id:
        scheduled = ScheduledDesign.objects.filter(
            due_date=date, recurring_task=task.recurring_task
        ).first()
    if not scheduled:
        scheduled = ScheduledDesign.objects.filter(
            due_date=date, recurring_task__isnull=True
        ).first()
    return scheduled


def task_detail(request, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    scheduled = _get_scheduled_design_for_task(task, task.due_date)
    if scheduled and task.drive_design_file_id != scheduled.drive_design_file_id:
        task.drive_design_file_id = scheduled.drive_design_file_id
        task.save(update_fields=["drive_design_file_id", "updated_at"])
        latest = (
            task.attachments.filter(kind=Attachment.KIND_DESIGN)
            .order_by("-created_at")
            .first()
        )
        if not latest or latest.drive_file_id != scheduled.drive_design_file_id:
            Attachment.objects.create(
                task=task,
                kind=Attachment.KIND_DESIGN,
                drive_file_id=scheduled.drive_design_file_id,
                filename="Scheduled design",
            )
    # Skip auto-generation here to avoid blocking page loads.
    task.refresh_status()
    context = _build_mockup_context(task)
    context["task"] = task
    latest_design = (
        task.attachments.filter(kind=Attachment.KIND_DESIGN)
        .order_by("-created_at")
        .first()
    )
    context["latest_design_attachment"] = latest_design
    first_incomplete = task.steps.filter(done=False).order_by("order", "id").first()
    context["first_incomplete_id"] = first_incomplete.id if first_incomplete else None
    return render(request, "handoff/task_detail.html", context)


def task_steps_fragment(request, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    first_incomplete = task.steps.filter(done=False).order_by("order", "id").first()
    return render(
        request,
        "handoff/_task_steps.html",
        {
            "task": task,
            "first_incomplete_id": first_incomplete.id if first_incomplete else None,
        },
    )


def task_mockups_fragment(request, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    context = _build_mockup_context(task)
    context["task"] = task
    return render(request, "handoff/_mockups_panel.html", context)


@require_POST
def replace_design(request, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    uploaded = request.FILES.get("design_file")
    if not uploaded:
        messages.error(request, "No design file uploaded.")
        return redirect("handoff:task_detail", task_id=task.id)

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as temp:
            for chunk in uploaded.chunks():
                temp.write(chunk)
            temp_path = temp.name
        file_id = upload_design_file(temp_path, uploaded.name, task.due_date)
        task.drive_design_file_id = file_id
        task.save(update_fields=["drive_design_file_id", "updated_at"])
        Attachment.objects.create(
            task=task,
            kind=Attachment.KIND_DESIGN,
            drive_file_id=file_id,
            filename=uploaded.name,
        )
        _maybe_autogenerate_mockups(request, task)
        messages.success(request, "Design updated.")
    except Exception as exc:
        messages.error(request, f"Design upload failed: {exc}")
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

    return redirect("handoff:task_detail", task_id=task.id)


def download_mockups(request, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    slots = task.mockup_slots.exclude(drive_file_id="").order_by("order")
    if not slots.exists():
        return redirect("handoff:task_detail", task_id=task.id)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for slot in slots:
            name, _, data = download_file_bytes(slot.drive_file_id)
            safe_name = f"{slot.order:02d}_{name}"
            zip_file.writestr(safe_name, data)
    zip_buffer.seek(0)

    filename = f"mockups-{task.due_date.isoformat()}-task-{task.id}.zip"
    response = HttpResponse(zip_buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def mockup_files(request, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    slots = task.mockup_slots.exclude(drive_file_id="").order_by("order")
    files = [
        {
            "order": slot.order,
            "file_id": slot.drive_file_id,
            "filename": slot.filename or f"mockup-{slot.order}.png",
        }
        for slot in slots
    ]
    return JsonResponse({"files": files})


def mockup_file_download(request, file_id: str):
    name, _, data = download_file_bytes(file_id)
    response = HttpResponse(data, content_type="application/octet-stream")
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


@require_POST
def generate_mockups(request, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    if not task.template or not task.template.mockup_templates.exists():
        messages.error(request, "No mockup templates configured for this task.")
        return redirect("handoff:task_detail", task_id=task.id)
    if not task.drive_design_file_id:
        messages.error(request, "No design file set for this task.")
        return redirect("handoff:task_detail", task_id=task.id)

    try:
        generated = run_mockup_generation(task)
        if generated:
            messages.success(request, "Mockups generated.")
    except Exception as exc:
        messages.error(request, f"Mockup generation failed: {exc}")

    return redirect("handoff:task_detail", task_id=task.id)


def preview_mockup_template(request, template_id: int):
    from .models import MockupTemplate, TaskTemplate

    template = get_object_or_404(MockupTemplate, pk=template_id)
    task_template = template.template
    if not task_template.sample_design_drive_file_id:
        return HttpResponse("Missing sample design.", status=400)
    try:
        design_name, design_mime, design_bytes = download_file_bytes(task_template.sample_design_drive_file_id)
        _, design_bytes = convert_svg_bytes(design_name, design_mime, design_bytes)
        png_bytes = preview_mockup_for_template(template, design_bytes)
        size_param = request.GET.get("size")
        if size_param:
            try:
                from PIL import Image
                from io import BytesIO

                size = int(size_param)
                image = Image.open(BytesIO(png_bytes))
                image = image.resize((size, size), Image.LANCZOS)
                out = BytesIO()
                image.save(out, format="PNG")
                png_bytes = out.getvalue()
            except Exception:
                pass
    except Exception as exc:
        return HttpResponse(f"Preview failed: {exc}", status=500)
    return HttpResponse(png_bytes, content_type="image/png")


@staff_member_required
def mockup_template_asset(request, template_id: int, kind: str):
    from .models import MockupTemplate

    template = get_object_or_404(MockupTemplate, pk=template_id)
    file_id = None
    if kind == "background":
        file_id = template.background_drive_file_id
    elif kind == "overlay":
        file_id = template.overlay_drive_file_id
    elif kind == "design":
        file_id = template.template.sample_design_drive_file_id
    if not file_id:
        return HttpResponse(status=404)
    name, mime, data = download_file_bytes(file_id)
    name, data = convert_svg_bytes(name, mime, data)
    size_param = request.GET.get("size")
    if size_param:
        try:
            from PIL import Image
            from io import BytesIO

            size = int(size_param)
            image = Image.open(BytesIO(data))
            image = image.resize((size, size), Image.LANCZOS)
            out = BytesIO()
            image.save(out, format="PNG")
            data = out.getvalue()
        except Exception:
            pass
    return HttpResponse(data, content_type="image/png")


@staff_member_required
def mockup_template_position(request, template_id: int):
    from .models import MockupTemplate

    template = get_object_or_404(MockupTemplate, pk=template_id)
    if not template.template.sample_design_drive_file_id:
        return HttpResponse("Add sample design ID on template.", status=400)
    return render(
        request,
        "handoff/mockup_position.html",
        {"template": template, "design_boxes": template.design_boxes.all()},
    )


@staff_member_required
@require_POST
def mockup_template_position_save(request, template_id: int):
    from .models import MockupTemplate, MockupDesignBox

    template = get_object_or_404(MockupTemplate, pk=template_id)
    try:
        data = request.POST
        template.design_x = int(data.get("design_x", template.design_x))
        template.design_y = int(data.get("design_y", template.design_y))
        template.design_width = int(data.get("design_width", template.design_width))
        template.design_height = int(data.get("design_height", template.design_height))
        overlay_position = data.get("overlay_position")
        if overlay_position in {"OVER", "UNDER"}:
            template.overlay_position = overlay_position
        template.save(
            update_fields=[
                "design_x",
                "design_y",
                "design_width",
                "design_height",
                "overlay_position",
            ]
        )
        boxes_raw = data.get("design_boxes", "")
        if boxes_raw:
            # Clear and recreate boxes
            template.design_boxes.all().delete()
            parts = [p for p in boxes_raw.split(";") if p.strip()]
            order = 1
            for part in parts:
                vals = part.split(",")
                if len(vals) not in (4, 5):
                    continue
                x, y, w, h = [int(float(v)) for v in vals[:4]]
                rot = float(vals[4]) if len(vals) == 5 else 0.0
                MockupDesignBox.objects.create(
                    template=template,
                    order=order,
                    x=x,
                    y=y,
                    width=w,
                    height=h,
                    rotation=rot,
                )
                order += 1
    except Exception as exc:
        return HttpResponse(f"Save failed: {exc}", status=400)
    return redirect(f"/admin/handoff/mockuptemplate/{template.id}/change/")


def _parse_steps(raw_text: str) -> list[str]:
    if not raw_text:
        return []
    lines = [line.strip() for line in raw_text.splitlines()]
    return [line for line in lines if line]


def create_task(request):
    if request.method == "POST":
        form = TaskCreateForm(request.POST, request.FILES)
        if form.is_valid():
            steps = _parse_steps(form.cleaned_data.get("steps_text", ""))
            design_file = form.cleaned_data.get("design_file")
            due_date = form.cleaned_data.get("due_date")

            uploaded_file_id = ""
            uploaded_file_name = ""
            temp_path = None
            if design_file:
                try:
                    with tempfile.NamedTemporaryFile(delete=False) as temp:
                        for chunk in design_file.chunks():
                            temp.write(chunk)
                        temp_path = temp.name
                    uploaded_file_id = upload_design_file(
                        temp_path, design_file.name, due_date
                    )
                    uploaded_file_name = design_file.name
                except Exception as exc:
                    form.add_error("design_file", f"Drive upload failed: {exc}")
                    return render(request, "handoff/task_create.html", {"form": form})
                finally:
                    if temp_path and os.path.exists(temp_path):
                        os.remove(temp_path)

            task = form.save(commit=False)
            if uploaded_file_id:
                task.drive_design_file_id = uploaded_file_id
            task.save()

            if steps:
                TaskStep.objects.bulk_create(
                    [
                        TaskStep(task=task, order=idx + 1, text=text)
                        for idx, text in enumerate(steps)
                    ]
                )
            else:
                task.seed_steps_from_template()

            if uploaded_file_id:
                Attachment.objects.create(
                    task=task,
                    kind=Attachment.KIND_DESIGN,
                    drive_file_id=uploaded_file_id,
                    filename=uploaded_file_name,
                )

            _maybe_autogenerate_mockups(request, task)
            return redirect("handoff:task_detail", task_id=task.id)
    else:
        form = TaskCreateForm()

    return render(request, "handoff/task_create.html", {"form": form})


@require_POST
def toggle_step(request, step_id: int):
    step = get_object_or_404(TaskStep, pk=step_id)
    step.toggle()
    step.task.refresh_status()
    task = step.task

    if request.headers.get("HX-Request") == "true":
        first_incomplete = task.steps.filter(done=False).order_by("order", "id").first()
        return render(
            request,
            "handoff/_task_steps.html",
            {
                "task": task,
                "first_incomplete_id": first_incomplete.id if first_incomplete else None,
            },
        )

    return redirect("handoff:task_detail", task_id=task.id)


@require_POST
def upload_mockup(request, slot_id: int):
    slot = get_object_or_404(MockupSlot, pk=slot_id)
    task = slot.task
    uploaded = request.FILES.get("mockup_file")
    if not uploaded:
        return render(
            request,
            "handoff/_mockup_slot.html",
            {"slot": slot, "error": "No file uploaded."},
        )

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as temp:
            for chunk in uploaded.chunks():
                temp.write(chunk)
            temp_path = temp.name
        file_id = upload_mockup_file(temp_path, uploaded.name, task.due_date)
        slot.drive_file_id = file_id
        slot.filename = uploaded.name
        slot.save(update_fields=["drive_file_id", "filename", "updated_at"])
        from .models import Attachment

        Attachment.objects.create(
            task=task,
            kind=Attachment.KIND_MOCKUP,
            drive_file_id=file_id,
            filename=uploaded.name,
        )
        task.refresh_status()
    except Exception as exc:
        return render(
            request,
            "handoff/_mockup_slot.html",
            {"slot": slot, "error": f"Upload failed: {exc}"},
        )
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

    return render(request, "handoff/_mockup_slot.html", {"slot": slot})
