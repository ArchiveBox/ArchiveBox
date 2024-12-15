import os
import json
import socket
import urllib.request
from typing import Dict, Any
from pathlib import Path
import subprocess
import platform
import tempfile
from datetime import datetime

import psutil
import machineid             # https://github.com/keygen-sh/py-machineid

from rich import print

PACKAGE_DIR = Path(__file__).parent
DATA_DIR = Path(os.getcwd()).resolve()

def get_vm_info():
    hw_in_docker = bool(os.getenv('IN_DOCKER', False) in ('1', 'true', 'True', 'TRUE'))
    hw_in_vm = False
    try:
        # check for traces of docker/containerd/podman in cgroup
        with open('/proc/self/cgroup', 'r') as procfile:
            for line in procfile:
                cgroup = line.strip()  # .split('/', 1)[-1].lower()
                if 'docker' in cgroup or 'containerd' in cgroup or 'podman' in cgroup:
                    hw_in_docker = True
    except Exception:
        pass
    
    hw_manufacturer = 'Docker' if hw_in_docker else 'Unknown'
    hw_product = 'Container' if hw_in_docker else 'Unknown'
    hw_uuid = machineid.id()
    
    if platform.system().lower() == 'darwin':
        # Get macOS machine info
        hw_manufacturer = 'Apple'
        hw_product = 'Mac'
        try:
            # Hardware:
            #     Hardware Overview:
            #       Model Name: Mac Studio
            #       Model Identifier: Mac13,1
            #       Model Number: MJMV3LL/A
            #       ...
            #       Serial Number (system): M230YYTD77
            #       Hardware UUID: 39A12B50-1972-5910-8BEE-235AD20C8EE3
            #       ...
            result = subprocess.run(['system_profiler', 'SPHardwareDataType'], capture_output=True, text=True, check=True)
            for line in result.stdout.split('\n'):
                if 'Model Name:' in line:
                    hw_product = line.split(':', 1)[-1].strip()
                elif 'Model Identifier:' in line:
                    hw_product += ' ' + line.split(':', 1)[-1].strip()
                elif 'Hardware UUID:' in line:
                    hw_uuid = line.split(':', 1)[-1].strip()
        except Exception:
            pass
    else:
        # get Linux machine info
        try:
            # Getting SMBIOS data from sysfs.
            # SMBIOS 2.8 present.
            # argo-1        | 2024-10-01T10:40:51Z ERR  error="Incoming request ended abruptly: context canceled" connIndex=2 event=1 ingressRule=0 originService=http://archivebox:8000                                                                               │
            # Handle 0x0100, DMI type 1, 27 bytes
            # System Information
            #         Manufacturer: DigitalOcean
            #         Product Name: Droplet
            #         Serial Number: 411922099
            #         UUID: fb65f41c-ec24-4539-beaf-f941903bdb2c
            #         ...
            #         Family: DigitalOcean_Droplet
            dmidecode = subprocess.run(['dmidecode', '-t', 'system'], capture_output=True, text=True, check=True)
            for line in dmidecode.stdout.split('\n'):
                if 'Manufacturer:' in line:
                    hw_manufacturer = line.split(':', 1)[-1].strip()
                elif 'Product Name:' in line:
                    hw_product = line.split(':', 1)[-1].strip()
                elif 'UUID:' in line:
                    hw_uuid = line.split(':', 1)[-1].strip()
        except Exception:
            pass

    # Check for VM fingerprint in manufacturer/product name
    if 'qemu' in hw_product.lower() or 'vbox' in hw_product.lower() or 'lxc' in hw_product.lower() or 'vm' in hw_product.lower():
        hw_in_vm = True
    
    # Check for QEMU explicitly in pmap output
    try:
        result = subprocess.run(['pmap', '1'], capture_output=True, text=True, check=True)
        if 'qemu' in result.stdout.lower():
            hw_in_vm = True
    except Exception:
        pass

    return {
        "hw_in_docker": hw_in_docker,
        "hw_in_vm": hw_in_vm,
        "hw_manufacturer": hw_manufacturer,
        "hw_product": hw_product,
        "hw_uuid": hw_uuid,
    }

def get_public_ip() -> str:
    def fetch_url(url: str) -> str:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.read().decode('utf-8').strip()

    def fetch_dns(pubip_lookup_host: str) -> str:
        return socket.gethostbyname(pubip_lookup_host).strip()

    methods = [
        (lambda: fetch_url("https://ipinfo.io/ip"), lambda r: r),
        (lambda: fetch_url("https://api.ipify.org?format=json"), lambda r: json.loads(r)['ip']),
        (lambda: fetch_dns("myip.opendns.com"), lambda r: r),
        (lambda: fetch_url("http://whatismyip.akamai.com/"), lambda r: r),  # try HTTP as final fallback in case of TLS/system time errors
    ]

    for fetch, parse in methods:
        try:
            result = parse(fetch())
            if result:
                return result
        except Exception:
            continue

    raise Exception("Could not determine public IP address")

def get_local_ip(remote_ip: str='1.1.1.1', remote_port: int=80) -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((remote_ip, remote_port))
            return s.getsockname()[0]
    except Exception:
        pass
    return '127.0.0.1'

ip_addrs = lambda addrs: (a for a in addrs if a.family == socket.AF_INET)
mac_addrs = lambda addrs: (a for a in addrs if a.family == psutil.AF_LINK)

def get_isp_info(ip=None):
    # Get public IP
    try:
        ip = ip or urllib.request.urlopen('https://api.ipify.org').read().decode('utf8')
    except Exception:
        pass
    
    # Get ISP name, city, and country
    data = {}
    try:
        url = f'https://ipapi.co/{ip}/json/'
        response = urllib.request.urlopen(url)
        data = json.loads(response.read().decode())
    except Exception:
        pass
    
    isp = data.get('org', 'Unknown')
    city = data.get('city', 'Unknown')
    region = data.get('region', 'Unknown')
    country = data.get('country_name', 'Unknown')
    
    # Get system DNS resolver servers
    dns_server = None
    try:
        result = subprocess.run(['dig', 'example.com', 'A'], capture_output=True, text=True, check=True).stdout
        dns_server = result.split(';; SERVER: ', 1)[-1].split('\n')[0].split('#')[0].strip()
    except Exception:
        try:
            dns_server = Path('/etc/resolv.conf').read_text().split('nameserver ', 1)[-1].split('\n')[0].strip()
        except Exception:
            dns_server = '127.0.0.1'
            print(f'[red]:warning: WARNING: Could not determine DNS server, using {dns_server}[/red]')
    
    # Get DNS resolver's ISP name
    # url = f'https://ipapi.co/{dns_server}/json/'
    # dns_isp = json.loads(urllib.request.urlopen(url).read().decode()).get('org', 'Unknown')
    
    return {
        'isp': isp,
        'city': city,
        'region': region,
        'country': country,
        'dns_server': dns_server,
        # 'net_dns_isp': dns_isp,
    }
    
def get_host_network() -> Dict[str, Any]:
    default_gateway_local_ip = get_local_ip()
    gateways = psutil.net_if_addrs()
    
    for interface, ips in gateways.items():
        for local_ip in ip_addrs(ips):
            if default_gateway_local_ip == local_ip.address:
                mac_address = next(mac_addrs(ips)).address
                public_ip = get_public_ip()
                return {
                    "hostname": max([socket.gethostname(), platform.node()], key=len),
                    "iface": interface,
                    "mac_address": mac_address,
                    "ip_local": local_ip.address,
                    "ip_public": public_ip,
                    # "is_behind_nat": local_ip.address != public_ip,
                    **get_isp_info(public_ip),
                }
    
    raise Exception("Could not determine host network info")


def get_os_info() -> Dict[str, Any]:
    os_release = platform.release()
    if platform.system().lower() == 'darwin':
        os_release = 'macOS ' + platform.mac_ver()[0]
    else:
        try:
            os_release = subprocess.run(['lsb_release', '-ds'], capture_output=True, text=True, check=True).stdout.strip()
        except Exception:
            pass
    
    return {
        "os_arch": platform.machine(),
        "os_family": platform.system().lower(),
        "os_platform": platform.platform(),
        "os_kernel": platform.version(),
        "os_release": os_release,
    }

def get_host_stats() -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_usage = psutil.disk_usage(str(tmp_dir))
    app_usage = psutil.disk_usage(str(PACKAGE_DIR))
    data_usage = psutil.disk_usage(str(DATA_DIR))
    mem_usage = psutil.virtual_memory()
    swap_usage = psutil.swap_memory()
    return {
        "cpu_boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
        "cpu_count": psutil.cpu_count(logical=False),
        "cpu_load": psutil.getloadavg(),
        # "cpu_pct": psutil.cpu_percent(interval=1),
        "mem_virt_used_pct": mem_usage.percent,
        "mem_virt_used_gb": round(mem_usage.used / 1024 / 1024 / 1024, 3),
        "mem_virt_free_gb": round(mem_usage.free / 1024 / 1024 / 1024, 3),
        "mem_swap_used_pct": swap_usage.percent,
        "mem_swap_used_gb": round(swap_usage.used / 1024 / 1024 / 1024, 3),
        "mem_swap_free_gb": round(swap_usage.free / 1024 / 1024 / 1024, 3),
        "disk_tmp_used_pct": tmp_usage.percent,
        "disk_tmp_used_gb": round(tmp_usage.used / 1024 / 1024 / 1024, 3),
        "disk_tmp_free_gb": round(tmp_usage.free / 1024 / 1024 / 1024, 3),  # in GB
        "disk_app_used_pct": app_usage.percent,
        "disk_app_used_gb": round(app_usage.used / 1024 / 1024 / 1024, 3),
        "disk_app_free_gb": round(app_usage.free / 1024 / 1024 / 1024, 3),
        "disk_data_used_pct": data_usage.percent,
        "disk_data_used_gb": round(data_usage.used / 1024 / 1024 / 1024, 3),
        "disk_data_free_gb": round(data_usage.free / 1024 / 1024 / 1024, 3),
    }

def get_host_immutable_info(host_info: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in host_info.items()
        if key in ['guid', 'net_mac', 'os_family', 'cpu_arch']
    }
    
def get_host_guid() -> str:
    return machineid.hashed_id('archivebox')

# Example usage
if __name__ == "__main__":
    host_info = {
        'guid': get_host_guid(),
        'os': get_os_info(),
        'vm': get_vm_info(),
        'net': get_host_network(),
        'stats': get_host_stats(),
    }
    print(host_info)

# {
#     'guid': '1cd2dd279f8a854...6943f2384437991a',
#     'os': {
#         'os_arch': 'arm64',
#         'os_family': 'darwin',
#         'os_platform': 'macOS-14.6.1-arm64-arm-64bit',
#         'os_kernel': 'Darwin Kernel Version 23.6.0: Mon Jul 29 21:14:30 PDT 2024; root:xnu-10063.141.2~1/RELEASE_ARM64_T6000',
#         'os_release': 'macOS 14.6.1'
#     },
#     'vm': {'hw_in_docker': False, 'hw_in_vm': False, 'hw_manufacturer': 'Apple', 'hw_product': 'Mac Studio Mac13,1', 'hw_uuid': '39A12B50-...-...-...-...'},
#     'net': {
#         'hostname': 'somehost.sub.example.com',
#         'iface': 'en0',
#         'mac_address': 'ab:cd:ef:12:34:56',
#         'ip_local': '192.168.2.18',
#         'ip_public': '123.123.123.123',
#         'isp': 'AS-SONICTELECOM',
#         'city': 'Berkeley',
#         'region': 'California',
#         'country': 'United States',
#         'dns_server': '192.168.1.1'
#     },
#     'stats': {
#         'cpu_boot_time': '2024-09-24T21:20:16',
#         'cpu_count': 10,
#         'cpu_load': (2.35693359375, 4.013671875, 4.1171875),
#         'mem_virt_used_pct': 66.0,
#         'mem_virt_used_gb': 15.109,
#         'mem_virt_free_gb': 0.065,
#         'mem_swap_used_pct': 89.4,
#         'mem_swap_used_gb': 8.045,
#         'mem_swap_free_gb': 0.955,
#         'disk_tmp_used_pct': 26.0,
#         'disk_tmp_used_gb': 113.1,
#         'disk_tmp_free_gb': 322.028,
#         'disk_app_used_pct': 56.1,
#         'disk_app_used_gb': 2138.796,
#         'disk_app_free_gb': 1675.996,
#         'disk_data_used_pct': 56.1,
#         'disk_data_used_gb': 2138.796,
#         'disk_data_free_gb': 1675.996
#     }
# }
