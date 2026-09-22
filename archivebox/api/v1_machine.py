__package__ = "archivebox.api"

from uuid import UUID
from typing import Annotated
from datetime import datetime

from django.http import HttpRequest

from ninja import FilterLookup, FilterSchema, Query, Router, Schema
from ninja.pagination import paginate

from archivebox.api.v1_core import CustomPagination


router = Router(tags=["Machine and Dependencies"])


# ============================================================================
# Machine Schemas
# ============================================================================


class MachineSchema(Schema):
    """Schema for Machine model."""

    TYPE: str = "machine.Machine"
    id: UUID
    created_at: datetime
    modified_at: datetime
    guid: str
    hostname: str
    hw_in_docker: bool
    hw_in_vm: bool
    hw_manufacturer: str
    hw_product: str
    hw_uuid: str
    os_arch: str
    os_family: str
    os_platform: str
    os_release: str
    os_kernel: str
    stats: dict
    num_uses_succeeded: int
    num_uses_failed: int


class MachineFilterSchema(FilterSchema):
    id: Annotated[str | None, FilterLookup("id__startswith")] = None
    hostname: Annotated[str | None, FilterLookup("hostname__icontains")] = None
    os_platform: Annotated[str | None, FilterLookup("os_platform__icontains")] = None
    os_arch: Annotated[str | None, FilterLookup("os_arch")] = None
    hw_in_docker: Annotated[bool | None, FilterLookup("hw_in_docker")] = None
    hw_in_vm: Annotated[bool | None, FilterLookup("hw_in_vm")] = None
    bin_providers: Annotated[str | None, FilterLookup("bin_providers__icontains")] = None


# ============================================================================
# Binary Schemas
# ============================================================================


class BinarySchema(Schema):
    """Schema for Binary model."""

    TYPE: str = "machine.Binary"
    id: UUID
    created_at: datetime
    modified_at: datetime
    machine_id: UUID
    machine_hostname: str
    name: str
    binproviders: str
    binprovider: str
    abspath: str
    version: str
    sha256: str
    status: str
    is_valid: bool
    num_uses_succeeded: int
    num_uses_failed: int

    @staticmethod
    def resolve_machine_hostname(obj) -> str:
        return obj.machine.hostname

    @staticmethod
    def resolve_is_valid(obj) -> bool:
        return obj.is_valid


class BinaryFilterSchema(FilterSchema):
    id: Annotated[str | None, FilterLookup("id__startswith")] = None
    name: Annotated[str | None, FilterLookup("name__icontains")] = None
    binprovider: Annotated[str | None, FilterLookup("binprovider")] = None
    status: Annotated[str | None, FilterLookup("status")] = None
    machine_id: Annotated[str | None, FilterLookup("machine_id__startswith")] = None
    version: Annotated[str | None, FilterLookup("version__icontains")] = None


# ============================================================================
# Machine Endpoints
# ============================================================================


@router.get("/machines", response=list[MachineSchema], url_name="get_machines")
@paginate(CustomPagination)
def get_machines(request: HttpRequest, filters: Query[MachineFilterSchema]):
    """List all machines."""
    from archivebox.machine.models import Machine

    return filters.filter(Machine.objects.all()).distinct()


@router.get("/machine/current", response=MachineSchema, url_name="get_current_machine")
def get_current_machine(request: HttpRequest):
    """Get the current machine."""
    from archivebox.machine.models import Machine

    return Machine.current()


@router.get("/machine/{machine_id}", response=MachineSchema, url_name="get_machine")
def get_machine(request: HttpRequest, machine_id: str):
    """Get a specific machine by ID."""
    from archivebox.machine.models import Machine
    from django.db.models import Q

    return Machine.objects.get(Q(id__startswith=machine_id) | Q(hostname__iexact=machine_id))


# ============================================================================


# ============================================================================
# Binary Endpoints
# ============================================================================


@router.get("/binaries", response=list[BinarySchema], url_name="get_binaries")
@paginate(CustomPagination)
def get_binaries(request: HttpRequest, filters: Query[BinaryFilterSchema]):
    """List all binaries."""
    from archivebox.machine.models import Binary

    return filters.filter(Binary.objects.all().select_related("machine")).distinct()


@router.get("/binary/{binary_id}", response=BinarySchema, url_name="get_binary")
def get_binary(request: HttpRequest, binary_id: str):
    """Get a specific binary by ID."""
    from archivebox.machine.models import Binary

    return Binary.objects.select_related("machine").get(id__startswith=binary_id)


@router.get("/binary/by-name/{name}", response=list[BinarySchema], url_name="get_binaries_by_name")
def get_binaries_by_name(request: HttpRequest, name: str):
    """Get all binaries with the given name."""
    from archivebox.machine.models import Binary

    return list(Binary.objects.filter(name__iexact=name).select_related("machine"))
