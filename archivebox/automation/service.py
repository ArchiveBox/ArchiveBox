"""Bounded, ordered rule processing; no capture or network work in ORM hooks."""

import logging
import threading
from contextvars import ContextVar
from contextlib import contextmanager
from urllib.parse import urlsplit

from django.db import connections, transaction
from django.utils import timezone

from archivebox.core.models import Snapshot, Tag
from .models import Rule, RuleRun, RuleEvent

logger = logging.getLogger(__name__)
_thread = None
_stop = threading.Event()
_suppress_events = ContextVar("automation_suppress_events", default=False)


@contextmanager
def suppress_rule_events():
    token = _suppress_events.set(True)
    try:
        yield
    finally:
        _suppress_events.reset(token)


def record_event(snapshot, kind, details=None):
    if _suppress_events.get():
        return None
    if not Rule.objects.filter(enabled=True, trigger=kind).exists():
        return None
    snapshot_id = getattr(snapshot, "pk", snapshot)
    if kind == "capture":
        return RuleEvent.objects.get_or_create(snapshot_id=snapshot_id, kind=kind, defaults={"details": details or {}})[0]
    return RuleEvent.objects.create(snapshot_id=snapshot_id, kind=kind, details=details or {})


def matches(rule, snapshot, event=None, *, values=None):
    conditions = list(rule.conditions.all())
    if not conditions:
        return False
    values = (
        values
        if values is not None
        else {
            "domain": [urlsplit(snapshot.url).hostname or ""],
            "url": [snapshot.url],
            "title": [snapshot.title or ""],
            "tag": snapshot.crawl.current_tag_names() if snapshot._state.adding else [tag.name for tag in snapshot.tags.all()],
            "permissions": [snapshot.config.get("PERMISSIONS", "")] if snapshot._state.adding else [snapshot.permissions],
            "event_tag": (event.details.get("tags", []) if event else []),
            "crawl_tag": snapshot.crawl.current_tag_names(),
            "crawl_label": [snapshot.crawl.label or ""],
        }
    )
    results = {}
    for condition in conditions:
        target = condition.value.casefold().strip()
        candidates = [str(value).casefold() for value in values[condition.field]]
        if condition.operator in ("in", "not_in"):
            targets = {value.strip() for value in target.replace("\n", ",").split(",") if value.strip()}
            matched = any(value in targets for value in candidates)
            if condition.operator == "not_in":
                matched = not matched
        elif condition.operator == "not_equals":
            matched = all(value != target for value in candidates)
        elif condition.operator == "not_contains":
            matched = all(target not in value for value in candidates)
        elif condition.operator == "equals":
            matched = any(value == target for value in candidates)
        elif condition.operator == "contains":
            matched = any(target in value for value in candidates)
        elif condition.operator == "starts":
            matched = any(value.startswith(target) for value in candidates)
        else:
            raise ValueError(f"Unknown operator: {condition.operator}")
        results.setdefault(condition.group, []).append(matched)

    def evaluate(group_key, mode):
        children = results.get(group_key, []) + [
            evaluate(key, group["match"]) for key, group in rule.groups.items() if group.get("parent", "") == group_key
        ]
        return bool(children) and (all(children) if mode == "all" else any(children))

    return evaluate("", rule.match)


def apply_rule(rule, snapshot, *, automatic=False, event=None):
    if rule.is_capture_configuration:
        raise ValueError("Capture configuration rules apply only before execution; use the read-only configuration preview.")
    # The audit and DB changes commit together. There is no filesystem or network
    # work in this short transaction. A crash cannot leave an applied rule unlogged.
    with suppress_rule_events(), transaction.atomic():
        if event and RuleRun.objects.filter(rule=rule, event=event).exists():
            return None
        matched = matches(rule, snapshot, event)
        changes = {}
        if matched:
            current_tags = {tag.name.casefold(): tag for tag in snapshot.tags.all()}
            for name in (name.strip() for name in rule.remove_tags.split(",") if name.strip()):
                if tag := current_tags.get(name.casefold()):
                    snapshot.tags.remove(tag)
                    changes.setdefault("removed_tags", []).append(tag.name)
            for name in (name.strip() for name in rule.add_tags.split(",") if name.strip()):
                tag, _ = Tag.get_or_create_by_name(name, defaults={"created_by": rule.created_by})
                if not snapshot.tags.filter(pk=tag.pk).exists():
                    snapshot.tags.add(tag)
                    changes.setdefault("added_tags", []).append(tag.name)
            if rule.folder_id and rule.folder_id != snapshot.folder_id:
                changes["folder"] = {"before": str(snapshot.folder_id) if snapshot.folder_id else None, "after": str(rule.folder_id)}
                Snapshot.objects.filter(pk=snapshot.pk).update(folder_id=rule.folder_id, modified_at=timezone.now())
                snapshot.folder_id = rule.folder_id
            if rule.permissions and rule.permissions != snapshot.permissions:
                changes["visibility"] = {"before": snapshot.permissions, "after": rule.permissions}
                config = dict(snapshot.config)
                config["PERMISSIONS"] = rule.permissions
                Snapshot.objects.filter(pk=snapshot.pk).update(config=config, modified_at=timezone.now())
                snapshot.refresh_from_db()
        return RuleRun.objects.create(
            rule=rule,
            rule_name=rule.name,
            snapshot=snapshot,
            automatic=automatic,
            matched=matched,
            changes=changes,
            event=event,
        )


def run_pending_rules(*, limit=25):
    rules = list(Rule.objects.filter(enabled=True).prefetch_related("conditions").select_related("created_by"))
    if not rules:
        return 0
    capture_rules = [rule for rule in rules if rule.trigger == "capture"]
    if capture_rules:
        earliest = min(rule.created_at for rule in capture_rules)
        for snapshot in (
            Snapshot.objects.filter(status=Snapshot.StatusChoices.SEALED, created_at__gte=earliest)
            .exclude(pk__in=RuleEvent.objects.filter(kind="capture").values("snapshot_id"))
            .order_by("created_at")[:limit]
        ):
            record_event(snapshot, "capture")
    events = (
        RuleEvent.objects.filter(processed_at__isnull=True, snapshot__status=Snapshot.StatusChoices.SEALED)
        .select_related("snapshot")
        .order_by("created_at", "pk")[:limit]
    )
    processed = 0
    for event in events:
        # Commit all actions and audit rows together. Rule mutations deliberately
        # do not emit further events, preventing recursive tag/folder loops.
        with suppress_rule_events(), transaction.atomic():
            if RuleEvent.objects.get(pk=event.pk).processed_at is not None:
                continue
            snapshot = event.snapshot
            stop = False
            for rule in rules:
                if (
                    rule.trigger != event.kind
                    or event.created_at < rule.created_at
                    or (event.kind == "capture" and snapshot.created_at < rule.created_at)
                ):
                    continue
                previous = RuleRun.objects.filter(rule=rule, event=event).first()
                if previous is None and event.kind == "capture":
                    previous = RuleRun.objects.filter(rule=rule, snapshot=snapshot, automatic=True, event__isnull=True).first()
                if stop:
                    if previous is None:
                        RuleRun.objects.create(
                            rule=rule,
                            rule_name=rule.name,
                            snapshot=snapshot,
                            event=event,
                            automatic=True,
                            changes={"skipped": "An earlier matching rule stopped processing."},
                        )
                    continue
                run = previous or apply_rule(rule, snapshot, automatic=True, event=event)
                processed += int(previous is None)
                stop = bool(run and run.matched and rule.stop_processing)
            RuleEvent.objects.filter(pk=event.pk).update(processed_at=timezone.now())
    return processed


def _background_run():
    try:
        while not _stop.is_set():
            try:
                run_pending_rules()
            except Exception:
                logger.exception("Automatic snapshot rules failed")
            _stop.wait(5)
    finally:
        connections.close_all()


def shutdown():
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)


def tick(*, daemon):
    global _thread
    if not daemon:
        return bool(run_pending_rules())
    if _thread is None or not _thread.is_alive():
        import atexit

        atexit.register(shutdown)
        _stop.clear()
        _thread = threading.Thread(target=_background_run, name="archivebox-automation", daemon=True)
        _thread.start()
    return False
