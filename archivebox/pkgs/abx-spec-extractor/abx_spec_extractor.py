__order__ = 10

import os

from typing import Optional, List, Annotated, Tuple
from pathlib import Path

from pydantic import AfterValidator
from abx_pkg import BinName


import abx


def assert_no_empty_args(args: List[str]) -> List[str]:
    assert all(len(arg) for arg in args)
    return args

ExtractorName = Annotated[str, AfterValidator(lambda s: s.isidentifier())]

HandlerFuncStr = Annotated[str, AfterValidator(lambda s: s.startswith('self.'))]
CmdArgsList = Annotated[List[str] | Tuple[str, ...], AfterValidator(assert_no_empty_args)]


@abx.hookspec
@abx.hookimpl
def get_EXTRACTORS():
    return {}

@abx.hookspec
@abx.hookimpl
def extract(uri: str, config: dict | None=None):
    return {}

@abx.hookspec(firstresult=True)
@abx.hookimpl(trylast=True)
def should_extract(uri: str, extractor: str, config: dict | None=None):
    return False


class BaseExtractor:
    name: ExtractorName
    binary: BinName

    default_args: CmdArgsList = []
    extra_args: CmdArgsList = []

    def get_output_path(self, snapshot) -> Path:
        return Path(self.__class__.__name__.lower())

    def should_extract(self, uri: str, config: dict | None=None) -> bool:
        try:
            assert self.detect_installed_binary().version
        except Exception:
            raise
            # could not load binary
            return False
        
        # output_dir = self.get_output_path(snapshot)
        # if output_dir.glob('*.*'):
        #     return False
        return True

    # @abx.hookimpl
    # def extract(self, snapshot_id: str) -> Dict[str, Any]:
    #     from core.models import Snapshot
    #     from archivebox import CONSTANTS
        
    #     snapshot = Snapshot.objects.get(id=snapshot_id)
        
    #     if not self.should_extract(snapshot.url):
    #         return {}
        
    #     status = 'failed'
    #     start_ts = timezone.now()
    #     uplink = self.detect_network_interface()
    #     installed_binary = self.detect_installed_binary()
    #     machine = installed_binary.machine
    #     assert uplink.machine == installed_binary.machine  # it would be *very* weird if this wasn't true
        
    #     output_dir = CONSTANTS.DATA_DIR / '.tmp' / 'extractors' / self.name / str(snapshot.abid)
    #     output_dir.mkdir(parents=True, exist_ok=True)

    #     # execute the extractor binary with the given args
    #     args = [snapshot.url, *self.args] if self.args is not None else [snapshot.url, *self.default_args, *self.extra_args]
    #     cmd = [str(installed_binary.abspath), *args]
    #     proc = self.exec(installed_binary=installed_binary, args=args, cwd=output_dir)

    #     # collect the output
    #     end_ts = timezone.now()
    #     output_files = list(str(path.relative_to(output_dir)) for path in output_dir.glob('**/*.*'))
    #     stdout = proc.stdout.strip()
    #     stderr = proc.stderr.strip()
    #     output_json = None
    #     output_text = stdout
    #     try:
    #         output_json = json.loads(stdout.strip())
    #         output_text = None
    #     except json.JSONDecodeError:
    #         pass
        
    #     errors = []
    #     if proc.returncode == 0:
    #         status = 'success'
    #     else:
    #         errors.append(f'{installed_binary.name} returned non-zero exit code: {proc.returncode}')   

    #     # increment health stats counters
    #     if status == 'success':
    #         machine.record_health_success()
    #         uplink.record_health_success()
    #         installed_binary.record_health_success()
    #     else:
    #         machine.record_health_failure()
    #         uplink.record_health_failure()
    #         installed_binary.record_health_failure()

    #     return {
    #         'extractor': self.name,
            
    #         'snapshot': {
    #             'id': snapshot.id,
    #             'abid': snapshot.abid,
    #             'url': snapshot.url,
    #             'created_by_id': snapshot.created_by_id,
    #         },
            
    #         'machine': {
    #             'id': machine.id,
    #             'abid': machine.abid,
    #             'guid': machine.guid,
    #             'hostname': machine.hostname,
    #             'hw_in_docker': machine.hw_in_docker,
    #             'hw_in_vm': machine.hw_in_vm,
    #             'hw_manufacturer': machine.hw_manufacturer,
    #             'hw_product': machine.hw_product,
    #             'hw_uuid': machine.hw_uuid,
    #             'os_arch': machine.os_arch,
    #             'os_family': machine.os_family,
    #             'os_platform': machine.os_platform,
    #             'os_release': machine.os_release,
    #             'os_kernel': machine.os_kernel,
    #         },
            
    #         'uplink': { 
    #             'id': uplink.id,
    #             'abid': uplink.abid,
    #             'mac_address': uplink.mac_address,
    #             'ip_public': uplink.ip_public,
    #             'ip_local': uplink.ip_local,
    #             'dns_server': uplink.dns_server,
    #             'hostname': uplink.hostname,
    #             'iface': uplink.iface,
    #             'isp': uplink.isp,
    #             'city': uplink.city,
    #             'region': uplink.region,
    #             'country': uplink.country,
    #         },
            
    #         'binary': {
    #             'id': installed_binary.id,
    #             'abid': installed_binary.abid,
    #             'name': installed_binary.name,
    #             'binprovider': installed_binary.binprovider,
    #             'abspath': installed_binary.abspath,
    #             'version': installed_binary.version,
    #             'sha256': installed_binary.sha256,
    #         },

    #         'cmd': cmd,
    #         'stdout': stdout,
    #         'stderr': stderr,
    #         'returncode': proc.returncode,
    #         'start_ts': start_ts,
    #         'end_ts': end_ts,
            
    #         'status': status,
    #         'errors': errors,
    #         'output_dir': str(output_dir.relative_to(CONSTANTS.DATA_DIR)),
    #         'output_files': output_files,
    #         'output_json': output_json or {},
    #         'output_text': output_text or '',
    #     }

    # TODO: move this to a hookimpl
    def exec(self, args: CmdArgsList=(), cwd: Optional[Path]=None, installed_binary=None):
        cwd = cwd or Path(os.getcwd())
        binary = self.load_binary(installed_binary=installed_binary)
        
        return binary.exec(cmd=args, cwd=cwd)
    
    # @cached_property
    @property
    def BINARY(self):
        # import abx.archivebox.reads
        # for binary in abx.archivebox.reads.get_BINARIES().values():
        #     if binary.name == self.binary:
        #         return binary
        raise ValueError(f'Binary {self.binary} not found')
    
    def detect_installed_binary(self):
        from machine.models import InstalledBinary
        # hydrates binary from DB/cache if record of installed version is recent enough
        # otherwise it finds it from scratch by detecting installed version/abspath/sha256 on host
        return InstalledBinary.objects.get_from_db_or_cache(self.BINARY)

    def load_binary(self, installed_binary=None):
        installed_binary = installed_binary or self.detect_installed_binary()
        return installed_binary.load_from_db()
    
    # def detect_network_interface(self):
    #     from machine.models import NetworkInterface
    #     return NetworkInterface.objects.current()
