"""Bounded, atomic consolidation of tag identities and their Snapshot links."""

from html import unescape

from django.db import transaction

from archivebox.core.models import Folder, SnapshotTag, Tag
from archivebox.core.tag_util import normalize_tag_name

MERGE_MAX_TAGS = 50
MERGE_MAX_LINKS = 2500


def _folded_tag_names(value):
    return {name.strip().casefold() for name in value.split(",") if name.strip()}


def _folder_tag_condition_matches(node, affected):
    if not isinstance(node, dict):
        return False
    if "op" in node:
        return any(_folder_tag_condition_matches(child, affected) for child in node.get("rules") or ())
    field = node.get("field") or ""
    if field != "tags" and not field.startswith("tags__"):
        return False
    lookup = node.get("lookup")
    # Every affected snapshot retains a tag; simple presence/absence cannot change.
    if field == "tags" and lookup in {"isnull", "present"}:
        return False
    if field in {"tags", "tags__id", "tags__pk"}:
        actual = {str(tag_id) for tag_id, _name in affected if tag_id is not None}
    elif field == "tags__name":
        actual = {name.casefold() for _tag_id, name in affected}
    else:
        # Other Tag fields (creator, timestamps, …) can also change since an
        # existing link will point at a different record after the merge.
        return True
    value = node.get("value")
    if lookup in {"in", "not_in"}:
        values = value if isinstance(value, list) else str(value).split(",")
        return bool(actual.intersection(str(item).strip().casefold() for item in values))
    term = str(value).casefold()
    if lookup in {"exact", "not_exact"}:
        return term in actual
    if lookup in {"icontains", "not_contains"}:
        return any(term in candidate for candidate in actual)
    if lookup == "istartswith":
        return any(candidate.startswith(term) for candidate in actual)
    if lookup == "iendswith":
        return any(candidate.endswith(term) for candidate in actual)
    return True


def _check_merge_dependencies(retired, target, final_name, memberships):
    from archivebox.api.models import OutboundWebhook
    from archivebox.crawls.models import Crawl, CrawlSchedule
    from archivebox.importers.models import ImporterSource

    def crawl_tag_names(value):
        return {name.casefold() for name in Crawl.parse_tag_names(value)}

    affected = [*retired, (target.pk if target else None, final_name)]
    retired_names = {name.casefold() for _pk, name in retired}
    for folder_id, rules in Folder.objects.exclude(rules__isnull=True).values_list("pk", "rules").iterator():
        if _folder_tag_condition_matches(rules, affected):
            raise ValueError(f"Update Smart Folder {folder_id}: its tag filter would change. No tags were merged.")
    rules = OutboundWebhook.objects.filter(enabled=True).values_list("pk", "ref", "signal", "relationship", "actions")
    missed_events = {}
    for rule_id, ref, signal, relationship, actions in rules.iterator():
        if ref == "core.snapshot" and relationship in {"", "*", "tags"} and signal in {"M2M_ADD", "M2M_REMOVE"}:
            if signal not in missed_events:
                changed = memberships
                if signal == "M2M_ADD" and target:
                    existing = SnapshotTag.objects.filter(tag_id=target.pk).order_by().values("snapshot_id")
                    changed = memberships.exclude(snapshot_id__in=existing)
                missed_events[signal] = changed.exists()
            if missed_events[signal]:
                raise ValueError(f"Update Rule {rule_id}: it acts on Snapshot tag changes. No tags were merged.")
        if ref == "core.tag" and (signal == "DELETE" or (signal == "CREATE" and target is None)):
            raise ValueError(f"Update Rule {rule_id}: it acts on Tag lifecycle events. No tags were merged.")
        for action in actions or ():
            if not isinstance(action, dict):
                continue
            kind = action.get("type")
            if kind in {"add_tags", "remove_tags"} and retired_names.intersection(_folded_tag_names(action.get(kind) or "")):
                raise ValueError(f"Update Rule {rule_id}: it uses a tag being retired. No tags were merged.")
    for source_id, tags in ImporterSource.objects.filter(enabled=True).exclude(tags="").values_list("pk", "tags").iterator():
        if retired_names.intersection(crawl_tag_names(tags)):
            raise ValueError(f"Update Importer {source_id}: it uses a tag being retired. No tags were merged.")
    schedules = CrawlSchedule.objects.filter(is_enabled=True).exclude(template__tags_str="").values_list("pk", "template__tags_str")
    for schedule_id, tags in schedules.iterator():
        if retired_names.intersection(crawl_tag_names(tags)):
            raise ValueError(f"Update Scheduled Crawl {schedule_id}: its template uses a tag being retired. No tags were merged.")
    active_crawls = (
        Crawl.objects.filter(status__in=(*Crawl.RUNNABLE_STATES, Crawl.StatusChoices.PAUSED))
        .exclude(tags_str="")
        .values_list("pk", "tags_str")
    )
    for crawl_id, tags in active_crawls.iterator():
        if retired_names.intersection(crawl_tag_names(tags)):
            raise ValueError(f"Wait for Crawl {crawl_id} to finish: it uses a tag being retired. No tags were merged.")


@transaction.atomic
def merge_selected_tags(queryset, name, *, user, can_create, selected_count, snapshot_scope):
    """Merge an admin-scoped selection, without firing per-snapshot capture actions."""
    name = normalize_tag_name(name)
    stored_name = unescape(name).strip()
    if not stored_name or len(stored_name) > Tag._meta.get_field("name").max_length:
        raise ValueError("Enter a tag name between 1 and 100 characters.")
    selected = list(queryset.order_by("pk").values_list("pk", "name").distinct()[: MERGE_MAX_TAGS + 1])
    if not 2 <= len(selected) <= MERGE_MAX_TAGS:
        raise ValueError(f"Select between 2 and {MERGE_MAX_TAGS} tags to merge.")
    if str(len(selected)) != selected_count:
        raise ValueError("The tag selection changed. Review it before merging.")

    target = Tag.objects.filter(name=stored_name).first()
    if target is None:
        matching = list(Tag.objects.filter(name__iexact=stored_name).order_by("pk")[:2])
        if len(matching) > 1:
            raise ValueError("Several tags use this name with different capitalization. Enter the exact target name.")
        target = matching[0] if matching else None
    if not target and not can_create:
        raise ValueError("You can merge into an existing tag, but you do not have permission to create a new tag.")
    # Lock the actual Tag rows in a stable order on PostgreSQL before reading
    # their links. A writer cannot attach to a superseded tag mid-merge.
    expected = dict(selected)
    if target is not None:
        expected.setdefault(target.pk, target.name)
    locked = dict(Tag.objects.select_for_update().filter(pk__in=expected).order_by("pk").values_list("pk", "name"))
    if locked != expected:
        raise ValueError("The tag selection changed. Review it before merging.")
    retired = [(pk, old_name) for pk, old_name in selected if not target or pk != target.pk]
    retired_ids = [pk for pk, _old_name in retired]
    memberships = SnapshotTag.objects.filter(tag_id__in=retired_ids)
    if len(list(memberships.order_by().values_list("pk", flat=True)[: MERGE_MAX_LINKS + 1])) > MERGE_MAX_LINKS:
        raise ValueError(f"These tags have over {MERGE_MAX_LINKS:,} Snapshot links. Select a smaller batch.")
    permitted = snapshot_scope.order_by().values("pk")
    if memberships.exclude(snapshot_id__in=permitted).exists():
        raise ValueError("Some tagged Snapshots are outside your permissions. No tags were merged.")
    _check_merge_dependencies(retired, target, target.name if target else stored_name, memberships)

    snapshots = memberships.order_by().values_list("snapshot_id", flat=True).distinct()
    if target is None:
        target = Tag.objects.create(name=name, created_by=user)
    existing = SnapshotTag.objects.filter(tag_id=target.pk).order_by().values("snapshot_id")
    # A bounded multiple-row insert and normal Tag deletion preserve FK and
    # uniqueness checks. No per-Snapshot saves or duplicate attachment events.
    missing = [SnapshotTag(tag_id=target.pk, snapshot_id=pk) for pk in snapshots.exclude(snapshot_id__in=existing)]
    SnapshotTag.objects.bulk_create(missing)
    changed = snapshots.count()
    Tag.objects.filter(pk__in=retired_ids).delete()
    return target, len(retired_ids), changed
