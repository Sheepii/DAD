from django.test import SimpleTestCase, TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from .etsy import normalize_tags_csv, suggest_title_from_filename, validate_tags
from .models import ScheduledDesign, Store, StoreMembership, Task, TaskPublication


class EtsyTagValidationTests(SimpleTestCase):
    def test_validate_ok(self):
        tags = [f"Tag {i}" for i in range(1, 14)]
        result = validate_tags(tags)
        self.assertTrue(result.ok)

    def test_validate_requires_13(self):
        result = validate_tags(["one", "two"])
        self.assertFalse(result.ok)
        self.assertIn("Expected exactly 13 tags", result.errors[0])

    def test_validate_rejects_special_chars(self):
        tags = [f"Tag {i}" for i in range(1, 14)]
        tags[0] = "bad-tag"
        result = validate_tags(tags)
        self.assertFalse(result.ok)
        self.assertIn(1, result.per_tag_errors)

    def test_normalize_tags_csv(self):
        raw = " one, two , ,three "
        self.assertEqual(normalize_tags_csv(raw), ["one", "two", "three"])

    def test_suggest_title(self):
        title = suggest_title_from_filename("my_design_file.png", suffix="T-Shirt")
        self.assertEqual(title, "my design file T-Shirt")


class StorePublicationTests(TestCase):
    def test_ensure_publications_creates_for_active_stores(self):
        Store.objects.create(name="Store A", order=1, active=True)
        Store.objects.create(name="Store B", order=2, active=True)
        Store.objects.create(name="Store C", order=3, active=False)
        task = Task.objects.create(title="Test", due_date=timezone.localdate())
        created = task.ensure_publications()
        self.assertEqual(created, 2)
        self.assertEqual(task.publications.count(), 2)

    def test_listed_sets_listed_at(self):
        store = Store.objects.create(name="Store A", order=1, active=True)
        task = Task.objects.create(title="Test", due_date=timezone.localdate())
        pub = TaskPublication.objects.create(task=task, store=store)
        self.assertIsNone(pub.listed_at)
        was_listed = pub.status == TaskPublication.STATUS_LISTED
        pub.status = TaskPublication.STATUS_LISTED
        pub.mark_listed_if_needed(was_listed=was_listed)
        pub.save()
        self.assertIsNotNone(pub.listed_at)


class ManualDoneTests(TestCase):
    def test_manual_done_forces_done_status(self):
        task = Task.objects.create(title="Test", due_date=timezone.localdate())
        task.manual_done = True
        task.save(update_fields=["manual_done"])
        task.refresh_status()
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_DONE)


class TodayStoreAccessTests(TestCase):
    def test_today_requires_login(self):
        response = self.client.get("/today/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_non_staff_user_sees_tasks_for_assigned_store_only(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(username="dad", password="pass12345")
        store_a = Store.objects.create(name="Store A", order=1, active=True)
        store_b = Store.objects.create(name="Store B", order=2, active=True)
        StoreMembership.objects.create(user=user, store=store_a, active=True)

        task = Task.objects.create(title="Store Task", due_date=timezone.localdate())
        ScheduledDesign.objects.create(
            due_date=timezone.localdate(),
            recurring_task=None,
            store=store_a,
            drive_design_file_id="drive-id-1",
        )
        ScheduledDesign.objects.create(
            due_date=timezone.localdate(),
            recurring_task=None,
            store=store_b,
            drive_design_file_id="drive-id-2",
        )

        self.client.force_login(user)
        response = self.client.get("/today/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, task.title)
