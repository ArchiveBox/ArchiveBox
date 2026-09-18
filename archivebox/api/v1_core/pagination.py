import math
from typing import Any

from django.http import HttpRequest
from ninja.pagination import PaginationBase


class CustomPagination(PaginationBase):
    class Input(PaginationBase.Input):
        limit: int = 200
        offset: int = 0
        page: int = 0

    class Output(PaginationBase.Output):
        count: int
        total_items: int
        total_pages: int
        page: int
        limit: int
        offset: int
        num_items: int
        items: list[Any]

    def paginate_queryset(self, queryset, pagination: Input, request: HttpRequest, **params):
        limit = min(pagination.limit, 500)
        offset = pagination.offset or (pagination.page * limit)
        total = queryset.values("pk").distinct().count() if queryset.query.distinct else queryset.count()
        total_pages = math.ceil(total / limit)
        current_page = math.ceil(offset / (limit + 1))
        items = queryset[offset : offset + limit]
        return {
            "count": total,
            "total_items": total,
            "total_pages": total_pages,
            "page": current_page,
            "limit": limit,
            "offset": offset,
            "num_items": len(items),
            "items": items,
        }
