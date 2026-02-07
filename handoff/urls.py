from django.urls import path

from . import views

app_name = "handoff"

urlpatterns = [
    path("", views.home, name="home"),
    path("today/", views.today, name="today"),
    path("summary/", views.summary, name="summary"),
    path("stores/", views.store_calendars, name="store_calendars"),
    path(
        "scheduled-design/<int:design_id>/preview/",
        views.scheduled_design_preview,
        name="scheduled_design_preview",
    ),
    path("runway/", views.runway_status, name="runway_status"),
    path("idea-dump/", views.idea_dump, name="idea_dump"),
    path("sops/", views.sop_library, name="sop_library"),
    path("create/", views.create_task, name="create_task"),
    path("task/<int:task_id>/", views.task_detail, name="task_detail"),
    path("task/<int:task_id>/done/", views.toggle_manual_done, name="toggle_manual_done"),
    path("task/<int:task_id>/etsy/", views.etsy_listing_preview, name="etsy_listing_preview"),
    path("task/<int:task_id>/etsy/save/", views.etsy_listing_save, name="etsy_listing_save"),
    path("task/<int:task_id>/etsy/generate-tags/", views.etsy_generate_tags, name="etsy_generate_tags"),
    path("task/<int:task_id>/etsy/publications/save/", views.etsy_publications_save, name="etsy_publications_save"),
    path("task/<int:task_id>/steps/", views.task_steps_fragment, name="task_steps"),
    path("task/<int:task_id>/mockups/", views.task_mockups_fragment, name="task_mockups"),
    path("task/<int:task_id>/mockups/download/", views.download_mockups, name="download_mockups"),
    path("task/<int:task_id>/mockups/generate/", views.generate_mockups, name="generate_mockups"),
    path("task/<int:task_id>/mockups/progress/", views.mockup_generation_status, name="mockup_generation_status"),
    path("task/<int:task_id>/mockups/files/", views.mockup_files, name="mockup_files"),
    path("mockup/file/<str:file_id>/download/", views.mockup_file_download, name="mockup_file_download"),
    path("task/<int:task_id>/design/replace/", views.replace_design, name="replace_design"),
    path("mockup-template/<int:template_id>/preview/", views.preview_mockup_template, name="preview_mockup_template"),
    path("mockup-template/<int:template_id>/position/", views.mockup_template_position, name="mockup_template_position"),
    path("mockup-template/<int:template_id>/position/save/", views.mockup_template_position_save, name="mockup_template_position_save"),
    path("mockup-template/<int:template_id>/asset/<str:kind>/", views.mockup_template_asset, name="mockup_template_asset"),
    path("step/<int:step_id>/toggle/", views.toggle_step, name="toggle_step"),
    path("mockup/<int:slot_id>/upload/", views.upload_mockup, name="upload_mockup"),
]
