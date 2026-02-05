from django.db import models
import re

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
        if self.drive_design_file_id:
            self.drive_design_file_id = extract_drive_id(self.drive_design_file_id)
        if self.drive_mockup_folder_id:
            self.drive_mockup_folder_id = extract_drive_id(
                self.drive_mockup_folder_id
            )
        super().save(*args, **kwargs)

    def required_mockup_orders(self) -> set[int]:
        return set()

    def required_mockups_done(self) -> bool:
        return True

    def ensure_mockup_slots(self, count: int = 6) -> None:
        existing = self.mockup_slots.count()
        if existing >= count:
            return
        slots = [
            MockupSlot(task=self, order=idx + 1)
            for idx in range(existing, count)
        ]
        MockupSlot.objects.bulk_create(slots)

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
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.drive_file_id:
            self.drive_file_id = extract_drive_id(self.drive_file_id)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.label or self.filename or self.drive_file_id


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
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.drive_design_file_id:
            self.drive_design_file_id = extract_drive_id(self.drive_design_file_id)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        label = self.recurring_task.title if self.recurring_task else "All tasks"
        return f"{label} - {self.due_date}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["due_date", "recurring_task"],
                name="unique_scheduled_design_per_day_task",
            )
        ]


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
