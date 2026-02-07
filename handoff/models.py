from django.db import models
import re
from django.conf import settings

from django.utils import timezone


class TaskTemplate(models.Model):
    name = models.CharField(max_length=200)
    default_steps = models.JSONField(
        blank=True,
        null=True,
        help_text="List of step strings, e.g. [\"Step 1\", \"Step 2\"]",
    )
    default_video_url = models.URLField(blank=True)
    sample_design_drive_file_id = models.CharField(max_length=200, blank=True)
    etsy_title_suffix = models.CharField(
        max_length=50,
        blank=True,
        help_text="Appended to suggested Etsy titles, e.g. 'T-Shirt'.",
    )
    etsy_description_default = models.TextField(
        blank=True,
        help_text="Default Etsy description for this product type (template).",
    )

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if self.sample_design_drive_file_id:
            self.sample_design_drive_file_id = extract_drive_id(
                self.sample_design_drive_file_id
            )
        super().save(*args, **kwargs)


def extract_drive_id(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    if "?" in value:
        value = value.split("?", 1)[0].strip()
    if "&" in value:
        value = value.split("&", 1)[0].strip()
    if value.startswith("http"):
        match = re.search(r"/d/([a-zA-Z0-9_-]+)", value)
        if match:
            return match.group(1)
        match = re.search(r"/folders/([a-zA-Z0-9_-]+)", value)
        if match:
            return match.group(1)
        match = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", value)
        if match:
            return match.group(1)
    return value


class Task(models.Model):
    STATUS_NEW = "NEW"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_DONE = "DONE"

    STATUS_CHOICES = [
        (STATUS_NEW, "New"),
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_DONE, "Done"),
    ]

    title = models.CharField(max_length=200)
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW)
    assigned_to = models.CharField(max_length=100, default="Dad")
    notes = models.TextField(blank=True)
    drive_design_file_id = models.CharField(max_length=200, blank=True)
    drive_mockup_folder_id = models.CharField(max_length=200, blank=True)
    mockups_generated_design_id = models.CharField(max_length=200, blank=True)
    video_url = models.URLField(blank=True)
    etsy_title = models.CharField(max_length=140, blank=True)
    etsy_description = models.TextField(blank=True)
    etsy_tags = models.JSONField(
        blank=True,
        null=True,
        help_text="List of 13 tags (strings). Each tag must be under 20 characters.",
    )
    manual_done = models.BooleanField(
        default=False,
        help_text="Manual override for marking the task done (used for Dad view).",
    )
    template = models.ForeignKey(
        TaskTemplate, on_delete=models.SET_NULL, null=True, blank=True
    )
    recurring_task = models.ForeignKey(
        "RecurringTask", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.title} ({self.due_date})"

    @property
    def total_steps(self) -> int:
        return self.steps.count()

    @property
    def done_steps(self) -> int:
        return self.steps.filter(done=True).count()

    @property
    def progress_text(self) -> str:
        return f"{self.done_steps}/{self.total_steps} steps done"

    @property
    def all_steps_done(self) -> bool:
        total = self.total_steps
        return total > 0 and self.done_steps == total

    def refresh_status(self) -> None:
        if self.manual_done:
            self.status = Task.STATUS_DONE
            self.save(update_fields=["status", "updated_at"])
            return
        if self.all_steps_done:
            self.status = Task.STATUS_DONE
        elif self.done_steps > 0:
            self.status = Task.STATUS_IN_PROGRESS
        else:
            self.status = Task.STATUS_NEW
        self.save(update_fields=["status", "updated_at"])

    def seed_steps_from_template(self) -> int:
        if not self.template or not self.template.default_steps:
            return 0
        steps = self.template.default_steps
        if not isinstance(steps, list):
            return 0
        created = []
        for order, text in enumerate(steps, start=1):
            if not text:
                continue
            created.append(
                TaskStep(
                    task=self,
                    order=order,
                    text=str(text).strip(),
                )
            )
        if created:
            TaskStep.objects.bulk_create(created)
        return len(created)

    def save(self, *args, **kwargs):
        previous_status = None
        if self.pk:
            previous_status = (
                Task.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            )
        if self.drive_design_file_id:
            self.drive_design_file_id = extract_drive_id(self.drive_design_file_id)
        if self.drive_mockup_folder_id:
            self.drive_mockup_folder_id = extract_drive_id(
                self.drive_mockup_folder_id
            )
        super().save(*args, **kwargs)
        if previous_status != Task.STATUS_DONE and self.status == Task.STATUS_DONE:
            self.record_design_posted()

    def record_design_posted(self) -> None:
        drive_id = (self.drive_design_file_id or "").strip()
        if not drive_id:
            return
        design = DesignFile.objects.filter(drive_file_id=drive_id).first()
        store = design.store if design else None
        if not store:
            listed = (
                self.publications.filter(status=TaskPublication.STATUS_LISTED)
                .select_related("store")
                .order_by("store__order", "store__name", "id")
            )
            if listed.count() == 1:
                store = listed.first().store
            else:
                active = Store.objects.filter(active=True).order_by("order", "name")
                if active.count() == 1:
                    store = active.first()
        if not store:
            match = (
                ScheduledDesign.objects.filter(
                    due_date=self.due_date, drive_design_file_id=drive_id, store__isnull=False
                )
                .select_related("store")
                .first()
            )
            if match:
                store = match.store
        if design:
            updates = []
            if design.status != DesignFile.STATUS_POSTED:
                design.status = DesignFile.STATUS_POSTED
                updates.append("status")
            if not design.date_assigned:
                design.date_assigned = self.due_date
                updates.append("date_assigned")
            if store and design.store_id != store.id:
                design.store = store
                updates.append("store")
            if updates:
                design.save(update_fields=updates + ["updated_at"])
        exists = DesignHistory.objects.filter(
            posted_date=self.due_date, original_drive_file_id=drive_id
        ).exists()
        if not exists:
            DesignHistory.objects.create(
                design_file=design,
                posted_date=self.due_date,
                original_drive_file_id=drive_id,
                store=store,
                notes=f"Task {self.id} marked done.",
            )
        try:
            from .drive import archive_design_file

            result = archive_design_file(drive_id, store=store)
            if design and result.get("moved"):
                updates = []
                new_name = result.get("name")
                if new_name and design.filename != new_name:
                    design.filename = new_name
                    updates.append("filename")
                if design.source_folder != "Done":
                    design.source_folder = "Done"
                    updates.append("source_folder")
                if updates:
                    design.save(update_fields=updates + ["updated_at"])
        except Exception:
            # Never block the task flow if Drive is unavailable.
            return

    def required_mockup_orders(self) -> set[int]:
        if not self.template_id:
            return set()
        try:
            orders = list(
                self.template.mockup_templates.values_list("order", flat=True)
            )
        except Exception:
            return set()
        return {int(order) for order in orders if order}

    def required_mockups_done(self) -> bool:
        required = self.required_mockup_orders()
        if not required:
            return True
        filled = set(
            self.mockup_slots.exclude(drive_file_id="").values_list("order", flat=True)
        )
        return required.issubset({int(o) for o in filled if o})

    def ensure_mockup_slots(self, count: int = 6) -> None:
        existing = self.mockup_slots.count()
        if existing >= count:
            return
        slots = [
            MockupSlot(task=self, order=idx + 1)
            for idx in range(existing, count)
        ]
        MockupSlot.objects.bulk_create(slots)

    def ensure_publications(self) -> int:
        stores = list(Store.objects.filter(active=True).order_by("order", "name"))
        if not stores:
            return 0
        existing_store_ids = set(
            TaskPublication.objects.filter(task=self).values_list("store_id", flat=True)
        )
        to_create = [
            TaskPublication(task=self, store=store)
            for store in stores
            if store.id not in existing_store_ids
        ]
        if to_create:
            TaskPublication.objects.bulk_create(to_create)
        return len(to_create)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["recurring_task", "due_date"],
                name="unique_recurring_task_per_day",
            )
        ]


class TaskStep(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveIntegerField(default=0)
    text = models.CharField(max_length=300)
    done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return self.text

    def toggle(self) -> None:
        self.done = not self.done
        self.done_at = timezone.now() if self.done else None
        self.save(update_fields=["done", "done_at"])


class Attachment(models.Model):
    KIND_DESIGN = "DESIGN"
    KIND_MOCKUP = "MOCKUP"
    KIND_OTHER = "OTHER"

    KIND_CHOICES = [
        (KIND_DESIGN, "Design"),
        (KIND_MOCKUP, "Mockup"),
        (KIND_OTHER, "Other"),
    ]

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attachments")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    drive_file_id = models.CharField(max_length=200)
    filename = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.kind} - {self.filename or self.drive_file_id}"


class TemplateAttachment(models.Model):
    template = models.ForeignKey(
        TaskTemplate, on_delete=models.CASCADE, related_name="attachments"
    )
    label = models.CharField(max_length=200, blank=True)
    drive_file_id = models.CharField(max_length=200)
    filename = models.CharField(max_length=255, blank=True)
    include_in_mockup_zip = models.BooleanField(
        default=True,
        help_text="Include this file in front-end mockup ZIP downloads.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.drive_file_id:
            self.drive_file_id = extract_drive_id(self.drive_file_id)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.label or self.filename or self.drive_file_id


class Store(models.Model):
    name = models.CharField(max_length=200, unique=True)
    order = models.PositiveIntegerField(default=1)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "name", "id"]

    def __str__(self) -> str:
        return self.name


class StoreMembership(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="store_memberships"
    )
    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="memberships"
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "store"], name="unique_user_store_membership")
        ]
        ordering = ["store__order", "store__name", "user__username", "id"]

    def __str__(self) -> str:
        return f"{self.user} -> {self.store}"


class TaskPublication(models.Model):
    STATUS_QUEUED = "QUEUED"
    STATUS_LISTED = "LISTED"

    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_LISTED, "Listed"),
    ]

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="publications")
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="publications")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    listing_url = models.URLField(blank=True)
    listed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["store__order", "store__name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["task", "store"],
                name="unique_task_store_publication",
            )
        ]

    def __str__(self) -> str:
        return f"{self.task} -> {self.store} ({self.status})"

    def mark_listed_if_needed(self, was_listed: bool) -> None:
        if self.status == self.STATUS_LISTED and not was_listed:
            self.listed_at = timezone.now()


class MockupSlot(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="mockup_slots")
    order = models.PositiveIntegerField(default=1)
    label = models.CharField(max_length=200, blank=True)
    drive_file_id = models.CharField(max_length=200, blank=True)
    filename = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]

    def save(self, *args, **kwargs):
        if self.drive_file_id:
            self.drive_file_id = extract_drive_id(self.drive_file_id)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.label or f"Mockup {self.order}"


class MockupTemplate(models.Model):
    template = models.ForeignKey(
        TaskTemplate, on_delete=models.CASCADE, related_name="mockup_templates"
    )
    order = models.PositiveIntegerField(default=1)
    label = models.CharField(max_length=200, blank=True)
    background_drive_file_id = models.CharField(max_length=200)
    overlay_drive_file_id = models.CharField(max_length=200, blank=True)
    mask_drive_file_id = models.CharField(max_length=200, blank=True)
    overlay_position = models.CharField(
        max_length=10,
        choices=[("OVER", "Overlay above design"), ("UNDER", "Overlay below design")],
        default="OVER",
    )
    design_x = models.PositiveIntegerField(default=0)
    design_y = models.PositiveIntegerField(default=0)
    design_width = models.PositiveIntegerField(default=4000)
    design_height = models.PositiveIntegerField(default=4000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def save(self, *args, **kwargs):
        if self.background_drive_file_id:
            self.background_drive_file_id = extract_drive_id(
                self.background_drive_file_id
            )
        if self.overlay_drive_file_id:
            self.overlay_drive_file_id = extract_drive_id(
                self.overlay_drive_file_id
            )
        if self.mask_drive_file_id:
            self.mask_drive_file_id = extract_drive_id(self.mask_drive_file_id)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.label or f"Mockup Template {self.order}"


class MockupDesignBox(models.Model):
    template = models.ForeignKey(
        MockupTemplate, on_delete=models.CASCADE, related_name="design_boxes"
    )
    order = models.PositiveIntegerField(default=1)
    x = models.PositiveIntegerField(default=0)
    y = models.PositiveIntegerField(default=0)
    width = models.PositiveIntegerField(default=4000)
    height = models.PositiveIntegerField(default=4000)
    rotation = models.FloatField(default=0.0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"Box {self.order}"


class ScheduledDesign(models.Model):
    due_date = models.DateField()
    recurring_task = models.ForeignKey(
        "RecurringTask", on_delete=models.CASCADE, null=True, blank=True
    )
    drive_design_file_id = models.CharField(max_length=200)
    store = models.ForeignKey(
        "Store", on_delete=models.SET_NULL, null=True, blank=True, related_name="scheduled_designs"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.drive_design_file_id:
            self.drive_design_file_id = extract_drive_id(self.drive_design_file_id)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        label = self.recurring_task.title if self.recurring_task else "All tasks"
        store_label = f" ({self.store.name})" if self.store else ""
        return f"{label}{store_label} - {self.due_date}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["due_date", "recurring_task", "store"],
                name="unique_scheduled_design_per_day_task_store",
            )
        ]


class DesignFile(models.Model):
    STATUS_DUMPED = "DUMPED"
    STATUS_SCHEDULED = "SCHEDULED"
    STATUS_ACTIVE = "ACTIVE"
    STATUS_POSTED = "POSTED"
    STATUS_ERROR = "ERROR"
    STATUS_RECYCLED = "RECYCLED"

    STATUS_CHOICES = [
        (STATUS_DUMPED, "Dumped"),
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_POSTED, "Posted"),
        (STATUS_ERROR, "Error"),
        (STATUS_RECYCLED, "Recycled"),
    ]

    filename = models.CharField(max_length=255)
    date_assigned = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    drive_file_id = models.CharField(max_length=200, blank=True)
    store = models.ForeignKey(
        "Store", on_delete=models.SET_NULL, null=True, blank=True, related_name="design_files"
    )
    size_mb = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    ext = models.CharField(max_length=10, blank=True)
    source_folder = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.filename} ({self.status})"


class DesignHistory(models.Model):
    design_file = models.ForeignKey(
        DesignFile, on_delete=models.SET_NULL, null=True, blank=True, related_name="history"
    )
    posted_date = models.DateField()
    original_drive_file_id = models.CharField(max_length=200, blank=True)
    store = models.ForeignKey(
        "Store", on_delete=models.SET_NULL, null=True, blank=True, related_name="design_history"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.design_file or 'Design'} - {self.posted_date}"


class SOPGuide(models.Model):
    name = models.CharField(max_length=200)
    scribe_id_or_url = models.CharField(max_length=300)
    context_route = models.CharField(max_length=200, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name


class SOPReplyTemplate(models.Model):
    name = models.CharField(max_length=200)
    trigger_keywords = models.JSONField(
        blank=True,
        null=True,
        help_text="List of keywords/phrases that match a customer message.",
    )
    reply_text = models.TextField()
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name


class AppSettings(models.Model):
    drive_root_folder_id = models.CharField(max_length=200, blank=True)
    drive_credentials_file_path = models.CharField(max_length=500, blank=True)
    drive_token_file_path = models.CharField(max_length=500, blank=True)
    drive_use_service_account = models.BooleanField(default=False)
    drive_service_account_file_path = models.CharField(max_length=500, blank=True)
    auto_generate_mockups = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return "App Settings"

    @classmethod
    def get_solo(cls):
        obj = cls.objects.first()
        if obj:
            return obj
        return cls.objects.create()

    def save(self, *args, **kwargs):
        if self.drive_root_folder_id:
            self.drive_root_folder_id = extract_drive_id(self.drive_root_folder_id)
        super().save(*args, **kwargs)


class AdminNote(models.Model):
    title = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admin_notes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        timestamp = self.created_at.strftime("%Y-%m-%d %H:%M")
        return self.title or f"Admin note ({timestamp})"


class RecurringTask(models.Model):
    title = models.CharField(max_length=200)
    assigned_to = models.CharField(max_length=100, default="Dad")
    notes = models.TextField(blank=True)
    drive_design_file_id = models.CharField(max_length=200, blank=True)
    video_url = models.URLField(blank=True)
    template = models.ForeignKey(
        TaskTemplate, on_delete=models.SET_NULL, null=True, blank=True
    )
    default_steps = models.JSONField(
        blank=True,
        null=True,
        help_text="List of step strings, overrides template steps if set.",
    )
    start_date = models.DateField(default=timezone.localdate)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.title} ({self.assigned_to})"

    def save(self, *args, **kwargs):
        if self.drive_design_file_id:
            self.drive_design_file_id = extract_drive_id(self.drive_design_file_id)
        super().save(*args, **kwargs)

    def step_list(self) -> list[str]:
        if isinstance(self.default_steps, list) and self.default_steps:
            return [str(step).strip() for step in self.default_steps if step]
        if self.template and isinstance(self.template.default_steps, list):
            return [str(step).strip() for step in self.template.default_steps if step]
        return []

    def create_task_for_date(self, due_date):
        if not self.active or due_date < self.start_date:
            return None, False
        task, created = Task.objects.get_or_create(
            recurring_task=self,
            due_date=due_date,
            defaults={
                "title": self.title,
                "assigned_to": self.assigned_to,
                "notes": self.notes,
                "drive_design_file_id": self.drive_design_file_id,
                "video_url": self.video_url,
                "template": self.template,
            },
        )
        if created and not task.steps.exists():
            steps = self.step_list()
            if steps:
                TaskStep.objects.bulk_create(
                    [
                        TaskStep(task=task, order=idx + 1, text=text)
                        for idx, text in enumerate(steps)
                    ]
                )
            else:
                task.seed_steps_from_template()
        if created:
            task.ensure_publications()
        return task, created

    @classmethod
    def generate_for_date(cls, due_date, assignee: str | None = None) -> int:
        queryset = cls.objects.filter(active=True, start_date__lte=due_date)
        if assignee:
            queryset = queryset.filter(assigned_to=assignee)
        created_count = 0
        for recurring in queryset:
            _, created = recurring.create_task_for_date(due_date)
            if created:
                created_count += 1
        return created_count
