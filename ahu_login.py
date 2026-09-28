"""Small event-driven AHU Portal client; based on Colin's v1.1.2 source."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import sys
import time
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection
from urllib3.exceptions import HTTPError as UrllibHTTPError

VERSION = '1.2'
GATEWAY_IP, GATEWAY_PORT = '172.16.253.3', 801
TARGET_URL = f'http://{GATEWAY_IP}:{GATEWAY_PORT}/eportal/'
DEFAULT_PREFIXES = ('10.', '172.16.', '172.21.')
LOG = logging.getLogger('ahu')


@dataclass(frozen=True)
class Selection:
    ip: str
    index: int | None = None


def load_env(path):
    # Retain v1.1.2 literal key=value semantics and whitespace handling.
    result = {}
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            result[key.strip()] = value.strip()
    return result


def campus_prefixes(env):
    return tuple(s.strip() for s in env.get('CAMPUS_IP_PREFIXES', '').split(',') if s.strip()) or DEFAULT_PREFIXES


def is_valid_campus_ip(ip, prefixes):
    # Keep existing exclusions; never accept the TUN benchmarking range.
    return bool(ip) and not ip.startswith(('127.', '169.254.', '192.168.', '198.18.', '198.19.')) and ip.startswith(prefixes)


def route_source():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect((GATEWAY_IP, GATEWAY_PORT))
            return probe.getsockname()[0]
    except OSError:
        return None


INVENTORY_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$adapters = @(Get-NetAdapter -IncludeHidden | Where-Object Status -eq 'Up')
$rows = @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.AddressState -eq 'Preferred' -and -not $_.SkipAsSource
} | ForEach-Object {
    $address = $_
    $adapter = $adapters | Where-Object ifIndex -eq $address.InterfaceIndex | Select-Object -First 1
    if ($adapter) {
        [pscustomobject]@{ip=$address.IPAddress; index=[int]$address.InterfaceIndex; hardware=[bool]$adapter.HardwareInterface}
    }
})
ConvertTo-Json -InputObject $rows -Compress
'''


def network_inventory():
    exe = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    process = subprocess.run([str(exe), '-NoProfile', '-NonInteractive', '-Command', INVENTORY_SCRIPT],
                             capture_output=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
    if process.returncode:
        raise OSError('interface_query_failed')
    return json.loads(process.stdout.decode('utf-8-sig'))


def select_fallback(rows, prefixes, preferred=None):
    matches = [row for row in rows if is_valid_campus_ip(row['ip'], prefixes)
               and (preferred is None or int(row['index']) == preferred)]
    if preferred is None:
        physical = [row for row in matches if row.get('hardware')]
        matches = physical or matches
    choices = list(dict.fromkeys(Selection(row['ip'], int(row['index'])) for row in matches))
    if len(choices) > 1:
        raise ValueError('multiple_campus_addresses_set_CAMPUS_INTERFACE_INDEX')
    return choices[0] if choices else None


def get_selection(env, attempts=20):
    prefixes = campus_prefixes(env)
    preferred = int(env['CAMPUS_INTERFACE_INDEX']) if env.get('CAMPUS_INTERFACE_INDEX') else None
    if preferred is not None and not 0 < preferred < 2**24:
        raise ValueError('invalid_interface_index')
    # No PowerShell on the normal route. At most two scans when fallback is needed:
    # once immediately, once after the existing DHCP wait window.
    for attempt in range(attempts):
        source = route_source()
        if source and is_valid_campus_ip(source, prefixes) and preferred is None:
            LOG.info('selected ip=%s via=route', source)
            return Selection(source)
        if attempt in (0, attempts - 1):
            try:
                rows = network_inventory()
            except (OSError, ValueError, subprocess.SubprocessError):
                LOG.info('interface_query_failed')
            else:
                choice = select_fallback(rows, prefixes, preferred)
                if choice:
                    LOG.info('selected ip=%s interface=%s via=fallback route_source=%s', choice.ip, choice.index, source)
                    return choice
        if attempt < attempts - 1:
            time.sleep(1)
    return None


class SourceAdapter(HTTPAdapter):
    def __init__(self, choice):
        self.choice = choice
        super().__init__(max_retries=0)

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        kwargs['source_address'] = (self.choice.ip, 0)
        options = list(HTTPConnection.default_socket_options)
        if self.choice.index is not None:
            # Windows IP_UNICAST_IF takes a network-byte-order interface index.
            options.append((socket.IPPROTO_IP, 31, struct.pack('!I', self.choice.index)))
        kwargs['socket_options'] = options
        return super().init_poolmanager(connections, maxsize, block, **kwargs)


def payload_for(ip, env):
    return {'c': 'Portal', 'a': 'login', 'callback': 'dr1003', 'login_method': '1',
            'user_account': env['CAMPUS_ACCOUNT'], 'user_password': env['CAMPUS_PASSWORD'],
            'wlan_user_ip': ip, 'jsVersion': '3.3.2', 'terminal_type': '1', 'v': '7379', 'lang': 'zh-cn'}


def classify_response(status, text):
    if status != 200:
        return 4, f'http_{status}'
    text = text.strip().lstrip('\ufeff')
    match = re.fullmatch(r'dr1003\s*\((.*)\)\s*;?', text, re.DOTALL)
    try:
        data = json.loads(match.group(1) if match else text)
    except (ValueError, RecursionError):
        return 6, 'invalid_response'
    if not isinstance(data, dict):
        return 6, 'invalid_response'
    if str(data.get('result')) == '1':
        return 0, 'authenticated'
    if str(data.get('result')) == '0' and str(data.get('ret_code')) == '2':
        return 0, 'already_online'
    if str(data.get('result')) == '0':
        return 5, 'authentication_rejected'
    return 6, 'unknown_response'


def request_portal(choice, env, probe=False):
    # No global proxy/route changes. Bind only this connection, never follow redirects.
    try:
        with requests.Session() as session:
            session.trust_env = False
            session.mount(TARGET_URL, SourceAdapter(choice))
            params = None if probe else payload_for(choice.ip, env)
            with session.get(TARGET_URL, params=params, timeout=6, allow_redirects=False, stream=True) as response:
                if probe:
                    return 0, f'gateway_http_{response.status_code}_no_login_sent'
                body = response.raw.read(65537, decode_content=True)
                if len(body) > 65536:
                    return 6, 'response_too_large'
                return classify_response(response.status_code, body.decode('utf-8', errors='replace'))
    except (OSError, requests.RequestException, UrllibHTTPError) as error:
        # Never write exception text / request URL / response body: they can echo secrets.
        LOG.info('request_failed type=%s', type(error).__name__)
        return 4, 'network_error'


def main(argv=None):
    parser = argparse.ArgumentParser(description='AHU AutoLogin')
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('--diagnose', action='store_true', help='IP selection only; no authentication')
    parser.add_argument('--probe', action='store_true', help='Credential-free gateway HTTP check')
    parser.add_argument('--config-dir', type=Path)
    parser.add_argument('--delay', type=int, choices=(0, 15, 20, 30), default=0)
    args = parser.parse_args(argv)
    directory = args.config_dir or Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
    handler = None
    try:
        if args.delay:
            time.sleep(args.delay)
        handler = RotatingFileHandler(directory / 'autologin.log', maxBytes=512 * 1024, backupCount=1, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        LOG.addHandler(handler)
        LOG.setLevel(logging.INFO)
        LOG.info('start version=%s', VERSION)
        config = directory / '.env'
        env = load_env(config) if config.exists() else {}
        if not (args.diagnose or args.probe) and (not env.get('CAMPUS_ACCOUNT') or not env.get('CAMPUS_PASSWORD')):
            code, status = 3, 'missing_account_or_password'
        else:
            choice = get_selection(env)
            if choice is None:
                code, status = 2, 'no_campus_ip'
            elif args.diagnose:
                code, status = 0, 'ip_selected_no_login_sent'
            else:
                code, status = request_portal(choice, env, args.probe)
        LOG.info('exit code=%s status=%s', code, status)
        if sys.stdout:
            print(f'code={code} status={status}')
        return code
    except ValueError:
        LOG.error('exit code=3 status=invalid_or_ambiguous_interface_config')
        return 3
    except (OSError, subprocess.SubprocessError):
        LOG.error('exit code=4 status=local_io_error')
        return 4
    finally:
        if handler:
            LOG.removeHandler(handler)
            handler.close()


if __name__ == '__main__':
    sys.exit(main())
