"""Model-derived, parameterized snapshot predicates shared by folder views and exports."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Exists, OuterRef, F, Value
from django.db.models.functions import Cast, Concat, MD5
from django.utils import timezone

CHILDREN_RULES = {"field": "folder", "lookup": "in_children", "value": "self"}
OPERATORS = {
    "exact": "is",
    "not_exact": "is not",
    "icontains": "contains",
    "not_contains": "does not contain",
    "istartswith": "starts with",
    "iendswith": "ends with",
    "in": "is one of",
    "not_in": "is not one of",
    "gt": "is greater than",
    "gte": "is at least",
    "lt": "is less than",
    "lte": "is at most",
    "isnull": "is empty",
    "present": "is present",
    "past_days": "in the last days",
    "has_key": "has key",
    "in_folder": "is in folder",
    "not_in_folder": "is not in folder",
    "in_children": "is in children of",
}
UNITS = {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}


@lru_cache(maxsize=1)
def model_fields():
    from archivebox.core.models import Snapshot

    fields = {}

    def visit(model, prefix="", multi=False, ancestors=()):
        for field in model._meta.get_fields():
            if field.hidden or field.name.startswith("_"):
                continue
            path = prefix + field.name
            if field.is_relation:
                related = field.related_model
                if not related or related in ancestors or related is Snapshot:
                    continue
                many = multi or field.one_to_many or field.many_to_many
                fields[path] = (related._meta.pk, many)
                if len(ancestors) < 2 and related._meta.app_label in {"core", "crawls"}:
                    visit(related, path + "__", many, (*ancestors, model))
                elif related._meta.label_lower == "auth.user":
                    fields[path + "__username"] = (related._meta.get_field("username"), many)
            elif not isinstance(field, models.BinaryField):
                fields[path] = (getattr(field, "output_field", field), multi)

    visit(Snapshot)
    return fields


def field_spec(name, field):
    from archivebox.core.models import Snapshot

    model, labels = Snapshot, []
    for part in name.split("__"):
        descriptor = model._meta.get_field(part)
        if descriptor.is_relation:
            model = descriptor.related_model
            label = model._meta.verbose_name_plural if descriptor.one_to_many or descriptor.many_to_many else model._meta.verbose_name
        else:
            label = descriptor.verbose_name
        labels.append(str(label).capitalize())
    if isinstance(field, models.BooleanField):
        kind, lookups = "boolean", ["exact", "not_exact", "isnull", "present"]
    elif isinstance(field, (models.IntegerField, models.FloatField, models.DecimalField)):
        kind, lookups = "number", ["exact", "not_exact", "gt", "gte", "lt", "lte", "in", "not_in", "isnull", "present"]
    elif isinstance(field, (models.DateField, models.TimeField)):
        kind, lookups = "date", ["exact", "gt", "gte", "lt", "lte", "past_days", "isnull", "present"]
    elif isinstance(field, models.JSONField):
        kind, lookups = "json", ["exact", "not_exact", "has_key", "isnull", "present"]
    else:
        kind, lookups = (
            "text",
            ["exact", "not_exact", "icontains", "not_contains", "istartswith", "iendswith", "in", "not_in", "isnull", "present"],
        )
    return {
        "name": name,
        "label": " → ".join(labels),
        "type": kind,
        "operators": lookups,
        "choices": list(field.flatchoices) if field.choices else [],
        "units": list(UNITS) if kind == "number" and ("bytes" in str(field.help_text).lower() or name.endswith("_size")) else [],
    }


class RuleQuery:
    def __init__(self, folders=None, *, validate=False, freeze_limits=False):
        from archivebox.core.models import Folder

        self.folders = {str(f.pk): f for f in (folders if folders is not None else Folder.objects.all())}
        self.validate = validate
        self.freeze_limits = freeze_limits
        self.cache = {}
        self.specs = {spec["name"]: spec for spec in self.schema()}

    @staticmethod
    @lru_cache(maxsize=1)
    def sort_fields():
        from archivebox.core.models import Snapshot

        return {
            field.name: str(field.verbose_name).capitalize()
            for field in Snapshot._meta.concrete_fields
            if not field.is_relation and not isinstance(field, (models.JSONField, models.BinaryField))
        }

    @classmethod
    def ordering(cls, folder):
        from archivebox.core.models import Snapshot

        sort = (folder.rules or {}).get("sort", "-created_at")
        if sort == "?":
            # Stable shuffle: pagination, exports and bulk moves see the same set.
            return [MD5(Concat(Cast("pk", models.CharField()), Value(str(folder.pk)))).asc(), "pk"]
        if not isinstance(sort, str) or sort.removeprefix("-") not in cls.sort_fields():
            raise ValidationError("Choose a supported sort field.")
        field, descending = sort.removeprefix("-"), sort.startswith("-")
        order = sort
        if Snapshot._meta.get_field(field).null:
            order = F(field).desc(nulls_last=True) if descending else F(field).asc(nulls_last=True)
        return [order, "-pk" if descending else "pk"]

    def limit(self, folder, query):
        from archivebox.core.models import Snapshot

        ordering = self.ordering(folder)
        limit = folder.rules.get("limit")
        if limit is None:
            return query
        if type(limit) is not int or not 1 <= limit <= 2**63 - 1:
            raise ValidationError("Limit must be a positive whole number, or blank.")
        if self.validate:
            return query
        matches = Snapshot.objects.filter(query).order_by(*ordering)
        if limit <= 1000:
            from archivebox.misc.paginators import snapshot_page

            # Reuse the bounded order-index probe for small playlists, avoiding
            # a full sort of a large folder before applying its limit.
            ids = snapshot_page(
                matches.values_list("pk", flat=True),
                base_queryset=Snapshot.objects.values_list("pk", flat=True),
                start=0,
                size=limit,
            )
            return Q(pk__in=ids)
        if not self.freeze_limits:
            return Q(pk__in=matches.values("pk")[:limit])
        # Freeze a scalar boundary before writes so a limited folder cannot
        # refill and move more than the initially selected set. No ID list/lock.
        first = ordering[0]
        expression = F(first.lstrip("-")) if isinstance(first, str) else first.expression
        descending = first.startswith("-") if isinstance(first, str) else first.descending
        matches = matches.alias(_folder_order=expression)
        boundary = list(matches.annotate(_value=expression).values_list("_value", "pk")[limit - 1 : limit])
        if not boundary:
            return query
        value, pk = boundary[0]
        comparison = "gte" if descending else "lte"
        cutoff = Q(_folder_order=value, **{f"pk__{comparison}": pk})
        cutoff |= Q(_folder_order__isnull=False) if value is None else Q(**{f"_folder_order__{'gt' if descending else 'lt'}": value})
        return Q(pk__in=matches.filter(cutoff).order_by().values("pk"))

    @staticmethod
    @lru_cache(maxsize=1)
    def schema():
        result = [field_spec(name, field) for name, (field, _) in model_fields().items() if name != "folder"]
        result[:0] = [
            {
                "name": "folder",
                "label": "Folder",
                "type": "folder",
                "operators": ["in_folder", "not_in_folder", "in_children"],
                "choices": [],
                "units": [],
            },
            {
                "name": "domain",
                "label": "Domain",
                "type": "text",
                "operators": ["exact", "not_exact", "icontains", "not_contains", "istartswith", "iendswith", "in", "not_in"],
                "choices": [],
                "units": [],
            },
        ]
        return result

    def folder(self, folder_id, stack=()):
        key = str(folder_id)
        if len(stack) > 64:
            raise ValidationError("Use at most 64 levels of folder references.")
        if key in stack:
            raise ValidationError("Smart folder rules cannot contain a cycle.")
        if key in self.cache:
            return self.cache[key]
        folder = self.folders.get(key)
        if folder is None:
            return Q(pk__in=[])
        children = [child for child in self.folders.values() if str(child.parent_id) == key]
        if folder.is_smart:
            query = self.compile(folder.rules, (*stack, key))
        else:
            query = Q(folder_id=folder.pk)
        # Validate the future union before nesting a folder. Its old membership
        # remains readable while the independently committed move is in progress.
        if children and not folder.is_container:
            for child in children:
                query |= self.folder(child.pk, (*stack, key))
        if folder.is_smart:
            query = self.limit(folder, query)
        self.cache[key] = query
        return query

    def compile(self, rules, stack=()):
        from archivebox.core.models import Snapshot

        count = 0

        def build(node, depth=0):
            nonlocal count
            count += 1
            if count > 100 or depth > 8 or not isinstance(node, dict):
                raise ValidationError("Use at most 100 rules and 8 nested groups.")
            if "op" in node:
                op, children = node.get("op"), node.get("rules")
                if (
                    op not in {"AND", "OR", "NOT"}
                    or not isinstance(children, list)
                    or not 1 <= len(children) <= 2
                    or (op == "NOT" and len(children) != 1)
                ):
                    raise ValidationError("AND/OR groups take one or two members; NOT takes one group or condition.")
                parts = [build(child, depth + 1) for child in children]
                result = parts[0]
                for part in parts[1:]:
                    result = result & part if op == "AND" else result | part
                if op == "NOT":
                    # SQLite can seek IS NULL, but NOT (column IS NOT NULL)
                    # scans the index. Keep simple null predicates sargable.
                    if len(result.children) == 1 and isinstance(result.children[0], tuple) and result.children[0][0].endswith("__isnull"):
                        name, value = result.children[0]
                        return Q(**{name: not value})
                    return ~result
                return result
            name, lookup, value = node.get("field"), node.get("lookup"), node.get("value")
            spec = self.specs.get(name)
            if not spec or lookup not in spec["operators"]:
                raise ValidationError("Choose a supported model field and comparison.")
            negative = lookup in {"not_exact", "not_contains", "not_in", "not_in_folder"}
            lookup = {"not_exact": "exact", "not_contains": "icontains", "not_in": "in", "not_in_folder": "in_folder"}.get(lookup, lookup)
            if name == "folder":
                if lookup == "in_children":
                    parent = stack[-1] if value == "self" and stack else str(value)
                    if parent not in self.folders and self.validate:
                        raise ValidationError("Choose an existing parent folder.")
                    result = Q(pk__in=[])
                    physical, pending, visited = [], [parent], set()
                    while pending:
                        key = pending.pop()
                        if key in visited:
                            raise ValidationError("Folders cannot contain a cycle.")
                        visited.add(key)
                        # Include any remaining source rows during a partial move.
                        if key in self.folders and (
                            self.folders[key].is_container or any(str(child.parent_id) == key for child in self.folders.values())
                        ):
                            physical.append(key)
                        for child in self.folders.values():
                            if str(child.parent_id) == key:
                                if child.is_container and not child.rules.get("limit"):
                                    pending.append(str(child.pk))
                                else:
                                    result |= self.folder(child.pk, stack) if child.is_smart else Q(pk__in=[])
                                    if not child.is_smart:
                                        physical.append(str(child.pk))
                    result |= Q(folder_id__in=physical)
                else:
                    if value != "*" and str(value) not in self.folders and self.validate:
                        raise ValidationError("Choose an existing folder or ANY.")
                    if value == "*":
                        result, negative = Q(folder__isnull=negative), False
                    else:
                        result = self.folder(value, stack)
            else:
                field, multi = model_fields().get(name, (models.CharField(), False))
                if lookup in {"isnull", "present"}:
                    value, lookup = lookup == "isnull", "isnull"
                elif lookup == "past_days":
                    try:
                        days = int(value)
                        if not 0 <= days <= 365000:
                            raise ValueError
                        value = timezone.now() - timedelta(days=days)
                        if not isinstance(field, models.DateTimeField):
                            value = value.date()
                        lookup = "gte"
                    except (ValueError, TypeError, OverflowError) as error:
                        raise ValidationError("Enter a valid number of days.") from error
                else:
                    values = value if lookup == "in" else [value]
                    if not isinstance(values, list) or not values or len(values) > 100:
                        raise ValidationError("Enter between 1 and 100 values.")
                    cleaned = []
                    for item in values:
                        try:
                            if isinstance(item, dict) and spec["units"]:
                                amount = Decimal(str(item["amount"])) * UNITS[item["unit"]]
                                if not amount.is_finite() or amount != amount.to_integral_value():
                                    raise ValueError
                                item = int(amount)
                            if lookup != "has_key":
                                item = field.clean(item, None)
                            if lookup in {"icontains", "istartswith", "iendswith"} and not item:
                                raise ValueError
                            cleaned.append(item)
                        except (ValueError, TypeError, KeyError, InvalidOperation, OverflowError) as error:
                            raise ValidationError("Enter a valid value for this field.") from error
                    value = cleaned if lookup == "in" else cleaned[0]
                if name == "domain":
                    result = Q(
                        Exists(
                            Snapshot.objects.with_hostname(allow_empty=True).filter(
                                pk=OuterRef("pk"),
                                **{f"_domain_host__{lookup}": value},
                            ),
                        ),
                    )
                elif multi:
                    result = Q(Exists(Snapshot.objects.filter(pk=OuterRef("pk")).filter(**{f"{name}__{lookup}": value})))
                else:
                    result = Q(**{f"{name}__{lookup}": value})
            return ~result if negative else result

        return build(rules)
