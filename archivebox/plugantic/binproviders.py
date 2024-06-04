__package__ = 'archivebox.plugantic'

import os
import shutil
import operator

from typing import Callable, Any, Optional, Type, Dict, Annotated, ClassVar, Literal, cast, TYPE_CHECKING
from typing_extensions import Self
from abc import ABC, abstractmethod
from collections import namedtuple
from pathlib import Path
from subprocess import run, PIPE

from pydantic_core import core_schema, ValidationError
from pydantic import BaseModel, Field, TypeAdapter, AfterValidator, validate_call, GetCoreSchemaHandler



def func_takes_args_or_kwargs(lambda_func: Callable[..., Any]) -> bool:
    """returns True if a lambda func takes args/kwargs of any kind, otherwise false if it's pure/argless"""
    code = lambda_func.__code__
    has_args = code.co_argcount > 0
    has_varargs = code.co_flags & 0x04 != 0
    has_varkw = code.co_flags & 0x08 != 0
    return has_args or has_varargs or has_varkw


def is_semver_str(semver: Any) -> bool:
    if isinstance(semver, str):
        return (semver.count('.') == 2 and semver.replace('.', '').isdigit())
    return False

def semver_to_str(semver: tuple[int, int, int] | str) -> str:
    if isinstance(semver, (list, tuple)):
        return '.'.join(str(chunk) for chunk in semver)
    if is_semver_str(semver):
        return semver
    raise ValidationError('Tried to convert invalid SemVer: {}'.format(semver))


SemVerTuple = namedtuple('SemVerTuple', ('major', 'minor', 'patch'), defaults=(0, 0, 0))
SemVerParsableTypes = str | tuple[str | int, ...] | list[str | int]

class SemVer(SemVerTuple):
    major: int
    minor: int = 0
    patch: int = 0

    if TYPE_CHECKING:
        full_text: str | None = ''

    def __new__(cls, *args, full_text=None, **kwargs):
        # '1.1.1'
        if len(args) == 1 and is_semver_str(args[0]):
            result = SemVer.parse(args[0])

        # ('1', '2', '3')
        elif len(args) == 1 and isinstance(args[0], (tuple, list)):
            result = SemVer.parse(args[0])

        # (1, '2', None)
        elif not all(isinstance(arg, (int, type(None))) for arg in args):
            result = SemVer.parse(args)

        # (None)
        elif all(chunk in ('', 0, None) for chunk in (*args, *kwargs.values())):
            result = None

        # 1, 2, 3
        else:
            result = SemVerTuple.__new__(cls, *args, **kwargs)

        if result is not None:
            # add first line as extra hidden metadata so it can be logged without having to re-run version cmd
            result.full_text = full_text or str(result)
        return result

    @classmethod
    def parse(cls, version_stdout: SemVerParsableTypes) -> Self | None:
        """
        parses a version tag string formatted like into (major, minor, patch) ints
        'Google Chrome 124.0.6367.208'             -> (124, 0, 6367)
        'GNU Wget 1.24.5 built on darwin23.2.0.'   -> (1, 24, 5)
        'curl 8.4.0 (x86_64-apple-darwin23.0) ...' -> (8, 4, 0)
        '2024.04.09'                               -> (2024, 4, 9)

        """
        # print('INITIAL_VALUE', type(version_stdout).__name__, version_stdout)

        if isinstance(version_stdout, (tuple, list)):
            version_stdout = '.'.join(str(chunk) for chunk in version_stdout)
        elif isinstance(version_stdout, bytes):
            version_stdout = version_stdout.decode()
        elif not isinstance(version_stdout, str):
            version_stdout = str(version_stdout)
        
        # no text to work with, return None immediately
        if not version_stdout.strip():
            # raise Exception('Tried to parse semver from empty version output (is binary installed and available?)')
            return None

        just_numbers = lambda col: col.lower().strip('v').split('+')[0].split('-')[0].split('_')[0]
        contains_semver = lambda col: (
            col.count('.') in (1, 2, 3)
            and all(chunk.isdigit() for chunk in col.split('.')[:3])  # first 3 chunks can only be nums
        )

        full_text = version_stdout.split('\n')[0].strip()
        first_line_columns = full_text.split()[:4]
        version_columns = list(filter(contains_semver, map(just_numbers, first_line_columns)))
        
        # could not find any column of first line that looks like a version number, despite there being some text
        if not version_columns:
            # raise Exception('Failed to parse semver from version command output: {}'.format(' '.join(first_line_columns)))
            return None

        # take first col containing a semver, and truncate it to 3 chunks (e.g. 2024.04.09.91) -> (2024, 04, 09)
        first_version_tuple = version_columns[0].split('.', 3)[:3]

        # print('FINAL_VALUE', first_version_tuple)

        return cls(*(int(chunk) for chunk in first_version_tuple), full_text=full_text)

    def __str__(self):
        return '.'.join(str(chunk) for chunk in self)

    # @classmethod
    # def __get_pydantic_core_schema__(cls, source: Type[Any], handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
    #     default_schema = handler(source)
    #     return core_schema.no_info_after_validator_function(
    #         cls.parse,
    #         default_schema,
    #         serialization=core_schema.plain_serializer_function_ser_schema(
    #             lambda semver: str(semver),
    #             info_arg=False,
    #             return_schema=core_schema.str_schema(),
    #         ),
    #     )

assert SemVer(None) == None
assert SemVer('') == None
assert SemVer.parse('') == None
assert SemVer(1) == (1, 0, 0)
assert SemVer(1, 2) == (1, 2, 0)
assert SemVer('1.2+234234') == (1, 2, 0)
assert SemVer((1, 2, 3)) == (1, 2, 3)
assert getattr(SemVer((1, 2, 3)), 'full_text') == '1.2.3'
assert SemVer(('1', '2', '3')) == (1, 2, 3)
assert SemVer.parse('5.6.7') == (5, 6, 7)
assert SemVer.parse('124.0.6367.208') == (124, 0, 6367)
assert SemVer.parse('Google Chrome 124.1+234.234') == (124, 1, 0)
assert SemVer.parse('Google Ch1rome 124.0.6367.208') == (124, 0, 6367)
assert SemVer.parse('Google Chrome 124.0.6367.208+beta_234. 234.234.123\n123.456.324') == (124, 0, 6367)
assert getattr(SemVer.parse('Google Chrome 124.0.6367.208+beta_234. 234.234.123\n123.456.324'), 'full_text') == 'Google Chrome 124.0.6367.208+beta_234. 234.234.123'
assert SemVer.parse('Google Chrome') == None

@validate_call
def bin_name(bin_path_or_name: str | Path) -> str:
    name = Path(bin_path_or_name).name
    assert len(name) > 1
    assert name.replace('-', '').replace('_', '').replace('.', '').isalnum(), (
        f'Binary name can only contain a-Z0-9-_.: {name}')
    return name

BinName = Annotated[str, AfterValidator(bin_name)]

@validate_call
def path_is_file(path: Path | str) -> Path:
    path = Path(path) if isinstance(path, str) else path
    assert path.is_file(), f'Path is not a file: {path}'
    return path

HostExistsPath = Annotated[Path, AfterValidator(path_is_file)]

@validate_call
def path_is_executable(path: HostExistsPath) -> HostExistsPath:
    assert os.access(path, os.X_OK), f'Path is not executable (fix by running chmod +x {path})'
    return path

@validate_call
def path_is_script(path: HostExistsPath) -> HostExistsPath:
    SCRIPT_EXTENSIONS = ('.py', '.js', '.sh')
    assert path.suffix.lower() in SCRIPT_EXTENSIONS, 'Path is not a script (does not end in {})'.format(', '.join(SCRIPT_EXTENSIONS))
    return path

HostExecutablePath = Annotated[HostExistsPath, AfterValidator(path_is_executable)]

@validate_call
def path_is_abspath(path: Path) -> Path:
    return path.resolve()

HostAbsPath = Annotated[HostExistsPath, AfterValidator(path_is_abspath)]
HostBinPath = Annotated[Path, AfterValidator(path_is_abspath), AfterValidator(path_is_file)]


@validate_call
def bin_abspath(bin_path_or_name: BinName | Path) -> HostBinPath | None:
    assert bin_path_or_name

    if str(bin_path_or_name).startswith('/'):
        # already a path, get its absolute form
        abspath = Path(bin_path_or_name).resolve()
    else:
        # not a path yet, get path using os.which
        binpath = shutil.which(bin_path_or_name)
        if not binpath:
            return None
        abspath = Path(binpath).resolve()

    try:
        return TypeAdapter(HostBinPath).validate_python(abspath)
    except ValidationError:
        return None


@validate_call
def bin_version(bin_path: HostBinPath, args=('--version',)) -> SemVer | None:
    return SemVer(run([bin_path, *args], stdout=PIPE).stdout.strip().decode())


class InstalledBin(BaseModel):
    abspath: HostBinPath
    version: SemVer


def is_valid_install_string(pkgs_str: str) -> str:
    """Make sure a string is a valid install string for a package manager, e.g. 'yt-dlp ffmpeg'"""
    assert pkgs_str
    assert all(len(pkg) > 1 for pkg in pkgs_str.split(' '))
    return pkgs_str

def is_valid_python_dotted_import(import_str: str) -> str:
    assert import_str and import_str.replace('.', '').replace('_', '').isalnum()
    return import_str

InstallStr = Annotated[str, AfterValidator(is_valid_install_string)]

LazyImportStr = Annotated[str, AfterValidator(is_valid_python_dotted_import)]

ProviderHandler = Callable[..., Any] | Callable[[], Any]                               # must take no args [], or [bin_name: str, **kwargs]
#ProviderHandlerStr = Annotated[str, AfterValidator(lambda s: s.startswith('self.'))]
ProviderHandlerRef = LazyImportStr | ProviderHandler
ProviderLookupDict = Dict[str, LazyImportStr]
ProviderType = Literal['abspath', 'version', 'subdeps', 'install']


# class Host(BaseModel):
#     machine: str
#     system: str
#     platform: str
#     in_docker: bool
#     in_qemu: bool
#     python: str

BinProviderName = Literal['env', 'pip', 'apt', 'brew', 'npm', 'vendor']


class BinProvider(ABC, BaseModel):
    name: BinProviderName
    
    abspath_provider: ProviderLookupDict = Field(default={'*': 'self.on_get_abspath'}, exclude=True)
    version_provider: ProviderLookupDict = Field(default={'*': 'self.on_get_version'}, exclude=True)
    subdeps_provider: ProviderLookupDict = Field(default={'*': 'self.on_get_subdeps'}, exclude=True)
    install_provider: ProviderLookupDict = Field(default={'*': 'self.on_install'}, exclude=True)

    _abspath_cache: ClassVar = {}
    _version_cache: ClassVar = {}
    _install_cache: ClassVar = {}

    # def provider_version(self) -> SemVer | None:
    #     """Version of the actual underlying package manager (e.g. pip v20.4.1)"""
    #     if self.name in ('env', 'vendor'):
    #         return SemVer('0.0.0')
    #     installer_binpath = Path(shutil.which(self.name)).resolve()
    #     return bin_version(installer_binpath)

    # def provider_host(self) -> Host:
    #     """Information about the host env, archictecture, and OS needed to select & build packages"""
    #     p = platform.uname()
    #     return Host(
    #         machine=p.machine,
    #         system=p.system,
    #         platform=platform.platform(),
    #         python=sys.implementation.name,
    #         in_docker=os.environ.get('IN_DOCKER', '').lower() == 'true',
    #         in_qemu=os.environ.get('IN_QEMU', '').lower() == 'true',
    #     )

    def get_default_providers(self):
        return self.get_providers_for_bin('*')

    def resolve_provider_func(self, provider_func: ProviderHandlerRef | None) -> ProviderHandler | None:
        if provider_func is None:
            return None

        # if provider_func is a dotted path to a function on self, swap it for the actual function
        if isinstance(provider_func, str) and provider_func.startswith('self.'):
            provider_func = getattr(self, provider_func.split('self.', 1)[-1])

        # if provider_func is a dot-formatted import string, import the function
        if isinstance(provider_func, str):
            from django.utils.module_loading import import_string

            package_name, module_name, classname, path = provider_func.split('.', 3)   # -> abc, def, ghi.jkl

            # get .ghi.jkl nested attr present on module abc.def
            imported_module = import_string(f'{package_name}.{module_name}.{classname}')
            provider_func = operator.attrgetter(path)(imported_module)

            # # abc.def.ghi.jkl  -> 1, 2, 3
            # for idx in range(1, len(path)):
            #     parent_path = '.'.join(path[:-idx])  # abc.def.ghi
            #     try:
            #         parent_module = import_string(parent_path)
            #         provider_func = getattr(parent_module, path[-idx])
            #     except AttributeError, ImportError:
            #         continue

        assert TypeAdapter(ProviderHandler).validate_python(provider_func), (
            f'{self.__class__.__name__} provider func for {bin_name} was not a function or dotted-import path: {provider_func}')

        return provider_func

    @validate_call
    def get_providers_for_bin(self, bin_name: str) -> ProviderLookupDict:
        providers_for_bin = {
            'abspath': self.abspath_provider.get(bin_name),
            'version': self.version_provider.get(bin_name),
            'subdeps': self.subdeps_provider.get(bin_name),
            'install': self.install_provider.get(bin_name),
        }
        only_set_providers_for_bin = {k: v for k, v in providers_for_bin.items() if v is not None}
        
        return only_set_providers_for_bin

    @validate_call
    def get_provider_for_action(self, bin_name: BinName, provider_type: ProviderType, default_provider: Optional[ProviderHandlerRef]=None, overrides: Optional[ProviderLookupDict]=None) -> ProviderHandler:
        """
        Get the provider func for a given key + Dict of provider callbacks + fallback default provider.
        e.g. get_provider_for_action(bin_name='yt-dlp', 'install', default_provider=self.on_install, ...) -> Callable
        """

        provider_func_ref = (
            (overrides or {}).get(provider_type)
            or self.get_providers_for_bin(bin_name).get(provider_type)
            or self.get_default_providers().get(provider_type)
            or default_provider
        )
        # print('getting provider for action', bin_name, provider_type, provider_func)

        provider_func = self.resolve_provider_func(provider_func_ref)

        assert provider_func, f'No {self.name} provider func was found for {bin_name} in: {self.__class__.__name__}.'

        return provider_func

    @validate_call
    def call_provider_for_action(self, bin_name: BinName, provider_type: ProviderType, default_provider: Optional[ProviderHandlerRef]=None, overrides: Optional[ProviderLookupDict]=None, **kwargs) -> Any:
        provider_func: ProviderHandler = self.get_provider_for_action(
            bin_name=bin_name,
            provider_type=provider_type,
            default_provider=default_provider,
            overrides=overrides,
        )
        if not func_takes_args_or_kwargs(provider_func):
            # if it's a pure argless lambdas, dont pass bin_path and other **kwargs
            provider_func_without_args = cast(Callable[[], Any], provider_func)
            return provider_func_without_args()

        provider_func = cast(Callable[..., Any], provider_func)
        return provider_func(bin_name, **kwargs)



    def on_get_abspath(self, bin_name: BinName, **_) -> HostBinPath | None:
        print(f'[*] {self.__class__.__name__}: Getting abspath for {bin_name}...')
        try:
            return bin_abspath(bin_name)
        except ValidationError:
            return None

    def on_get_version(self, bin_name: BinName, abspath: Optional[HostBinPath]=None, **_) -> SemVer | None:
        abspath = abspath or self._abspath_cache.get(bin_name) or self.get_abspath(bin_name)
        if not abspath: return None

        print(f'[*] {self.__class__.__name__}: Getting version for {bin_name}...')
        try:
            return bin_version(abspath)
        except ValidationError:
            return None

    def on_get_subdeps(self, bin_name: BinName, **_) -> InstallStr:
        print(f'[*] {self.__class__.__name__}: Getting subdependencies for {bin_name}')
        # ... subdependency calculation logic here
        return TypeAdapter(InstallStr).validate_python(bin_name)

    @abstractmethod
    def on_install(self, bin_name: BinName, subdeps: Optional[InstallStr]=None, **_):
        subdeps = subdeps or self.get_subdeps(bin_name)
        print(f'[*] {self.__class__.__name__}: Installing subdependencies for {bin_name} ({subdeps})')
        # ... install logic here
        assert True


    @validate_call
    def get_abspath(self, bin_name: BinName, overrides: Optional[ProviderLookupDict]=None) -> HostBinPath | None:
        abspath = self.call_provider_for_action(
            bin_name=bin_name,
            provider_type='abspath',
            default_provider=self.on_get_abspath,
            overrides=overrides,
        )
        if not abspath:
            return None
        result = TypeAdapter(HostBinPath).validate_python(abspath)
        self._abspath_cache[bin_name] = result
        return result

    @validate_call
    def get_version(self, bin_name: BinName, abspath: Optional[HostBinPath]=None, overrides: Optional[ProviderLookupDict]=None) -> SemVer | None:
        version = self.call_provider_for_action(
            bin_name=bin_name,
            provider_type='version',
            default_provider=self.on_get_version,
            overrides=overrides,
            abspath=abspath,
        )
        if not version:
            return None
        result = SemVer(version)
        self._version_cache[bin_name] = result
        return result

    @validate_call
    def get_subdeps(self, bin_name: BinName, overrides: Optional[ProviderLookupDict]=None) -> InstallStr:
        subdeps = self.call_provider_for_action(
            bin_name=bin_name,
            provider_type='subdeps',
            default_provider=self.on_get_subdeps,
            overrides=overrides,
        )
        if not subdeps:
            subdeps = bin_name
        result = TypeAdapter(InstallStr).validate_python(subdeps)
        return result

    @validate_call
    def install(self, bin_name: BinName, overrides: Optional[ProviderLookupDict]=None) -> InstalledBin | None:
        subdeps = self.get_subdeps(bin_name, overrides=overrides)

        self.call_provider_for_action(
            bin_name=bin_name,
            provider_type='install',
            default_provider=self.on_install,
            overrides=overrides,
            subdeps=subdeps,
        )

        installed_abspath = self.get_abspath(bin_name)
        assert installed_abspath, f'Unable to find {bin_name} abspath after installing with {self.name}'

        installed_version = self.get_version(bin_name, abspath=installed_abspath)
        assert installed_version, f'Unable to find {bin_name} version after installing with {self.name}'
        
        result = InstalledBin(abspath=installed_abspath, version=installed_version)
        self._install_cache[bin_name] = result
        return result

    @validate_call
    def load(self, bin_name: BinName, overrides: Optional[ProviderLookupDict]=None, cache: bool=False) -> InstalledBin | None:
        installed_abspath = None
        installed_version = None

        if cache:
            installed_bin = self._install_cache.get(bin_name)
            if installed_bin:
                return installed_bin
            installed_abspath = self._abspath_cache.get(bin_name)
            installed_version = self._version_cache.get(bin_name)


        installed_abspath = installed_abspath or self.get_abspath(bin_name, overrides=overrides)
        if not installed_abspath:
            return None

        installed_version = installed_version or self.get_version(bin_name, abspath=installed_abspath, overrides=overrides)
        if not installed_version:
            return None

        return InstalledBin(abspath=installed_abspath, version=installed_version)

    @validate_call
    def load_or_install(self, bin_name: BinName, overrides: Optional[ProviderLookupDict]=None, cache: bool=True) -> InstalledBin | None:
        installed = self.load(bin_name, overrides=overrides, cache=cache)
        if not installed:
            installed = self.install(bin_name, overrides=overrides)
        return installed


class PipProvider(BinProvider):
    name: BinProviderName = 'pip'

    def on_install(self, bin_name: str, subdeps: Optional[InstallStr]=None, **_):
        subdeps = subdeps or self.on_get_subdeps(bin_name)
        print(f'[*] {self.__class__.__name__}: Installing subdependencies for {bin_name} ({subdeps})')
        
        proc = run(['pip', 'install', '--upgrade', *subdeps.split(' ')], stdout=PIPE, stderr=PIPE)
        
        if proc.returncode != 0:
            print(proc.stdout.strip().decode())
            print(proc.stderr.strip().decode())
            raise Exception(f'{self.__class__.__name__}: install got returncode {proc.returncode} while installing {subdeps}: {subdeps}')


class AptProvider(BinProvider):
    name: BinProviderName = 'apt'
    
    subdeps_provider: ProviderLookupDict = {
        'yt-dlp': lambda: 'yt-dlp ffmpeg',
    }

    def on_install(self, bin_name: BinName, subdeps: Optional[InstallStr]=None, **_):
        subdeps = subdeps or self.on_get_subdeps(bin_name)
        print(f'[*] {self.__class__.__name__}: Installing subdependencies for {bin_name} ({subdeps})')
        
        run(['apt-get', 'update', '-qq'])
        proc = run(['apt-get', 'install', '-y', *subdeps.split(' ')], stdout=PIPE, stderr=PIPE)
        
        if proc.returncode != 0:
            print(proc.stdout.strip().decode())
            print(proc.stderr.strip().decode())
            raise Exception(f'{self.__class__.__name__} install got returncode {proc.returncode} while installing {subdeps}: {subdeps}')

class BrewProvider(BinProvider):
    name: BinProviderName = 'brew'

    def on_install(self, bin_name: str, subdeps: Optional[InstallStr]=None, **_):
        subdeps = subdeps or self.on_get_subdeps(bin_name)
        print(f'[*] {self.__class__.__name__}: Installing subdependencies for {bin_name} ({subdeps})')
        
        proc = run(['brew', 'install', *subdeps.split(' ')], stdout=PIPE, stderr=PIPE)
        
        if proc.returncode != 0:
            print(proc.stdout.strip().decode())
            print(proc.stderr.strip().decode())
            raise Exception(f'{self.__class__.__name__} install got returncode {proc.returncode} while installing {subdeps}: {subdeps}')


class EnvProvider(BinProvider):
    name: BinProviderName = 'env'

    abspath_provider: ProviderLookupDict = {
        # 'python': lambda: Path('/opt/homebrew/Cellar/python@3.10/3.10.14/Frameworks/Python.framework/Versions/3.10/bin/python3.10'),
    }
    version_provider: ProviderLookupDict = {
        # 'python': lambda: '{}.{}.{}'.format(*sys.version_info[:3]),
    }

    def on_install(self, bin_name: BinName, subdeps: Optional[InstallStr]=None, **_):
        """The env provider is ready-only and does not install any packages, so this is a no-op"""
        pass
