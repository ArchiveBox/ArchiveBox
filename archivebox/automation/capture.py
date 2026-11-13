"""Synchronous capture-rule actions using ArchiveBox's native config resolver."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from pydantic import ValidationError as ConfigValidationError

from archivebox.config.common import ArchiveBoxConfig, config_field_metadata, get_config
from archivebox.plugins.discovery import get_enabled_plugins, get_plugin_catalog


def configurable_fields():
    return {
        key: metadata
        for key, metadata in config_field_metadata().items()
        if metadata["scope"] == "crawl_frozen" and not metadata["sensitive"] and key not in ArchiveBoxConfig.computed_config_keys
    }


def validate_capture_actions(rule):
    overrides = rule.config_overrides if rule.config_overrides is not None else {}
    if not isinstance(overrides, dict):
        raise ValidationError({"config_overrides": "Use a JSON object of configuration names and values."})
    invalid = set(overrides) - configurable_fields().keys()
    if invalid:
        raise ValidationError({"config_overrides": f"Unknown or non-capture settings: {', '.join(sorted(invalid))}."})
    if overrides:
        try:
            # Validate the original typed values before normal resolution (which
            # intentionally accepts string environment/INI values).
            resolved = get_config(overrides=overrides, include_machine=False)
            rule.config_overrides = {key: resolved.model_dump(mode="json")[key] for key in overrides}
        except (ConfigValidationError, ValueError, TypeError) as error:
            raise ValidationError({"config_overrides": str(error)}) from error
    catalog = get_plugin_catalog()
    for field in ("enable_plugins", "disable_plugins"):
        names = getattr(rule, field)
        if not isinstance(names, list) or any(not isinstance(name, str) or name not in catalog for name in names):
            raise ValidationError({field: "Select installed plugins by their exact name."})
    if set(rule.enable_plugins) & set(rule.disable_plugins):
        raise ValidationError({"disable_plugins": "A rule cannot both enable and disable the same plugin."})
    if "PLUGINS" in overrides:
        names = [name.strip() for name in str(overrides["PLUGINS"]).split(",") if name.strip()]
        if any(name not in catalog for name in names):
            raise ValidationError({"config_overrides": "PLUGINS must contain installed plugin names."})
    if rule.max_depth is not None and (rule.trigger != "before_crawl" or not 0 <= rule.max_depth <= 4):
        raise ValidationError({"max_depth": "Set a depth from 0 to 4 in a before-crawl rule."})
    capture_actions = bool(overrides or rule.enable_plugins or rule.disable_plugins or rule.max_depth is not None)
    if rule.is_capture_configuration:
        if rule.add_tags or rule.remove_tags or rule.permissions or rule.folder_id:
            raise ValidationError(
                "Use capture settings and plugin actions before execution. Tag, folder, and visibility actions belong to later events.",
            )
    elif capture_actions:
        raise ValidationError("Capture configuration and plugin actions require a before-crawl or before-page trigger.")


def evaluate_capture_rules(crawl, *, snapshot=None, rules=None):
    """Return ordinary config overrides and audit entries, without persisting."""
    from .models import Rule
    from .service import matches

    phase = "before_snapshot" if snapshot is not None else "before_crawl"
    rules = list(rules) if rules is not None else list(Rule.objects.filter(enabled=True, trigger=phase).prefetch_related("conditions"))
    overrides = dict((snapshot.config if snapshot is not None else crawl.config) or {})
    max_depth = crawl.max_depth
    runs = []
    stopped = False
    seeds = [url.strip() for url in crawl.urls.splitlines() if url.strip() and not url.strip().startswith("#")]
    from urllib.parse import urlsplit

    for rule in rules:
        if stopped:
            runs.append((rule, False, {"skipped": "An earlier matching rule stopped processing."}))
            continue
        if snapshot is None:
            # Evaluate the whole expression against each seed, preventing an
            # AND from combining the domain of one seed with another seed's URL.
            matched = any(
                matches(
                    rule,
                    None,
                    values={
                        "domain": [urlsplit(url).hostname or ""],
                        "url": [url],
                        "crawl_tag": crawl.current_tag_names(),
                        "crawl_label": [crawl.label or ""],
                    },
                )
                for url in seeds
            )
        else:
            matched = matches(rule, snapshot)
        changes = {}
        if matched:
            validate_capture_actions(rule)
            before = get_config(
                crawl=crawl if snapshot is not None else None,
                snapshot=snapshot,
                persona=crawl.persona if crawl.persona_id else None,
                overrides=overrides,
            )
            overrides.update(rule.config_overrides)
            if rule.enable_plugins or rule.disable_plugins:
                effective = get_config(
                    crawl=crawl if snapshot is not None else None,
                    snapshot=snapshot,
                    persona=crawl.persona if crawl.persona_id else None,
                    overrides=overrides,
                )
                selected = str(effective.PLUGINS or "").strip()
                names = (
                    {name.strip() for name in selected.split(",") if name.strip()}
                    if selected
                    else set(get_enabled_plugins(config=effective))
                )
                names.update(rule.enable_plugins)
                names.difference_update(rule.disable_plugins)
                if not names:
                    raise ValidationError(
                        "Plugin actions cannot leave an empty selector; empty PLUGINS means ambient defaults. Disable individual output plugins while retaining their runtime dependencies.",
                    )
                overrides["PLUGINS"] = ",".join(sorted(names))
            after = get_config(
                crawl=crawl if snapshot is not None else None,
                snapshot=snapshot,
                persona=crawl.persona if crawl.persona_id else None,
                overrides=overrides,
            )
            keys = set(rule.config_overrides) | ({"PLUGINS"} if rule.enable_plugins or rule.disable_plugins else set())
            changes["config"] = {
                key: {"before": before.model_dump(mode="json").get(key), "after": after.model_dump(mode="json").get(key)} for key in keys
            }
            if rule.max_depth is not None:
                changes["max_depth"] = {"before": max_depth, "after": rule.max_depth}
                max_depth = rule.max_depth
            stopped = rule.stop_processing
        runs.append((rule, matched, changes))
    return overrides, max_depth, runs


def record_capture_runs(crawl, runs, *, snapshot=None, event=None):
    from .models import RuleRun

    return RuleRun.objects.bulk_create(
        [
            RuleRun(
                rule=rule,
                rule_name=rule.name,
                crawl=crawl,
                snapshot=snapshot,
                event=event,
                phase="before_snapshot" if snapshot is not None else "before_crawl",
                matched=matched,
                changes=changes,
            )
            for rule, matched, changes in runs
        ],
    )


def prepare_snapshot_rules(snapshot):
    """Persist once before payload/Persona preparation; completed captures stay immutable."""
    from archivebox.core.models import Snapshot
    from .models import RuleEvent

    if snapshot.status not in Snapshot.RUNNABLE_STATES:
        return
    with transaction.atomic():
        event, created = RuleEvent.objects.get_or_create(snapshot=snapshot, kind="before_snapshot")
        if not created:
            return
        # Existing executions predate this hook; do not rewrite their settings
        # when resuming, retrying a plugin, or performing maintenance.
        if snapshot.archiveresult_set.exists():
            event.processed_at = timezone.now()
            event.save(update_fields=["processed_at"])
            return
        config, _, runs = evaluate_capture_rules(snapshot.crawl, snapshot=snapshot)
        Snapshot.objects.filter(pk=snapshot.pk).update(config=config)
        snapshot.config = config
        record_capture_runs(snapshot.crawl, runs, snapshot=snapshot, event=event)
        event.processed_at = timezone.now()
        event.save(update_fields=["processed_at"])
