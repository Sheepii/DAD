import json

from django import forms
from django.utils import timezone

from .models import MockupTemplate, RecurringTask, Task, TaskTemplate, extract_drive_id


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
