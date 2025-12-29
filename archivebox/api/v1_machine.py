__package__ = 'archivebox.api'

from uuid import UUID
from typing import List, Optional
from datetime import datetime

from ninja import Router, Schema, FilterSchema, Field, Query
from ninja.pagination import paginate

from archivebox.api.v1_core import CustomPagination


router = Router(tags=['Machine and Dependencies'])


# ============================================================================
# Machine Schemas
# ============================================================================

class MachineSchema(Schema):
    """Schema for Machine model."""
    TYPE: str = 'machine.Machine'
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
    id: Optional[str] = Field(None, q='id__startswith')
    hostname: Optional[str] = Field(None, q='hostname__icontains')
    os_platform: Optional[str] = Field(None, q='os_platform__icontains')
    os_arch: Optional[str] = Field(None, q='os_arch')
    hw_in_docker: Optional[bool] = Field(None, q='hw_in_docker')
    hw_in_vm: Optional[bool] = Field(None, q='hw_in_vm')


# ============================================================================
    bin_providers: Optional[str] = Field(None, q='bin_providers__icontains')


# ============================================================================
# Binary Schemas
# ============================================================================

class BinarySchema(Schema):
    """Schema for Binary model."""
    TYPE: str = 'machine.Binary'
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
    id: Optional[str] = Field(None, q='id__startswith')
    name: Optional[str] = Field(None, q='name__icontains')
    binprovider: Optional[str] = Field(None, q='binprovider')
    status: Optional[str] = Field(None, q='status')
    machine_id: Optional[str] = Field(None, q='machine_id__startswith')
    version: Optional[str] = Field(None, q='version__icontains')


# ============================================================================
# Machine Endpoints
# ============================================================================

@router.get("/machines", response=List[MachineSchema], url_name="get_machines")
@paginate(CustomPagination)
def get_machines(request, filters: MachineFilterSchema = Query(...)):
    """List all machines."""
    from archivebox.machine.models import Machine
    return filters.filter(Machine.objects.all()).distinct()


@router.get("/machine/{machine_id}", response=MachineSchema, url_name="get_machine")
def get_machine(request, machine_id: str):
    """Get a specific machine by ID."""
    from archivebox.machine.models import Machine
    from django.db.models import Q
    return Machine.objects.get(Q(id__startswith=machine_id) | Q(hostname__iexact=machine_id))


@router.get("/machine/current", response=MachineSchema, url_name="get_current_machine")
def get_current_machine(request):
    """Get the current machine."""
    from archivebox.machine.models import Machine
    return Machine.current()


# ============================================================================


# ============================================================================
# Binary Endpoints
# ============================================================================

@router.get("/binaries", response=List[BinarySchema], url_name="get_binaries")
@paginate(CustomPagination)
def get_binaries(request, filters: BinaryFilterSchema = Query(...)):
    """List all binaries."""
    from archivebox.machine.models import Binary
    return filters.filter(Binary.objects.all().select_related('machine', 'dependency')).distinct()


@router.get("/binary/{binary_id}", response=BinarySchema, url_name="get_binary")
def get_binary(request, binary_id: str):
    """Get a specific binary by ID."""
    from archivebox.machine.models import Binary
    return Binary.objects.select_related('machine', 'dependency').get(id__startswith=binary_id)


@router.get("/binary/by-name/{name}", response=List[BinarySchema], url_name="get_binaries_by_name")
def get_binaries_by_name(request, name: str):
    """Get all binaries with the given name."""
    from archivebox.machine.models import Binary
    return list(Binary.objects.filter(name__iexact=name).select_related('machine', 'dependency'))
