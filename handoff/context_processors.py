from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from .models import DesignFile, ScheduledDesign, SOPGuide, Store


def _compute_runway_status(store: Store | None = None) -> dict:
    today = timezone.localdate()
    threshold = int(getattr(settings, "DESIGN_RUNWAY_THRESHOLD", 5))

    dates = list(
        DesignFile.objects.filter(
            date_assigned__gte=today,
            status__in=[DesignFile.STATUS_SCHEDULED, DesignFile.STATUS_ACTIVE],
            **({"store": store} if store else {}),
        )
        .values_list("date_assigned", flat=True)
        .distinct()
    )

    if not dates:
        dates = list(
            ScheduledDesign.objects.filter(
                due_date__gte=today, recurring_task__isnull=True, **({"store": store} if store else {})
            )
            .values_list("due_date", flat=True)
            .distinct()
        )

    days_remaining = len(dates)
    exhaustion_date = max(dates) if dates else None
    return {
        "days_remaining": days_remaining,
        "exhaustion_date": exhaustion_date,
        "threshold": threshold,
        "below_threshold": days_remaining < threshold,
    }


def _match_active_sop(path: str):
    path_lower = (path or "").lower()
    for sop in SOPGuide.objects.filter(active=True).order_by("name", "id"):
        route = (sop.context_route or "").strip()
        if not route:
            continue
        if route.startswith("/") and path.startswith(route):
            return sop
        if route.lower() in path_lower:
            return sop
    return None


def _build_sop_embed_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return f"https://scribehow.com/embed/{value}?as=scroll"


def handoff_context(request):
    context = {}
    try:
        if request.user.is_authenticated:
            if request.user.is_staff or request.user.is_superuser:
                stores = list(Store.objects.filter(active=True).order_by("order", "name"))
            else:
                stores = list(
                    Store.objects.filter(
                        active=True,
                        memberships__user=request.user,
                        memberships__active=True,
                    )
                    .distinct()
                    .order_by("order", "name")
                )
        else:
            stores = []
        context["store_options"] = stores
        store_id = request.GET.get("store")
        current_store = None
        if store_id:
            try:
                store_id_int = int(store_id)
                current_store = next((s for s in stores if s.id == store_id_int), None)
            except ValueError:
                current_store = None
        context["current_store"] = current_store
    except Exception:
        context["store_options"] = []
        context["current_store"] = None

    try:
        context["runway"] = _compute_runway_status(context.get("current_store"))
    except Exception:
        context["runway"] = None

    try:
        active = _match_active_sop(request.path)
        if active:
            context["active_sop"] = active
            context["active_sop_embed_url"] = _build_sop_embed_url(
                active.scribe_id_or_url
            )
    except Exception:
        pass

    return context
