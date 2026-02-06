import os
import tempfile

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

import io
import json
import zipfile
import mimetypes
import re
from urllib.parse import quote

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
from .context_processors import (
    _build_sop_embed_url,
    _compute_runway_status,
    _match_active_sop,
)
from .forms import TaskCreateForm
from .mockup_generator import convert_svg_bytes, preview_mockup_for_template
from .mockup_service import (
    get_mockup_job,
    maybe_autogenerate_mockups,
    run_mockup_generation,
    start_mockup_generation_job,
)
from .etsy import format_tags_csv, normalize_tags_csv, suggest_title_from_filename, validate_tags
from .ai import generate_etsy_tags
from .models import (
    Attachment,
    SOPGuide,
    MockupSlot,
    RecurringTask,
    ScheduledDesign,
    Store,
    Task,
    TaskPublication,
    TaskStep,
)
from .design_workflow import ensure_emergency_design


def home(request):
    return redirect("handoff:today")


def _get_user_stores(request):
    if not request.user.is_authenticated:
        return Store.objects.none()
    stores = Store.objects.filter(active=True).order_by("order", "name")
    if request.user.is_staff or request.user.is_superuser:
        return stores
    return stores.filter(
        memberships__user=request.user,
        memberships__active=True,
    ).distinct()


def _get_store_from_request(request):
    store_id = request.GET.get("store")
    if not store_id:
        return None
    stores = _get_user_stores(request)
    try:
        return stores.get(pk=int(store_id))
    except (Store.DoesNotExist, ValueError):
        return None


def _store_query_suffix(store: Store | None) -> str:
    return f"?store={store.id}" if store else ""


@login_required
def today(request):
    assignee = request.GET.get("assignee", "Dad")
    today_date = timezone.localdate()
    user_stores = list(_get_user_stores(request))
    store = _get_store_from_request(request)
    if user_stores and not store and len(user_stores) == 1:
        store = user_stores[0]

    if request.user.is_staff or request.user.is_superuser:
        RecurringTask.generate_for_date(today_date, assignee=assignee)
    else:
        RecurringTask.generate_for_date(today_date, assignee=None)
    recycled = None
    try:
        recycled = ensure_emergency_design(today_date, store=store)
        if recycled:
            messages.warning(
                request,
                "Emergency: no new designs found. Recycling an old design for today.",
            )
    except Exception as exc:
        messages.error(request, f"Emergency recycle failed: {exc}")
    if request.user.is_staff or request.user.is_superuser:
        tasks = (
            Task.objects.filter(due_date=today_date, assigned_to=assignee)
            .order_by("status", "title")
            .prefetch_related("steps")
        )
    else:
        tasks = (
            Task.objects.filter(due_date=today_date)
            .order_by("status", "title")
            .prefetch_related("steps")
        )
    scheduled_by_task = {}
    if store:
        filtered = []
        for task in tasks:
            scheduled = _get_scheduled_design_for_task(task, today_date, store=store)
            if scheduled:
                filtered.append(task)
                scheduled_by_task[task.id] = scheduled
        tasks = filtered
    elif not (request.user.is_staff or request.user.is_superuser):
        filtered = []
        for task in tasks:
            for user_store in user_stores:
                scheduled = _get_scheduled_design_for_task(task, today_date, store=user_store)
                if scheduled:
                    filtered.append(task)
                    scheduled_by_task[task.id] = scheduled
                    break
        tasks = filtered

    for task in tasks:
        scheduled = scheduled_by_task.get(task.id) if store else _get_scheduled_design_for_task(task, today_date, store=store)
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
            "assignee": assignee if (request.user.is_staff or request.user.is_superuser) else request.user.get_username(),
            "today_date": today_date,
            "store": store,
        },
    )


@login_required
def summary(request):
    assignee = request.GET.get("assignee", "Dad")
    today_date = timezone.localdate()
    user_stores = list(_get_user_stores(request))
    store = _get_store_from_request(request)
    if user_stores and not store and len(user_stores) == 1:
        store = user_stores[0]

    if request.user.is_staff or request.user.is_superuser:
        RecurringTask.generate_for_date(today_date, assignee=assignee)
        tasks_qs = (
            Task.objects.filter(due_date=today_date, assigned_to=assignee)
            .order_by("status", "title")
            .prefetch_related("steps")
        )
    else:
        RecurringTask.generate_for_date(today_date, assignee=None)
        tasks_qs = (
            Task.objects.filter(due_date=today_date)
            .order_by("status", "title")
            .prefetch_related("steps")
        )
    tasks = list(tasks_qs)
    if store:
        filtered = []
        for task in tasks:
            scheduled = _get_scheduled_design_for_task(task, today_date, store=store)
            if scheduled:
                filtered.append(task)
        tasks = filtered
    elif not (request.user.is_staff or request.user.is_superuser):
        filtered = []
        for task in tasks:
            for user_store in user_stores:
                scheduled = _get_scheduled_design_for_task(task, today_date, store=user_store)
                if scheduled:
                    filtered.append(task)
                    break
        tasks = filtered

    total = len(tasks)
    done = len([t for t in tasks if t.status == Task.STATUS_DONE])
    in_progress = len([t for t in tasks if t.status == Task.STATUS_IN_PROGRESS])
    new = len([t for t in tasks if t.status == Task.STATUS_NEW])
    return render(
        request,
        "handoff/summary.html",
        {
            "tasks": tasks,
            "assignee": assignee if (request.user.is_staff or request.user.is_superuser) else request.user.get_username(),
            "today_date": today_date,
            "total": total,
            "done": done,
            "in_progress": in_progress,
            "new": new,
            "store": store,
        },
    )


@login_required
def runway_status(request):
    store = _get_store_from_request(request)
    status = _compute_runway_status(store)
    payload = {
        "days_remaining": status["days_remaining"],
        "exhaustion_date": status["exhaustion_date"].isoformat()
        if status["exhaustion_date"]
        else None,
        "threshold": status["threshold"],
        "below_threshold": status["below_threshold"],
        "store": store.name if store else None,
    }
    return JsonResponse(payload)


@login_required
def sop_library(request):
    sops = SOPGuide.objects.filter(active=True).order_by("name", "id")
    selected = None
    embed_url = ""
    selected_id = request.GET.get("id")
    if selected_id:
        try:
            selected = sops.get(pk=int(selected_id))
            embed_url = _build_sop_embed_url(selected.scribe_id_or_url)
        except (SOPGuide.DoesNotExist, ValueError):
            selected = None
            embed_url = ""
    return render(
        request,
        "handoff/sop_library.html",
        {"sops": sops, "selected_sop": selected, "selected_embed_url": embed_url},
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
    zip_extras = []
    if task.template_id:
        for attachment in task.template.attachments.exclude(drive_file_id=""):
            filename = attachment.filename or attachment.label or f"extra-{attachment.id}"
            guessed_type, _ = mimetypes.guess_type(filename)
            is_video = bool(guessed_type and guessed_type.startswith("video/"))
            zip_extras.append(
                {
                    "id": attachment.id,
                    "label": attachment.label or filename,
                    "filename": filename,
                    "drive_file_id": attachment.drive_file_id,
                    "is_video": is_video,
                    "include_in_mockup_zip": attachment.include_in_mockup_zip,
                }
            )

    def _extract_numeric_order(*values):
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            match = re.search(r"\d+", text)
            if match:
                try:
                    return int(match.group(0))
                except ValueError:
                    continue
        return None

    required_orders = set(task.required_mockup_orders())
    mockup_cards = []
    for slot in task.mockup_slots.all():
        fallback_image_id = slot_images.get(slot.order)
        is_required = slot.order in required_orders
        if slot.drive_file_id or fallback_image_id or is_required:
            mockup_cards.append(
                {
                    "kind": "slot",
                    "number": slot.order,
                    "sort_number": slot.order,
                    "slot": slot,
                    "fallback_image_id": fallback_image_id,
                }
            )

    for extra in zip_extras:
        number = _extract_numeric_order(extra.get("label"), extra.get("filename"))
        mockup_cards.append(
            {
                "kind": "extra",
                "number": number,
                "sort_number": number if number is not None else 999999,
                "extra": extra,
            }
        )

    mockup_cards.sort(
        key=lambda card: (
            card.get("sort_number", 999999),
            0 if card.get("kind") == "slot" else 1,
            card.get("extra", {}).get("label", "") if card.get("kind") == "extra" else "",
            card.get("slot").order if card.get("kind") == "slot" else 0,
        )
    )

    return {
        "slot_images": slot_images,
        "folder_error": folder_error,
        "required_orders": {order: True for order in required_orders},
        "has_mockup_templates": has_mockup_templates,
        "mockups_folder_id": mockups_folder_id,
        "zip_extras": zip_extras,
        "mockup_cards": mockup_cards,
    }


def _maybe_autogenerate_mockups(request, task: Task) -> None:
    generated, error = maybe_autogenerate_mockups(task)
    if error and request is not None:
        messages.error(request, f"Auto-generate failed: {error}")
    elif generated and request is not None:
        messages.success(request, "Mockups auto-generated from design.")


def _get_scheduled_design_for_task(task: Task, date, store: Store | None = None) -> ScheduledDesign | None:
    scheduled = None
    store_filter = {"store": store} if store else {"store__isnull": True}
    if task.recurring_task_id:
        scheduled = ScheduledDesign.objects.filter(
            due_date=date, recurring_task=task.recurring_task, **store_filter
        ).first()
    if not scheduled:
        scheduled = ScheduledDesign.objects.filter(
            due_date=date, recurring_task__isnull=True, **store_filter
        ).first()
    return scheduled


@login_required
def task_detail(request, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    store = _get_store_from_request(request)
    scheduled = _get_scheduled_design_for_task(task, task.due_date, store=store)
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
    context["store"] = store
    latest_design = (
        task.attachments.filter(kind=Attachment.KIND_DESIGN)
        .order_by("-created_at")
        .first()
    )
    context["latest_design_attachment"] = latest_design
    first_incomplete = task.steps.filter(done=False).order_by("order", "id").first()
    context["first_incomplete_id"] = first_incomplete.id if first_incomplete else None
    return render(request, "handoff/task_detail.html", context)


@login_required
@require_POST
def toggle_manual_done(request, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    store = _get_store_from_request(request)
    task.manual_done = not task.manual_done
    task.save(update_fields=["manual_done", "updated_at"])
    task.refresh_status()
    return redirect(f"/task/{task.id}/{_store_query_suffix(store)}")


@login_required
def etsy_listing_preview(request, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    store = _get_store_from_request(request)

    # Seed Etsy defaults once (template description, suggested title).
    updated_fields = []
    if not task.etsy_description and task.template_id and task.template.etsy_description_default:
        task.etsy_description = task.template.etsy_description_default
        updated_fields.append("etsy_description")
    if not task.etsy_title:
        suffix = task.template.etsy_title_suffix if task.template_id else ""
        latest_design = (
            task.attachments.filter(kind=Attachment.KIND_DESIGN).order_by("-created_at").first()
        )
        filename = latest_design.filename if latest_design and latest_design.filename else task.title
        task.etsy_title = suggest_title_from_filename(filename, suffix=suffix)
        updated_fields.append("etsy_title")
    if updated_fields:
        task.save(update_fields=updated_fields + ["updated_at"])

    task.ensure_publications()
    publications = (
        task.publications.select_related("store")
        .order_by("store__order", "store__name", "id")
    )
    context = _build_mockup_context(task)
    context["task"] = task
    slots = task.mockup_slots.exclude(drive_file_id="").order_by("order")
    context["mockup_slots"] = slots
    context["listing_title"] = task.etsy_title or task.title
    context["listing_description"] = (task.etsy_description or "").strip()
    context["listing_tags"] = format_tags_csv(task.etsy_tags or [])
    context["product_suffix"] = task.template.etsy_title_suffix if task.template_id else ""
    context["publications"] = publications
    context["store"] = store
    sops = list(SOPGuide.objects.filter(active=True).order_by("name", "id"))
    if sops:
        active_sop = _match_active_sop(request.path)
        selected_sop = active_sop if active_sop in sops else None
        if not selected_sop:
            for sop in sops:
                if "etsy" in (sop.context_route or "").lower():
                    selected_sop = sop
                    break
        if not selected_sop:
            selected_sop = sops[0]
        context["sop_guides"] = [
            {
                "id": sop.id,
                "name": sop.name,
                "embed_url": _build_sop_embed_url(sop.scribe_id_or_url),
            }
            for sop in sops
        ]
        context["selected_sop_id"] = selected_sop.id
        context["selected_sop_embed_url"] = _build_sop_embed_url(
            selected_sop.scribe_id_or_url
        )
    return render(request, "handoff/etsy_listing_preview.html", context)


@login_required
@require_POST
def etsy_listing_save(request, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    content_type = request.headers.get("Content-Type", "")
    if "application/json" in content_type:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except Exception:
            return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)
        title = str(payload.get("title") or "").strip()
        description = str(payload.get("description") or "").strip()
        tags_csv = str(payload.get("tags") or "").strip()
    else:
        title = str(request.POST.get("title") or "").strip()
        description = str(request.POST.get("description") or "").strip()
        tags_csv = str(request.POST.get("tags") or "").strip()

    clear_tags = not tags_csv
    tags = normalize_tags_csv(tags_csv)
    validation = validate_tags(tags) if tags else validate_tags([])
    if tags and not validation.ok:
        return JsonResponse(
            {
                "ok": False,
                "errors": validation.errors,
                "per_tag_errors": validation.per_tag_errors,
                "normalized": format_tags_csv(validation.tags),
            },
            status=400,
        )

    updated = []
    if title != task.etsy_title:
        task.etsy_title = title
        updated.append("etsy_title")
    if description != task.etsy_description:
        task.etsy_description = description
        updated.append("etsy_description")
    if clear_tags and task.etsy_tags:
        task.etsy_tags = None
        updated.append("etsy_tags")
    elif tags:
        task.etsy_tags = validation.tags
        updated.append("etsy_tags")

    if updated:
        task.save(update_fields=updated + ["updated_at"])

    return JsonResponse(
        {
            "ok": True,
            "etsy_title": task.etsy_title,
            "etsy_description": task.etsy_description,
            "etsy_tags": task.etsy_tags or [],
            "normalized": format_tags_csv(task.etsy_tags or []),
        }
    )


@login_required
@require_POST
def etsy_generate_tags(request, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    try:
        payload = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        payload = {}

    title = str(payload.get("title") or task.etsy_title or task.title).strip()
    description = str(payload.get("description") or task.etsy_description or "").strip()
    product_hint = str(payload.get("product_hint") or (task.template.etsy_title_suffix if task.template_id else "")).strip()

    try:
        result = generate_etsy_tags(title=title, description=description, product_hint=product_hint)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    validation = validate_tags(result.tags)
    if not validation.ok:
        return JsonResponse(
            {
                "ok": False,
                "error": "Generated tags failed validation.",
                "errors": validation.errors,
                "per_tag_errors": validation.per_tag_errors,
                "tags": validation.tags,
                "normalized": format_tags_csv(validation.tags),
                "raw": result.raw_text,
            },
            status=400,
        )

    task.etsy_tags = validation.tags
    task.save(update_fields=["etsy_tags", "updated_at"])
    return JsonResponse(
        {
            "ok": True,
            "tags": validation.tags,
            "normalized": format_tags_csv(validation.tags),
        }
    )


@login_required
@require_POST
def etsy_publications_save(request, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    try:
        payload = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

    items = payload.get("publications")
    if not isinstance(items, list):
        return JsonResponse({"ok": False, "error": "Missing publications list."}, status=400)

    task.ensure_publications()
    pubs_by_store = {
        pub.store_id: pub
        for pub in task.publications.select_related("store").all()
    }

    updated = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            store_id = int(item.get("store_id"))
        except Exception:
            continue
        status = str(item.get("status") or "").strip().upper()
        listing_url = str(item.get("listing_url") or "").strip()
        pub = pubs_by_store.get(store_id)
        if not pub:
            # Only allow stores that exist.
            if not Store.objects.filter(pk=store_id).exists():
                continue
            pub = TaskPublication.objects.create(task=task, store_id=store_id)
            pubs_by_store[store_id] = pub

        fields = []
        was_listed = pub.status == TaskPublication.STATUS_LISTED
        if status in {TaskPublication.STATUS_QUEUED, TaskPublication.STATUS_LISTED} and status != pub.status:
            pub.status = status
            pub.mark_listed_if_needed(was_listed=was_listed)
            fields.append("status")
            if pub.listed_at and not was_listed:
                fields.append("listed_at")
        if listing_url != pub.listing_url:
            pub.listing_url = listing_url
            fields.append("listing_url")
        if fields:
            pub.save(update_fields=fields + ["updated_at"])
            updated += 1

    return JsonResponse({"ok": True, "updated": updated})


@login_required
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


@login_required
def task_mockups_fragment(request, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    context = _build_mockup_context(task)
    context["task"] = task
    return render(request, "handoff/_mockups_panel.html", context)


@login_required
@require_POST
def replace_design(request, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    store = _get_store_from_request(request)
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

    return redirect(f"/task/{task.id}/{_store_query_suffix(store)}")


@login_required
def download_mockups(request, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    slots = list(task.mockup_slots.exclude(drive_file_id="").order_by("order"))
    template_assets = []
    if task.template_id:
        template_assets = list(task.template.attachments.exclude(drive_file_id=""))
    if not slots and not template_assets:
        return redirect("handoff:task_detail", task_id=task.id)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        seen_names = set()
        def unique_name(name: str) -> str:
            base = name
            idx = 2
            while name in seen_names:
                if "." in base:
                    left, ext = base.rsplit(".", 1)
                    name = f"{left}-{idx}.{ext}"
                else:
                    name = f"{base}-{idx}"
                idx += 1
            seen_names.add(name)
            return name

        for slot in slots:
            name, _, data = download_file_bytes(slot.drive_file_id)
            _, ext = os.path.splitext(name or "")
            ext = ext or ".png"
            safe_name = unique_name(f"{slot.order}{ext}")
            zip_file.writestr(safe_name, data)
        for idx, asset in enumerate(template_assets, start=1):
            if not asset.include_in_mockup_zip:
                continue
            name, _, data = download_file_bytes(asset.drive_file_id)
            asset_name = asset.filename or name or f"template-extra-{idx}.png"
            safe_name = unique_name(asset_name)
            zip_file.writestr(safe_name, data)
    zip_buffer.seek(0)

    filename = f"mockups-{task.due_date.isoformat()}-task-{task.id}.zip"
    response = HttpResponse(zip_buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
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


@login_required
def mockup_file_download(request, file_id: str):
    name, mime, data = download_file_bytes(file_id)
    content_type = mime or mimetypes.guess_type(name)[0] or "application/octet-stream"
    response = HttpResponse(data, content_type=content_type)
    safe_name = name.replace('"', "")
    response["Content-Disposition"] = (
        f'attachment; filename="{safe_name}"; filename*=UTF-8\'\'{quote(safe_name)}'
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_POST
def generate_mockups(request, task_id: int):
    task = get_object_or_404(Task, pk=task_id)
    store = _get_store_from_request(request)
    if not task.template or not task.template.mockup_templates.exists():
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {"error": "No mockup templates configured for this task."}, status=400
            )
        messages.error(request, "No mockup templates configured for this task.")
        return redirect("handoff:task_detail", task_id=task.id)
    if not task.drive_design_file_id:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"error": "No design file set for this task."}, status=400)
        messages.error(request, "No design file set for this task.")
        return redirect("handoff:task_detail", task_id=task.id)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        job_id = start_mockup_generation_job(task.id)
        total = task.template.mockup_templates.count()
        return JsonResponse({"job_id": job_id, "total": total})

    try:
        generated = run_mockup_generation(task)
        if generated:
            messages.success(request, "Mockups generated.")
    except Exception as exc:
        messages.error(request, f"Mockup generation failed: {exc}")

    return redirect(f"/task/{task.id}/{_store_query_suffix(store)}")


@login_required
def mockup_generation_status(request, task_id: int):
    job_id = request.GET.get("job", "")
    if not job_id:
        return JsonResponse({"error": "Missing job id."}, status=400)
    job = get_mockup_job(job_id)
    if not job or job.task_id != task_id:
        return JsonResponse({"error": "Job not found."}, status=404)
    return JsonResponse(
        {
            "job_id": job.job_id,
            "task_id": job.task_id,
            "total": job.total,
            "done": job.done,
            "status": job.status,
            "error": job.error,
        }
    )


@login_required
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


@login_required
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
            task.ensure_publications()

            # Seed Etsy defaults early (title/description) to support copy/paste flows.
            if not task.etsy_description and task.template_id and task.template.etsy_description_default:
                task.etsy_description = task.template.etsy_description_default
            if not task.etsy_title:
                suffix = task.template.etsy_title_suffix if task.template_id else ""
                seed_name = uploaded_file_name or task.title
                task.etsy_title = suggest_title_from_filename(seed_name, suffix=suffix)
            task.save(update_fields=["etsy_title", "etsy_description", "updated_at"])

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


@login_required
@require_POST
def toggle_step(request, step_id: int):
    step = get_object_or_404(TaskStep, pk=step_id)
    step.toggle()
    step.task.refresh_status()
    task = step.task
    store = _get_store_from_request(request)

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

    return redirect(f"/task/{task.id}/{_store_query_suffix(store)}")


@login_required
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
