from __future__ import annotations

import datetime as dt

from .models import DesignFile, ScheduledDesign


def backfill_scheduled_designs(
    *,
    store=None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> int:
    queryset = (
        DesignFile.objects.filter(
            status__in=[DesignFile.STATUS_SCHEDULED, DesignFile.STATUS_ACTIVE],
            date_assigned__isnull=False,
        )
        .exclude(drive_file_id="")
        .order_by("date_assigned", "updated_at", "id")
    )
    if store is not None:
        queryset = queryset.filter(store=store)
    if date_from is not None:
        queryset = queryset.filter(date_assigned__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(date_assigned__lte=date_to)

    desired: dict[tuple[dt.date, int | None], str] = {}
    for design in queryset:
        desired[(design.date_assigned, design.store_id)] = design.drive_file_id

    if not desired:
        return 0

    existing = set(
        ScheduledDesign.objects.filter(
            recurring_task__isnull=True,
            due_date__in=[key[0] for key in desired.keys()],
            store_id__in=[key[1] for key in desired.keys() if key[1] is not None],
        ).values_list("due_date", "store_id")
    )
    if any(key[1] is None for key in desired.keys()):
        existing_none = set(
            ScheduledDesign.objects.filter(
                recurring_task__isnull=True,
                due_date__in=[key[0] for key in desired.keys() if key[1] is None],
                store__isnull=True,
            ).values_list("due_date", "store_id")
        )
        existing.update(existing_none)

    to_create = []
    for (due_date, store_id), drive_design_file_id in desired.items():
        key = (due_date, store_id)
        if key in existing:
            continue
        to_create.append(
            ScheduledDesign(
                due_date=due_date,
                recurring_task=None,
                store_id=store_id,
                drive_design_file_id=drive_design_file_id,
            )
        )

    if not to_create:
        return 0

    ScheduledDesign.objects.bulk_create(to_create, ignore_conflicts=True)
    return len(to_create)
