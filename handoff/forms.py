import json
import re

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import (
    MockupTemplate,
    AdminNote,
    RecurringTask,
    Task,
    TaskTemplate,
    TemplateAttachment,
    extract_drive_id,
)


def _steps_to_text(steps) -> str:
    if isinstance(steps, list):
        return "\n".join(str(step).strip() for step in steps if str(step).strip())
    return ""


class StepListField(forms.CharField):
    def to_python(self, value):
        value = super().to_python(value)
        if not value:
            return []
        value = value.strip()
        if not value:
            return []
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(step).strip() for step in parsed if str(step).strip()]
        except json.JSONDecodeError:
            pass
        lines = [line.strip() for line in value.splitlines()]
        return [line for line in lines if line]


class TaskCreateForm(forms.ModelForm):
    steps_text = forms.CharField(
        label="Checklist steps (one per line)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
    )
    design_file = forms.FileField(required=False)

    class Meta:
        model = Task
        fields = [
            "title",
            "due_date",
            "assigned_to",
            "notes",
            "drive_design_file_id",
            "drive_mockup_folder_id",
            "video_url",
            "template",
        ]
        widgets = {
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.initial.get("due_date"):
            self.initial["due_date"] = timezone.localdate()
        if not self.initial.get("assigned_to"):
            self.initial["assigned_to"] = "Dad"
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")

    def clean_drive_design_file_id(self):
        value = self.cleaned_data.get("drive_design_file_id", "")
        return extract_drive_id(value)

    def clean_drive_mockup_folder_id(self):
        value = self.cleaned_data.get("drive_mockup_folder_id", "")
        return extract_drive_id(value)


class TaskTemplateForm(forms.ModelForm):
    default_steps = StepListField(
        label="Default steps (one per line)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
    )

    class Meta:
        model = TaskTemplate
        fields = [
            "name",
            "default_steps",
            "default_video_url",
            "sample_design_drive_file_id",
            "etsy_title_suffix",
            "etsy_description_default",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.default_steps:
            self.initial["default_steps"] = _steps_to_text(self.instance.default_steps)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")


class RecurringTaskForm(forms.ModelForm):
    assigned_to = forms.ChoiceField(label="Assigned to")
    default_steps = StepListField(
        label="Default steps (one per line)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
    )

    class Meta:
        model = RecurringTask
        fields = [
            "title",
            "assigned_to",
            "notes",
            "drive_design_file_id",
            "video_url",
            "template",
            "default_steps",
            "start_date",
            "active",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user_model = get_user_model()
        users = user_model.objects.filter(is_active=True).order_by("username")
        choices = [(user.username, user.get_username()) for user in users]
        current_assignee = (self.initial.get("assigned_to") or getattr(self.instance, "assigned_to", "") or "").strip()
        if current_assignee and current_assignee not in {value for value, _ in choices}:
            choices.insert(0, (current_assignee, f"{current_assignee} (legacy)"))
        if choices:
            self.fields["assigned_to"].choices = choices
        else:
            self.fields["assigned_to"].choices = [("Dad", "Dad")]
        if not self.initial.get("assigned_to"):
            self.initial["assigned_to"] = choices[0][0] if choices else "Dad"
        if self.instance and self.instance.default_steps:
            self.initial["default_steps"] = _steps_to_text(self.instance.default_steps)
        if not self.initial.get("start_date"):
            self.initial["start_date"] = timezone.localdate()
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")

    def clean_drive_design_file_id(self):
        value = self.cleaned_data.get("drive_design_file_id", "")
        return extract_drive_id(value)

    def clean_assigned_to(self):
        return (self.cleaned_data.get("assigned_to") or "").strip()


class MockupTemplateForm(forms.ModelForm):
    background_upload = forms.FileField(required=False)
    overlay_upload = forms.FileField(required=False)
    mask_upload = forms.FileField(required=False)

    class Meta:
        model = MockupTemplate
        fields = [
            "template",
            "order",
            "label",
            "background_drive_file_id",
            "overlay_drive_file_id",
            "mask_drive_file_id",
            "overlay_position",
            "design_x",
            "design_y",
            "design_width",
            "design_height",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")


class TaskAdminForm(forms.ModelForm):
    design_upload = forms.FileField(required=False, label="Upload new design")

    class Meta:
        model = Task
        fields = "__all__"


class TemplateAttachmentForm(forms.ModelForm):
    attachment_upload = forms.FileField(required=False, label="Upload file")
    drive_file_id = forms.CharField(required=False, label="Drive file id")

    class Meta:
        model = TemplateAttachment
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        uploaded = cleaned.get("attachment_upload")
        drive_file_id = (cleaned.get("drive_file_id") or "").strip()
        if not uploaded and not drive_file_id:
            self.add_error("drive_file_id", "Upload a file or enter a Drive file ID.")
        return cleaned

    def clean_drive_file_id(self):
        value = (self.cleaned_data.get("drive_file_id") or "").strip()
        uploaded = self.files.get(self.add_prefix("attachment_upload"))
        if uploaded:
            # File upload takes precedence; Drive ID will be set after upload.
            return ""
        value = extract_drive_id(value)
        if not value:
            return ""
        # Google Drive IDs are URL-safe tokens; short numeric placeholders are invalid.
        if not re.match(r"^[A-Za-z0-9_-]{15,}$", value):
            raise forms.ValidationError("Enter a valid Google Drive file ID or upload a file.")
        return value


class AdminNoteForm(forms.ModelForm):
    class Meta:
        model = AdminNote
        fields = ["title", "body"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "vTextField wide"}),
            "body": forms.Textarea(attrs={"class": "vLargeTextField wide", "rows": 6}),
        }
