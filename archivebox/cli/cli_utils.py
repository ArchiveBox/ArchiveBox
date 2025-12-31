"""
Shared CLI utilities for ArchiveBox commands.

This module contains common utilities used across multiple CLI commands,
extracted to avoid code duplication.
"""

__package__ = 'archivebox.cli'

from typing import Optional


def apply_filters(queryset, filter_kwargs: dict, limit: Optional[int] = None):
    """
    Apply Django-style filters from CLI kwargs to a QuerySet.

    Supports: --status=queued, --url__icontains=example, --id__in=uuid1,uuid2

    Args:
        queryset: Django QuerySet to filter
        filter_kwargs: Dict of filter key-value pairs from CLI
        limit: Optional limit on results

    Returns:
        Filtered QuerySet

    Example:
        queryset = Snapshot.objects.all()
        filter_kwargs = {'status': 'queued', 'url__icontains': 'example.com'}
        filtered = apply_filters(queryset, filter_kwargs, limit=10)
    """
    filters = {}
    for key, value in filter_kwargs.items():
        if value is None or key in ('limit', 'offset'):
            continue
        # Handle CSV lists for __in filters
        if key.endswith('__in') and isinstance(value, str):
            value = [v.strip() for v in value.split(',')]
        filters[key] = value

    if filters:
        queryset = queryset.filter(**filters)
    if limit:
        queryset = queryset[:limit]

    return queryset
