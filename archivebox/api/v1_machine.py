__package__ = 'archivebox.api'

from uuid import UUID
from typing import List, Optional
from datetime import datetime

from ninja import Router, Schema, FilterSchema, Field, Query
from ninja.pagination import paginate

from api.v1_core import CustomPagination


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
# Dependency Schemas
# ============================================================================

class DependencySchema(Schema):
    """Schema for Dependency model."""
    TYPE: str = 'machine.Dependency'
    id: UUID
    created_at: datetime
    modified_at: datetime
    bin_name: str
    bin_providers: str
    custom_cmds: dict
    config: dict
    is_installed: bool
    installed_count: int

    @staticmethod
    def resolve_is_installed(obj) -> bool:
        return obj.is_installed

    @staticmethod
    def resolve_installed_count(obj) -> int:
        return obj.installed_binaries.count()


class DependencyFilterSchema(FilterSchema):
    id: Optional[str] = Field(None, q='id__startswith')
    bin_name: Optional[str] = Field(None, q='bin_name__icontains')
    bin_providers: Optional[str] = Field(None, q='bin_providers__icontains')


# ============================================================================
# InstalledBinary Schemas
# ============================================================================

class InstalledBinarySchema(Schema):
    """Schema for InstalledBinary model."""
    TYPE: str = 'machine.InstalledBinary'
    id: UUID
    created_at: datetime
    modified_at: datetime
    machine_id: UUID
    machine_hostname: str
    dependency_id: Optional[UUID]
    dependency_bin_name: Optional[str]
    name: str
    binprovider: str
    abspath: str
    version: str
    sha256: str
    is_valid: bool
    num_uses_succeeded: int
    num_uses_failed: int

    @staticmethod
    def resolve_machine_hostname(obj) -> str:
        return obj.machine.hostname

    @staticmethod
    def resolve_dependency_id(obj) -> Optional[UUID]:
        return obj.dependency_id

    @staticmethod
    def resolve_dependency_bin_name(obj) -> Optional[str]:
        return obj.dependency.bin_name if obj.dependency else None

    @staticmethod
    def resolve_is_valid(obj) -> bool:
        return obj.is_valid


class InstalledBinaryFilterSchema(FilterSchema):
    id: Optional[str] = Field(None, q='id__startswith')
    name: Optional[str] = Field(None, q='name__icontains')
    binprovider: Optional[str] = Field(None, q='binprovider')
    machine_id: Optional[str] = Field(None, q='machine_id__startswith')
    dependency_id: Optional[str] = Field(None, q='dependency_id__startswith')
    version: Optional[str] = Field(None, q='version__icontains')


# ============================================================================
# Machine Endpoints
# ============================================================================

@router.get("/machines", response=List[MachineSchema], url_name="get_machines")
@paginate(CustomPagination)
def get_machines(request, filters: MachineFilterSchema = Query(...)):
    """List all machines."""
    from machine.models import Machine
    return filters.filter(Machine.objects.all()).distinct()


@router.get("/machine/{machine_id}", response=MachineSchema, url_name="get_machine")
def get_machine(request, machine_id: str):
    """Get a specific machine by ID."""
    from machine.models import Machine
    from django.db.models import Q
    return Machine.objects.get(Q(id__startswith=machine_id) | Q(hostname__iexact=machine_id))


@router.get("/machine/current", response=MachineSchema, url_name="get_current_machine")
def get_current_machine(request):
    """Get the current machine."""
    from machine.models import Machine
    return Machine.current()


# ============================================================================
# Dependency Endpoints
# ============================================================================

@router.get("/dependencies", response=List[DependencySchema], url_name="get_dependencies")
@paginate(CustomPagination)
def get_dependencies(request, filters: DependencyFilterSchema = Query(...)):
    """List all dependencies."""
    from machine.models import Dependency
    return filters.filter(Dependency.objects.all()).distinct()


@router.get("/dependency/{dependency_id}", response=DependencySchema, url_name="get_dependency")
def get_dependency(request, dependency_id: str):
    """Get a specific dependency by ID or bin_name."""
    from machine.models import Dependency
    from django.db.models import Q
    try:
        return Dependency.objects.get(Q(id__startswith=dependency_id))
    except Dependency.DoesNotExist:
        return Dependency.objects.get(bin_name__iexact=dependency_id)


# ============================================================================
# InstalledBinary Endpoints
# ============================================================================

@router.get("/binaries", response=List[InstalledBinarySchema], url_name="get_binaries")
@paginate(CustomPagination)
def get_binaries(request, filters: InstalledBinaryFilterSchema = Query(...)):
    """List all installed binaries."""
    from machine.models import InstalledBinary
    return filters.filter(InstalledBinary.objects.all().select_related('machine', 'dependency')).distinct()


@router.get("/binary/{binary_id}", response=InstalledBinarySchema, url_name="get_binary")
def get_binary(request, binary_id: str):
    """Get a specific installed binary by ID."""
    from machine.models import InstalledBinary
    return InstalledBinary.objects.select_related('machine', 'dependency').get(id__startswith=binary_id)


@router.get("/binary/by-name/{name}", response=List[InstalledBinarySchema], url_name="get_binaries_by_name")
def get_binaries_by_name(request, name: str):
    """Get all installed binaries with the given name."""
    from machine.models import InstalledBinary
    return list(InstalledBinary.objects.filter(name__iexact=name).select_related('machine', 'dependency'))
