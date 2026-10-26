"""Read-only tunnel discovery and stable GUID/LUID checks; never changes routes."""

import ctypes as C
import ipaddress
import json
import sys
import uuid

from .. import process as subprocess
from .windows_wfp import GUID, U8, U32, U64, PTR


class IfRow(C.Structure):
    # MIB_IF_ROW2 prefix. Extra storage covers the SDK's remaining statistics.
    _fields_ = [("luid", U64), ("index", U32), ("guid", GUID),
                ("alias", C.c_wchar * 257), ("description", C.c_wchar * 257),
                ("physical_length", U32), ("physical", U8 * 32), ("permanent", U8 * 32),
                ("mtu", U32), ("type", U32), ("tunnel_type", U32), ("media_type", U32),
                ("physical_medium", U32), ("access", U32), ("direction", U32),
                ("flags", U8), ("oper_status", U32), ("admin_status", U32), ("tail", U8 * 2048)]


def interface(guid):
    key = GUID(uuid.UUID(str(guid)))
    api = C.WinDLL("iphlpapi", use_last_error=True)
    api.ConvertInterfaceGuidToLuid.argtypes = [C.POINTER(GUID), C.POINTER(U64)]
    api.GetIfEntry2.argtypes = [PTR]
    luid = U64()
    if api.ConvertInterfaceGuidToLuid(C.byref(key), C.byref(luid)):
        return None
    row = IfRow()
    row.luid = luid.value
    if api.GetIfEntry2(C.byref(row)):
        return None
    return {"guid": str(key), "luid": luid.value, "index": row.index,
            "name": row.alias, "up": row.oper_status == 1 and row.admin_status == 1}


def live(tunnel):
    if sys.platform != "win32":
        return False
    try:
        current = interface(tunnel["guid"])
        return bool(current and current["up"] and current["luid"] == tunnel["luid"]
                    and current["index"] == tunnel["index"])
    except Exception:
        return False


def list_tunnels():
    script = r'''
$ErrorActionPreference = 'Stop'
@((Get-NetAdapter -IncludeHidden | Where-Object {
    -not $_.HardwareInterface -and ($_.ifType -in 53,131 -or
      ($_.Name + ' ' + $_.InterfaceDescription) -match '(?i)tun|tap|wireguard|wintun|clash|mihomo|sing-box|tailscale|openvpn')
}) | ForEach-Object {
    $adapter = $_
    $addresses = @(Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -ErrorAction SilentlyContinue |
      Where-Object { $_.AddressState -in 'Preferred','Deprecated' } | Select-Object -ExpandProperty IPAddress)
    [pscustomobject]@{ guid = $adapter.InterfaceGuid.ToString(); addresses = $addresses }
}) | ConvertTo-Json -Compress -Depth 4
'''
    output = subprocess.check_output(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                     text=True, encoding="utf-8", errors="replace", stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=20)
    records = json.loads(output or "[]")
    if isinstance(records, dict):
        records = [records]
    result = []
    for record in records:
        current = interface(record["guid"])
        if not current:
            continue
        addresses = []
        for value in record.get("addresses", []):
            ip = ipaddress.ip_address(value)
            if not (ip.is_link_local or ip.is_loopback or ip.is_unspecified or ip.is_multicast):
                addresses.append(str(ip))
        current["addresses"] = sorted(set(addresses))
        result.append(current)
    return result
