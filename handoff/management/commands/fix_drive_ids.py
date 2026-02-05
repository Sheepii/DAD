from django.core.management.base import BaseCommand

from handoff.models import Attachment, RecurringTask, Task, extract_drive_id


class Command(BaseCommand):
    help = "Normalize stored Google Drive IDs when full links were pasted."

    def handle(self, *args, **options):
        updated = 0

        for task in Task.objects.exclude(drive_design_file_id=""):
            normalized = extract_drive_id(task.drive_design_file_id)
            if normalized != task.drive_design_file_id:
                task.drive_design_file_id = normalized
                task.save(update_fields=["drive_design_file_id"])
                updated += 1

        for task in Task.objects.exclude(drive_mockup_folder_id=""):
            normalized = extract_drive_id(task.drive_mockup_folder_id)
            if normalized != task.drive_mockup_folder_id:
                task.drive_mockup_folder_id = normalized
                task.save(update_fields=["drive_mockup_folder_id"])
                updated += 1

        for recurring in RecurringTask.objects.exclude(drive_design_file_id=""):
            normalized = extract_drive_id(recurring.drive_design_file_id)
            if normalized != recurring.drive_design_file_id:
                recurring.drive_design_file_id = normalized
                recurring.save(update_fields=["drive_design_file_id"])
                updated += 1

        for attachment in Attachment.objects.exclude(drive_file_id=""):
            normalized = extract_drive_id(attachment.drive_file_id)
            if normalized != attachment.drive_file_id:
                attachment.drive_file_id = normalized
                attachment.save(update_fields=["drive_file_id"])
                updated += 1

        from handoff.models import AppSettings

        for settings_obj in AppSettings.objects.exclude(drive_root_folder_id=""):
            normalized = extract_drive_id(settings_obj.drive_root_folder_id)
            if normalized != settings_obj.drive_root_folder_id:
                settings_obj.drive_root_folder_id = normalized
                settings_obj.save(update_fields=["drive_root_folder_id"])
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} record(s)."))
