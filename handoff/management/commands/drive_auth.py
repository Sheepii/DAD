from django.core.management.base import BaseCommand

from handoff.drive import run_local_auth


class Command(BaseCommand):
    help = "Run local OAuth flow and save Drive token.json."

    def handle(self, *args, **options):
        token_path = run_local_auth()
        self.stdout.write(self.style.SUCCESS(f"Token saved to {token_path}"))
