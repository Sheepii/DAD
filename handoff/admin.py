from django.contrib import admin, messages

from django.utils import timezone

from django.utils.safestring import mark_safe
from django.urls import path
from django.shortcuts import render, redirect
from django.utils import timezone
import calendar
import datetime
from django.http import JsonResponse
from django.core.management import call_command

from .forms import MockupTemplateForm, RecurringTaskForm, TaskTemplateForm, TaskAdminForm
from .context_processors import _compute_runway_status
from .design_workflow import ensure_emergency_design
from .mockup_generator import generate_mockup_bytes_for_template
from .drive import upload_mockup_bytes_to_bucket
from .models import (
    Attachment,
    AppSettings,
    DesignFile,
    DesignHistory,
    MockupTemplate,
    MockupSlot,
    ScheduledDesign,
    RecurringTask,
    SOPGuide,
    SOPReplyTemplate,
    Store,
    StoreMembership,
    Task,
    TaskPublication,
    TaskStep,
    TaskTemplate,
    TemplateAttachment,
    extract_drive_id,
)
from .drive import upload_design_file, upload_template_asset_bytes
import tempfile
import os
from .mockup_service import maybe_autogenerate_mockups


def handoff_schedule_view(request):
    today = timezone.localdate()
    month_str = request.GET.get("month")
    date_str = request.GET.get("date")
    task_filter = request.GET.get("task")
    store_filter = request.GET.get("store")
    selected_task = None
    selected_store = None
    if task_filter:
        try:
            selected_task = RecurringTask.objects.get(pk=int(task_filter))
        except (RecurringTask.DoesNotExist, ValueError):
            selected_task = None
    if store_filter:
        try:
            selected_store = Store.objects.get(pk=int(store_filter))
        except (Store.DoesNotExist, ValueError):
            selected_store = None

    if month_str:
        year, month = [int(x) for x in month_str.split("-")]
        current = datetime.date(year, month, 1)
    else:
        current = datetime.date(today.year, today.month, 1)

    selected_date = None
    if date_str:
        try:
            selected_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            selected_date = None

    if request.method == "POST":
        due_date = request.POST.get("due_date")
        design_id = request.POST.get("drive_design_file_id", "")
        uploaded = request.FILES.get("design_upload")
        task_id = request.POST.get("recurring_task_id")
        store_id = request.POST.get("store_id")
        task_obj = None
        store_obj = None
        if task_id:
            try:
                task_obj = RecurringTask.objects.get(pk=int(task_id))
            except (RecurringTask.DoesNotExist, ValueError):
                task_obj = None
        if store_id:
            try:
                store_obj = Store.objects.get(pk=int(store_id))
            except (Store.DoesNotExist, ValueError):
                store_obj = None
        if due_date:
            due = datetime.datetime.strptime(due_date, "%Y-%m-%d").date()
            remove_flag = request.POST.get("remove_design") == "1"
            if uploaded:
                temp_path = None
                try:
                    if hasattr(uploaded, "temporary_file_path"):
                        temp_path = uploaded.temporary_file_path()
                    else:
                        with tempfile.NamedTemporaryFile(delete=False) as temp:
                            for chunk in uploaded.chunks():
                                temp.write(chunk)
                            temp_path = temp.name
                    design_id = upload_design_file(temp_path, uploaded.name, due)
                finally:
                    if temp_path and not hasattr(uploaded, "temporary_file_path") and os.path.exists(temp_path):
                        os.remove(temp_path)
            if remove_flag:
                ScheduledDesign.objects.filter(
                    due_date=due, recurring_task=task_obj, store=store_obj
                ).delete()
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return JsonResponse(
                        {
                            "status": "deleted",
                            "due_date": due.isoformat(),
                            "task_id": str(task_obj.id) if task_obj else "",
                            "store_id": str(store_obj.id) if store_obj else "",
                        }
                    )
            elif design_id:
                design_id = extract_drive_id(design_id)
                scheduled, _ = ScheduledDesign.objects.update_or_create(
                    due_date=due,
                    recurring_task=task_obj,
                    store=store_obj,
                    defaults={"drive_design_file_id": design_id},
                )
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    label = task_obj.title if task_obj else "All tasks"
                    if store_obj:
                        label = f"{label} · {store_obj.name}"
                    return JsonResponse(
                        {
                            "status": "saved",
                            "due_date": due.isoformat(),
                            "item": {
                                "id": scheduled.id,
                                "design_id": scheduled.drive_design_file_id,
                                "task_id": str(task_obj.id) if task_obj else "",
                                "store_id": str(store_obj.id) if store_obj else "",
                                "label": label,
                                "thumb": f"https://drive.google.com/thumbnail?id={scheduled.drive_design_file_id}&sz=w120",
                            },
                        }
                    )
        redirect_task = f"&task={task_obj.id}" if task_obj else ""
        redirect_store = f"&store={store_obj.id}" if store_obj else ""
        return redirect(f"/admin/handoff/schedule/?date={due_date}{redirect_task}{redirect_store}")

    cal = calendar.Calendar(firstweekday=0)
    weeks = []
    scheduled_qs = ScheduledDesign.objects.select_related("recurring_task", "store")
    if selected_task:
        scheduled_qs = scheduled_qs.filter(recurring_task=selected_task)
    if selected_store:
        scheduled_qs = scheduled_qs.filter(store=selected_store)
    scheduled_map = {}
    for sd in scheduled_qs:
        label = sd.recurring_task.title if sd.recurring_task else "All tasks"
        if sd.store:
            label = f"{label} · {sd.store.name}"
        scheduled_map.setdefault(sd.due_date, []).append(
            {
                "id": sd.id,
                "design_id": sd.drive_design_file_id,
                "task": sd.recurring_task,
                "task_id": sd.recurring_task.id if sd.recurring_task else "",
                "store_id": sd.store.id if sd.store else "",
                "thumb": f"https://drive.google.com/thumbnail?id={sd.drive_design_file_id}&sz=w120",
                "label": label,
            }
        )
    for week in cal.monthdatescalendar(current.year, current.month):
        week_cells = []
        for day in week:
            week_cells.append(
                {
                    "date": day,
                    "in_month": day.month == current.month,
                    "scheduled_items": scheduled_map.get(day, []),
                }
            )
        weeks.append(week_cells)

    prev_month = (current.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
    next_month = (current.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)

    selected_design = None
    if selected_date:
        if selected_task:
            scheduled = ScheduledDesign.objects.filter(
                due_date=selected_date, recurring_task=selected_task, store=selected_store
            ).first()
        else:
            scheduled = ScheduledDesign.objects.filter(
                due_date=selected_date, recurring_task__isnull=True, store=selected_store
            ).first()
        if scheduled:
            selected_design = scheduled.drive_design_file_id

    context = dict(
        admin.site.each_context(request),
        month_label=current.strftime("%B %Y"),
        month_value=f"{current.year}-{current.month:02d}",
        prev_month=f"{prev_month.year}-{prev_month.month:02d}",
        next_month=f"{next_month.year}-{next_month.month:02d}",
        weeks=weeks,
        selected_date=selected_date or today,
        scheduled_map=scheduled_map,
        selected_design_id=selected_design or "",
        recurring_tasks=RecurringTask.objects.order_by("title"),
        stores=Store.objects.order_by("order", "name"),
        selected_task=selected_task,
        selected_store=selected_store,
        task_query=f"&task={selected_task.id}" if selected_task else "",
        store_query=f"&store={selected_store.id}" if selected_store else "",
    )
    context["runway"] = _compute_runway_status(selected_store)
    return render(request, "admin/handoff_schedule.html", context)


_orig_get_urls = admin.site.get_urls


def intake_designs_view(request):
    if request.method != "POST":
        return redirect("/admin/handoff/schedule/")
    try:
        call_command("intake_designs")
        messages.success(request, "Intake complete. Check Design Files for results.")
    except Exception as exc:
        messages.error(request, f"Intake failed: {exc}")
    return redirect("/admin/handoff/schedule/")


def emergency_recycle_view(request):
    if request.method != "POST":
        return redirect("/admin/handoff/schedule/")
    store_id = request.POST.get("store_id")
    store = None
    if store_id:
        try:
            store = Store.objects.get(pk=int(store_id))
        except (Store.DoesNotExist, ValueError):
            store = None
    try:
        result = ensure_emergency_design(timezone.localdate(), store=store)
        if result:
            label = store.name if store else "All stores"
            messages.warning(request, f"Emergency recycle applied for {label}.")
        else:
            messages.info(request, "No emergency recycle needed.")
    except Exception as exc:
        messages.error(request, f"Emergency recycle failed: {exc}")
    return redirect("/admin/handoff/schedule/")


def mockup_studio_view(request):
    templates = TaskTemplate.objects.order_by("name")
    stores = Store.objects.order_by("order", "name")
    selected_template = None
    selected_store = None
    selected_date = timezone.localdate()
    results = []

    if request.method == "POST":
        template_id = request.POST.get("template_id")
        store_id = request.POST.get("store_id")
        date_str = request.POST.get("due_date")
        upload = request.FILES.get("design_upload")

        if date_str:
            try:
                selected_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                selected_date = timezone.localdate()

        if store_id:
            try:
                selected_store = Store.objects.get(pk=int(store_id))
            except (Store.DoesNotExist, ValueError):
                selected_store = None

        if template_id:
            try:
                selected_template = TaskTemplate.objects.get(pk=int(template_id))
            except (TaskTemplate.DoesNotExist, ValueError):
                selected_template = None

        if not selected_template:
            messages.error(request, "Select a valid task template.")
        elif not upload:
            messages.error(request, "Upload a design file.")
        elif not selected_template.mockup_templates.exists():
            messages.error(request, "Selected template has no mockup templates.")
        else:
            design_bytes = upload.read()
            design_name = upload.name or "design.png"
            design_mime = upload.content_type or "image/png"
            try:
                for tmpl in selected_template.mockup_templates.all().order_by("order"):
                    png_bytes, filename = generate_mockup_bytes_for_template(
                        tmpl, design_name, design_mime, design_bytes
                    )
                    file_id = upload_mockup_bytes_to_bucket(
                        png_bytes, filename, due_date=selected_date, store=selected_store
                    )
                    results.append(
                        {
                            "file_id": file_id,
                            "filename": filename,
                            "label": tmpl.label or f"Mockup {tmpl.order}",
                        }
                    )
                messages.success(request, f"Generated {len(results)} mockup(s).")
            except Exception as exc:
                messages.error(request, f"Mockup generation failed: {exc}")

    context = dict(
        admin.site.each_context(request),
        templates=templates,
        stores=stores,
        selected_template=selected_template,
        selected_store=selected_store,
        selected_date=selected_date,
        results=results,
    )
    return render(request, "admin/handoff_mockup_studio.html", context)


def _get_urls():
    urls = _orig_get_urls()
    custom = [
        path("handoff/schedule/", admin.site.admin_view(handoff_schedule_view), name="handoff_schedule"),
        path("handoff/intake/", admin.site.admin_view(intake_designs_view), name="handoff_intake_designs"),
        path("handoff/emergency/", admin.site.admin_view(emergency_recycle_view), name="handoff_emergency_recycle"),
        path("handoff/mockup-studio/", admin.site.admin_view(mockup_studio_view), name="handoff_mockup_studio"),
    ]
    return custom + urls


admin.site.get_urls = _get_urls


class TaskStepInline(admin.TabularInline):
    model = TaskStep
    extra = 0


class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0


class TemplateAttachmentInline(admin.TabularInline):
    model = TemplateAttachment
    extra = 0


class MockupTemplateInline(admin.TabularInline):
    model = MockupTemplate
    extra = 0
    form = MockupTemplateForm
    readonly_fields = ("preview", "background_preview", "overlay_preview", "mask_preview")
    fields = (
        "order",
        "label",
        "preview",
        "background_preview",
        "background_upload",
        "background_drive_file_id",
        "overlay_preview",
        "overlay_upload",
        "overlay_drive_file_id",
        "mask_preview",
        "mask_upload",
        "mask_drive_file_id",
        "overlay_position",
        "design_x",
        "design_y",
        "design_width",
        "design_height",
    )

    def preview(self, obj):
        if not obj.pk:
            return ""
        if not obj.template or not obj.template.sample_design_drive_file_id:
            return "Add sample design ID on template"
        url = f"/mockup-template/{obj.pk}/preview/?size=600"
        return mark_safe(
            f'<div style="display:flex;align-items:center;gap:8px;">'
            f'<img src="{url}" style="width:120px;height:120px;object-fit:cover;border:1px solid #ddd;" />'
            f'<a href="{url}" target="_blank" rel="noopener">Open</a>'
            f'<a href="/mockup-template/{obj.pk}/position/" style="margin-left:8px;">Position</a>'
            f"</div>"
        )

    def background_preview(self, obj):
        if not obj.background_drive_file_id:
            return ""
        url = f"https://drive.google.com/thumbnail?id={obj.background_drive_file_id}&sz=w300"
        return mark_safe(f'<img src="{url}" style="width:80px;height:80px;object-fit:cover;border:1px solid #ddd;background:#000;" />')

    def overlay_preview(self, obj):
        if not obj.overlay_drive_file_id:
            return ""
        url = f"https://drive.google.com/thumbnail?id={obj.overlay_drive_file_id}&sz=w300"
        return mark_safe(f'<img src="{url}" style="width:80px;height:80px;object-fit:cover;border:1px solid #ddd;background:#000;" />')

    def mask_preview(self, obj):
        if not obj.mask_drive_file_id:
            return ""
        url = f"https://drive.google.com/thumbnail?id={obj.mask_drive_file_id}&sz=w300"
        return mark_safe(f'<img src="{url}" style="width:80px;height:80px;object-fit:cover;border:1px solid #ddd;background:#000;" />')


class MockupSlotInline(admin.TabularInline):
    model = MockupSlot
    extra = 0


class TaskPublicationInline(admin.TabularInline):
    model = TaskPublication
    extra = 0


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    form = TaskAdminForm
    list_display = ("title", "due_date", "assigned_to", "status")
    list_filter = ("due_date", "status", "assigned_to")
    search_fields = ("title", "notes")
    inlines = [TaskStepInline, MockupSlotInline, TaskPublicationInline, AttachmentInline]

    def save_model(self, request, obj, form, change):
        if obj.drive_design_file_id:
            obj.drive_design_file_id = extract_drive_id(obj.drive_design_file_id)
        if obj.drive_mockup_folder_id:
            obj.drive_mockup_folder_id = extract_drive_id(obj.drive_mockup_folder_id)
        uploaded = form.cleaned_data.get("design_upload")
        if uploaded:
            temp_path = None
            try:
                if hasattr(uploaded, "temporary_file_path"):
                    temp_path = uploaded.temporary_file_path()
                else:
                    with tempfile.NamedTemporaryFile(delete=False) as temp:
                        for chunk in uploaded.chunks():
                            temp.write(chunk)
                        temp_path = temp.name
                file_id = upload_design_file(temp_path, uploaded.name, obj.due_date)
                obj.drive_design_file_id = file_id
            finally:
                if temp_path and not hasattr(uploaded, "temporary_file_path") and os.path.exists(temp_path):
                    os.remove(temp_path)
        super().save_model(request, obj, form, change)
        generated, error = maybe_autogenerate_mockups(obj)
        if error:
            self.message_user(request, f"Auto-generate failed: {error}", level="ERROR")
        elif generated:
            self.message_user(request, "Mockups auto-generated from design.")

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        task = form.instance
        if not task.steps.exists():
            task.seed_steps_from_template()


@admin.register(TaskTemplate)
class TaskTemplateAdmin(admin.ModelAdmin):
    form = TaskTemplateForm
    list_display = ("name",)
    search_fields = ("name",)
    inlines = [TemplateAttachmentInline, MockupTemplateInline]

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        if formset.model is MockupTemplate:
            for inline_form in formset.forms:
                if inline_form.cleaned_data.get("DELETE"):
                    continue
                instance = inline_form.instance
                files = inline_form.files
                if files:
                    template_name = (
                        instance.template.name
                        if instance.template
                        else form.instance.name
                    )
                    if files.get("background_upload"):
                        uploaded = files["background_upload"]
                        file_id = upload_template_asset_bytes(
                            uploaded.read(),
                            uploaded.name,
                            template_name=template_name,
                            slide_order=instance.order,
                            kind="background",
                            mime_type=uploaded.content_type or "image/png",
                        )
                        instance.background_drive_file_id = file_id
                    if files.get("overlay_upload"):
                        uploaded = files["overlay_upload"]
                        file_id = upload_template_asset_bytes(
                            uploaded.read(),
                            uploaded.name,
                            template_name=template_name,
                            slide_order=instance.order,
                            kind="overlay",
                            mime_type=uploaded.content_type or "image/png",
                        )
                        instance.overlay_drive_file_id = file_id
                    if files.get("mask_upload"):
                        uploaded = files["mask_upload"]
                        file_id = upload_template_asset_bytes(
                            uploaded.read(),
                            uploaded.name,
                            template_name=template_name,
                            slide_order=instance.order,
                            kind="mask",
                            mime_type=uploaded.content_type or "image/png",
                        )
                        instance.mask_drive_file_id = file_id
                instance.save()
            formset.save_m2m()
            return
        for instance in instances:
            instance.save()
        formset.save_m2m()


@admin.register(MockupTemplate)
class MockupTemplateAdmin(admin.ModelAdmin):
    form = MockupTemplateForm
    list_display = ("template", "order", "label", "preview")
    list_filter = ("template",)
    actions = ["move_up", "move_down"]
    readonly_fields = ("preview", "background_preview", "overlay_preview", "mask_preview")

    fields = (
        "template",
        "order",
        "label",
        "overlay_position",
        "design_x",
        "design_y",
        "design_width",
        "design_height",
        "background_preview",
        "background_upload",
        "background_drive_file_id",
        "overlay_preview",
        "overlay_upload",
        "overlay_drive_file_id",
        "mask_preview",
        "mask_upload",
        "mask_drive_file_id",
        "preview",
    )

    def preview(self, obj):
        if not obj.pk:
            return ""
        if not obj.template or not obj.template.sample_design_drive_file_id:
            return "Add sample design ID on template"
        url = f"/mockup-template/{obj.pk}/preview/?size=400"
        return mark_safe(
            f'<div style="display:flex;align-items:center;gap:8px;">'
            f'<img src="{url}" style="width:80px;height:80px;object-fit:cover;border:1px solid #ddd;" />'
            f'<a href="{url}" target="_blank" rel="noopener">Open</a>'
            f'<a href="/mockup-template/{obj.pk}/position/" style="margin-left:8px;">Position</a>'
            f"</div>"
        )

    def background_preview(self, obj):
        if not obj.background_drive_file_id:
            return ""
        url = f"https://drive.google.com/thumbnail?id={obj.background_drive_file_id}&sz=w300"
        return mark_safe(f'<img src="{url}" style="width:120px;height:120px;object-fit:cover;border:1px solid #ddd;background:#000;" />')

    def overlay_preview(self, obj):
        if not obj.overlay_drive_file_id:
            return ""
        url = f"https://drive.google.com/thumbnail?id={obj.overlay_drive_file_id}&sz=w300"
        return mark_safe(f'<img src="{url}" style="width:120px;height:120px;object-fit:cover;border:1px solid #ddd;background:#000;" />')

    def mask_preview(self, obj):
        if not obj.mask_drive_file_id:
            return ""
        url = f"https://drive.google.com/thumbnail?id={obj.mask_drive_file_id}&sz=w300"
        return mark_safe(f'<img src="{url}" style="width:120px;height:120px;object-fit:cover;border:1px solid #ddd;background:#000;" />')

    @admin.action(description="Move up")
    def move_up(self, request, queryset):
        for obj in queryset.order_by("order"):
            if obj.order > 1:
                obj.order -= 1
                obj.save(update_fields=["order"])

    @admin.action(description="Move down")
    def move_down(self, request, queryset):
        for obj in queryset.order_by("-order"):
            obj.order += 1
            obj.save(update_fields=["order"])

    def save_model(self, request, obj, form, change):
        files = request.FILES
        if files:
            template_name = obj.template.name if obj.template else "Template"
            if files.get("background_upload"):
                uploaded = files["background_upload"]
                file_id = upload_template_asset_bytes(
                    uploaded.read(),
                    uploaded.name,
                    template_name=template_name,
                    slide_order=obj.order,
                    kind="background",
                    mime_type=uploaded.content_type or "image/png",
                )
                obj.background_drive_file_id = file_id
            if files.get("overlay_upload"):
                uploaded = files["overlay_upload"]
                file_id = upload_template_asset_bytes(
                    uploaded.read(),
                    uploaded.name,
                    template_name=template_name,
                    slide_order=obj.order,
                    kind="overlay",
                    mime_type=uploaded.content_type or "image/png",
                )
                obj.overlay_drive_file_id = file_id
            if files.get("mask_upload"):
                uploaded = files["mask_upload"]
                file_id = upload_template_asset_bytes(
                    uploaded.read(),
                    uploaded.name,
                    template_name=template_name,
                    slide_order=obj.order,
                    kind="mask",
                    mime_type=uploaded.content_type or "image/png",
                )
                obj.mask_drive_file_id = file_id
        super().save_model(request, obj, form, change)


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "drive_root_folder_id",
        "drive_use_service_account",
        "auto_generate_mockups",
        "updated_at",
    )


@admin.register(ScheduledDesign)
class ScheduledDesignAdmin(admin.ModelAdmin):
    list_display = ("due_date", "recurring_task", "store", "drive_design_file_id", "created_at")
    list_filter = ("due_date", "recurring_task", "store")
    actions = ["apply_today"]

    @admin.action(description="Apply today’s scheduled design to today’s tasks")
    def apply_today(self, request, queryset):
        from django.utils import timezone

        today = timezone.localdate()
        tasks = Task.objects.filter(due_date=today)
        if not tasks.exists():
            self.message_user(request, "No tasks for today.", level="WARNING")
            return
        scheduled_global = ScheduledDesign.objects.filter(
            due_date=today, recurring_task__isnull=True, store__isnull=True
        ).first()
        applied = 0
        for task in tasks:
            scheduled = None
            if task.recurring_task_id:
                scheduled = ScheduledDesign.objects.filter(
                    due_date=today, recurring_task=task.recurring_task, store__isnull=True
                ).first()
            if not scheduled:
                scheduled = scheduled_global
            if not scheduled:
                continue
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
            maybe_autogenerate_mockups(task)
            applied += 1
        if applied:
            self.message_user(request, f"Applied to {applied} task(s).")
        else:
            self.message_user(request, "No matching scheduled designs for today.", level="WARNING")

    def response_delete(self, request, obj_display, obj_id):
        return redirect("/admin/handoff/schedule/")


@admin.register(RecurringTask)
class RecurringTaskAdmin(admin.ModelAdmin):
    form = RecurringTaskForm
    list_display = ("title", "assigned_to", "active", "start_date")
    list_filter = ("active", "assigned_to")
    search_fields = ("title", "notes")
    actions = ["generate_today"]

    @admin.action(description="Generate today's tasks")
    def generate_today(self, request, queryset):
        today = timezone.localdate()
        created = 0
        for recurring in queryset:
            _, was_created = recurring.create_task_for_date(today)
            if was_created:
                created += 1
        self.message_user(request, f"Created {created} task(s) for {today}.")


@admin.register(TaskStep)
class TaskStepAdmin(admin.ModelAdmin):
    list_display = ("task", "order", "text", "done")
    list_filter = ("done",)
    search_fields = ("text",)


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ("task", "kind", "filename", "created_at")
    list_filter = ("kind",)


@admin.register(DesignFile)
class DesignFileAdmin(admin.ModelAdmin):
    list_display = ("filename", "store", "date_assigned", "status", "source_folder", "updated_at")
    list_filter = ("status", "source_folder", "store")
    search_fields = ("filename", "drive_file_id")


@admin.register(DesignHistory)
class DesignHistoryAdmin(admin.ModelAdmin):
    list_display = ("design_file", "store", "posted_date", "original_drive_file_id", "created_at")
    list_filter = ("posted_date", "store")
    search_fields = ("original_drive_file_id",)


@admin.register(SOPGuide)
class SOPGuideAdmin(admin.ModelAdmin):
    list_display = ("name", "context_route", "active", "updated_at")
    list_filter = ("active",)
    search_fields = ("name", "scribe_id_or_url", "context_route")


@admin.register(SOPReplyTemplate)
class SOPReplyTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "active", "updated_at")
    list_filter = ("active",)
    search_fields = ("name", "reply_text")


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("name", "order", "active", "updated_at")
    list_filter = ("active",)
    search_fields = ("name",)
    ordering = ("order", "name")


@admin.register(StoreMembership)
class StoreMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "store", "active", "updated_at")
    list_filter = ("active", "store")
    search_fields = ("user__username", "user__email", "store__name")
    autocomplete_fields = ("user", "store")


@admin.register(TaskPublication)
class TaskPublicationAdmin(admin.ModelAdmin):
    list_display = ("task", "store", "status", "listed_at", "updated_at")
    list_filter = ("status", "store")
    search_fields = ("task__title", "store__name", "listing_url")
    autocomplete_fields = ("task", "store")
