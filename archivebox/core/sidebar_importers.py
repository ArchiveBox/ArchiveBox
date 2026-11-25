"""Importer catalog and active source navigation for the snapshot sidebar."""

from collections import defaultdict

from django.db.models import Case, IntegerField, Q, Value, When
from django.db.models.functions import Lower
from django.urls import reverse

from archivebox.importers.catalog import get_importer_providers, get_importers
from archivebox.importers.models import ImporterSource
from archivebox.uuid_compat import compact_uuid


def importer_sidebar_allowed(request):
    # Match the native Importers views: staff and public visitors may not see sources.
    user = request.user
    return user.is_authenticated and user.is_active and user.is_superuser


def _provider_key(provider):
    definition = provider["definition"]
    return f"importer-family:{definition.plugin}:{definition.feed}"


def _sidebar_catalog(request):
    # The initial Library page renders both the entries and the Add menu.
    # Reuse discovery for that response without keeping stale manifests across requests.
    if not hasattr(request, "_library_importer_catalog"):
        definitions = get_importers()
        providers = sorted(
            get_importer_providers(definitions),
            key=lambda provider: (provider["name"].casefold(), _provider_key(provider)),
        )
        request._library_importer_catalog = definitions, {_provider_key(provider): provider for provider in providers}
    return request._library_importer_catalog


def _icon(definition):
    return reverse("importers:icon", args=(definition.plugin, definition.feed)) if definition.icon else ""


def _feed_action(definition):
    return {
        "label": definition.title,
        "url": reverse("importers:new", args=(definition.plugin, definition.feed)),
        "icon_url": _icon(definition),
    }


def _pair_filter(choices):
    feeds = defaultdict(list)
    for definition in choices:
        feeds[definition.plugin].append(definition.feed)

    query = Q(pk__in=[])
    for plugin, plugin_feeds in feeds.items():
        query |= Q(plugin=plugin, feed__in=plugin_feeds)
    return query


def _matches_filter(providers, term):
    if not term:
        return Q()
    key = term.casefold()
    matching_choices = [
        feed for provider in providers for feed in provider["feeds"] if key in provider["name"].casefold() or key in feed.title.casefold()
    ]
    return Q(name__icontains=term) | _pair_filter(matching_choices)


def _family_row(provider, *, expand=False):
    definition = provider["definition"]
    if len(provider["feeds"]) == 1:
        add_url = _feed_action(definition)["url"]
    else:
        add_url = reverse("importers:index", fragment=provider["anchor"])
    return {
        "id": _provider_key(provider),
        "name": provider["name"],
        "scope": "",
        "filter_value": "",
        "parent_id": "",
        "has_children": True,
        "expand": expand,
        "icon_url": _icon(definition),
        "actions": [{"label": "Add importer", "url": add_url}],
    }


def _source_row(pk, name, definition, parent):
    key = str(compact_uuid(pk))
    return {
        "id": key,
        "name": name,
        "scope": "importer",
        "filter_value": key,
        "parent_id": parent,
        "has_children": False,
        "icon_url": _icon(definition),
        "delete_url": reverse("importers:detail", args=(key,)) + "#delete-importer",
        "delete_label": "Delete Importer",
        "actions": [
            {"label": "Open importer", "url": reverse("importers:detail", args=(key,))},
            {"label": "Edit importer", "url": reverse("importers:edit", args=(key,))},
        ],
    }


def _source_page(sources, cursor, limit, *, families=()):
    sources = sources.annotate(sort_name=Lower("name"))
    order = ("sort_name", "pk")
    if families:
        # Search pages must introduce families in the same order as the root,
        # even when several pages of matching sources belong to one family.
        sources = sources.annotate(
            sort_family=Case(
                *(When(_pair_filter(provider["feeds"]), then=Value(rank)) for rank, provider in enumerate(families)),
                output_field=IntegerField(),
            ),
        )
        order = ("sort_family", *order)
    if cursor:
        *family, sort_name, pk = cursor
        after = Q(sort_name__gt=sort_name) | Q(sort_name=sort_name, pk__gt=compact_uuid(pk))
        if families:
            (rank,) = family
            after = Q(sort_family__gt=rank) | (Q(sort_family=rank) & after)
        elif family:
            raise ValueError("Invalid importer source cursor")
        sources = sources.filter(after)
    values = list(sources.order_by(*order).values_list("pk", "name", "plugin", "feed", *order[:-1])[: limit + 1])
    rows = values[:limit]
    next_key = [*rows[-1][4:], str(compact_uuid(rows[-1][0]))] if len(values) > limit else None
    return [row[:4] for row in rows], next_key


def _selected_source(request, importer_id):
    if not importer_sidebar_allowed(request) or not importer_id:
        return None
    try:
        importer_id = compact_uuid(importer_id)
    except (AttributeError, TypeError, ValueError):
        return None
    return ImporterSource.objects.filter(pk=importer_id, enabled=True).values_list("pk", "name", "plugin", "feed").first()


def importer_entries_page(request, *, term, parent, cursor, limit):
    """Return installed provider families or one keyset page of active sources."""
    if not importer_sidebar_allowed(request):
        return [], None

    definitions, providers = _sidebar_catalog(request)
    sources = ImporterSource.objects.filter(enabled=True)

    if parent:
        if parent not in providers:
            return [], None
        provider = providers[parent]
        sources = sources.filter(_pair_filter(provider["feeds"]), _matches_filter([provider], term))
        rows, next_key = _source_page(sources, cursor, limit)
        return [_source_row(pk, name, definitions[plugin, feed], parent) for pk, name, plugin, feed in rows], next_key

    family_by_pair = {(feed.plugin, feed.feed): key for key, provider in providers.items() for feed in provider["feeds"]}
    if term:
        # A search fetches only limit + 1 source rows, then groups their
        # ancestors in memory. This keeps matching children visible without
        # a separate lookup/query for each family.
        matches = sources.filter(_pair_filter(definitions.values()), _matches_filter(providers.values(), term))
        matched, next_key = _source_page(matches, cursor, limit, families=tuple(providers.values()))
        grouped = defaultdict(list)
        for pk, name, plugin, feed in matched:
            key = family_by_pair[plugin, feed]
            grouped[key].append(_source_row(pk, name, definitions[plugin, feed], key))
        return [
            row
            for key, provider in providers.items()
            if key in grouped
            for row in [{**_family_row(provider, expand=True), "children_loaded": True}, *grouped[key]]
        ], next_key

    # The native catalog is bounded independently of saved sources. Even empty
    # families are visible, and their active children are loaded only on demand.
    keys = list(providers)
    if cursor:
        (last_key,) = cursor
        keys = keys[keys.index(last_key) + 1 :]
    next_key = [keys[limit - 1]] if len(keys) > limit else None
    keys = keys[:limit]

    selected = None if cursor else _selected_source(request, request.GET.get("importer"))
    selected_provider = family_by_pair.get(tuple(selected[2:])) if selected else None
    # Keep a deep link visible even if its family is beyond the first page.
    # This adds at most one family and one child; the cursor still follows
    # the ordinary catalog page, so a later root page is not skipped.
    if selected_provider and selected_provider not in keys:
        keys.append(selected_provider)
    rows = []
    for key in keys:
        rows.append(_family_row(providers[key], expand=key == selected_provider))
        if selected and key == selected_provider:
            pk, name, plugin, feed = selected
            rows.append(_source_row(pk, name, definitions[plugin, feed], key))
    return rows, next_key


def importer_add_actions(request):
    """Advertise the same provider groups and feed options as the native picker."""
    if not importer_sidebar_allowed(request):
        return []
    _, providers = _sidebar_catalog(request)
    return [
        {**_feed_action(definition), "family": provider["name"]}
        for provider in providers.values()
        for definition in sorted(provider["feeds"], key=lambda feed: (feed.title.casefold(), feed.plugin, feed.feed))
    ]
