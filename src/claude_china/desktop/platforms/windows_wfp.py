"""Windows Filtering Platform allowlist, using the built-in user-mode API.

No driver, global firewall defaults, browser policies or proxy settings are
modified. Persistent objects and their restore metadata commit in one WFP
transaction. Only our provider for the requesting Windows user is managed.
"""

import ctypes as C
from contextlib import contextmanager
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
from subprocess import list2cmdline
import sys
import tempfile
import uuid

U8, U16, U32, U64 = C.c_uint8, C.c_uint16, C.c_uint32, C.c_uint64
PTR = C.c_void_p
NAMESPACE = uuid.UUID("ea4f31c9-76c6-4f86-9010-61c8df5311a7")
PROVIDER_MISSING = 0x80320005
SUBLAYER_MISSING = 0x80320007
PERSISTENT = 1
BLOCK, PERMIT = 0x1001, 0x1002
APP_ID = "d78e1e87-8644-4ea5-9437-d809ecefc971"
USER_ID = "af043a0a-b34d-4f86-979c-c90371af6e66"
REMOTE_IP = "b235ae9a-1d64-49b8-a44c-5ff3d9095045"
REMOTE_PORT = "c35a604d-d22b-4e1a-91b4-68f674ee674b"
PROTOCOL = "3971ef2b-623e-4f9a-8cb1-6e79b806b9a7"
LAYERS = {4: "c38d57d1-05a7-4c33-904f-7fbceee60e82",
          6: "4a72393b-319f-44bc-84c3-ba54dcb3b6b4"}


class GUID(C.Structure):
    _fields_ = [("data", U8 * 16)]

    def __init__(self, value=None):
        super().__init__()
        if value is not None:
            self.data[:] = uuid.UUID(str(value)).bytes_le

    def __str__(self):
        return str(uuid.UUID(bytes_le=bytes(self.data)))


class Blob(C.Structure):
    _fields_ = [("size", U32), ("data", C.POINTER(U8))]


class ValueUnion(C.Union):
    _fields_ = [("u8", U8), ("u16", U16), ("u32", U32),
                ("u64", C.POINTER(U64)), ("blob", C.POINTER(Blob)), ("pointer", PTR)]


class Value(C.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", U32), ("value", ValueUnion)]


class Display(C.Structure):
    _fields_ = [("name", C.c_wchar_p), ("description", C.c_wchar_p)]


class Provider(C.Structure):
    _fields_ = [("key", GUID), ("display", Display), ("flags", U32),
                ("data", Blob), ("service", C.c_wchar_p)]


class Sublayer(C.Structure):
    _fields_ = [("key", GUID), ("display", Display), ("flags", U32),
                ("provider", C.POINTER(GUID)), ("data", Blob), ("weight", U16)]


class Condition(C.Structure):
    _fields_ = [("field", GUID), ("match", U32), ("value", Value)]


class Action(C.Structure):
    _fields_ = [("type", U32), ("key", GUID)]


class Context(C.Union):
    _fields_ = [("raw", U64), ("key", GUID)]


class Filter(C.Structure):
    _fields_ = [("key", GUID), ("display", Display), ("flags", U32),
                ("provider", C.POINTER(GUID)), ("data", Blob),
                ("layer", GUID), ("sublayer", GUID), ("weight", Value),
                ("count", U32), ("conditions", C.POINTER(Condition)),
                ("action", Action), ("context", Context), ("reserved", C.POINTER(GUID)),
                ("id", U64), ("effective_weight", Value)]


class EnumTemplate(C.Structure):
    _fields_ = [("provider", C.POINTER(GUID)), ("layer", GUID), ("type", U32),
                ("flags", U32), ("context", PTR), ("count", U32),
                ("conditions", C.POINTER(Condition)), ("action_mask", U32), ("callout", PTR)]


def _check(code):
    if code:
        raise OSError("Windows network filter error: 0x%08x" % code)


def _api():
    dll = C.WinDLL("fwpuclnt.dll", use_last_error=True)
    signatures = {
        "FwpmEngineOpen0": [C.c_wchar_p, U32, PTR, PTR, C.POINTER(PTR)],
        "FwpmEngineClose0": [PTR],
        "FwpmFreeMemory0": [C.POINTER(PTR)],
        "FwpmTransactionBegin0": [PTR, U32],
        "FwpmTransactionCommit0": [PTR],
        "FwpmTransactionAbort0": [PTR],
        "FwpmProviderGetByKey0": [PTR, C.POINTER(GUID), C.POINTER(C.POINTER(Provider))],
        "FwpmProviderAdd0": [PTR, C.POINTER(Provider), PTR],
        "FwpmProviderDeleteByKey0": [PTR, C.POINTER(GUID)],
        "FwpmSubLayerAdd0": [PTR, C.POINTER(Sublayer), PTR],
        "FwpmSubLayerDeleteByKey0": [PTR, C.POINTER(GUID)],
        "FwpmGetAppIdFromFileName0": [C.c_wchar_p, C.POINTER(C.POINTER(Blob))],
        "FwpmFilterAdd0": [PTR, C.POINTER(Filter), PTR, C.POINTER(U64)],
        "FwpmFilterGetByKey0": [PTR, C.POINTER(GUID), C.POINTER(C.POINTER(Filter))],
        "FwpmFilterDeleteByKey0": [PTR, C.POINTER(GUID)],
        "FwpmFilterCreateEnumHandle0": [PTR, C.POINTER(EnumTemplate), C.POINTER(PTR)],
        "FwpmFilterEnum0": [PTR, PTR, U32, C.POINTER(C.POINTER(C.POINTER(Filter))), C.POINTER(U32)],
        "FwpmFilterDestroyEnumHandle0": [PTR, PTR],
    }
    for name, args in signatures.items():
        function = getattr(dll, name)
        function.argtypes = args
        function.restype = U32
    dll.FwpmFreeMemory0.restype = None
    return dll


def current_sid():
    advapi = C.WinDLL("advapi32", use_last_error=True)
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = PTR
    kernel.CloseHandle.argtypes = [PTR]
    kernel.LocalFree.argtypes = [PTR]
    advapi.OpenProcessToken.argtypes = [PTR, U32, C.POINTER(PTR)]
    advapi.GetTokenInformation.argtypes = [PTR, U32, PTR, U32, C.POINTER(U32)]
    advapi.ConvertSidToStringSidW.argtypes = [PTR, C.POINTER(PTR)]
    token = PTR()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, C.byref(token)):
        raise C.WinError()
    try:
        size = U32()
        advapi.GetTokenInformation(token, 1, None, 0, C.byref(size))
        data = C.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, data, size, C.byref(size)):
            raise C.WinError()
        sid = C.cast(data, C.POINTER(PTR))[0]
        string = PTR()
        if not advapi.ConvertSidToStringSidW(sid, C.byref(string)):
            raise C.WinError()
        try:
            return C.wstring_at(string)
        finally:
            kernel.LocalFree(string)
    finally:
        kernel.CloseHandle(token)


@contextmanager
def security_descriptor(sddl):
    advapi = C.WinDLL("advapi32", use_last_error=True)
    kernel = C.WinDLL("kernel32", use_last_error=True)
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [C.c_wchar_p, U32, C.POINTER(PTR), C.POINTER(U32)]
    kernel.LocalFree.argtypes = [PTR]
    descriptor, size = PTR(), U32()
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, C.byref(descriptor), C.byref(size)):
        raise C.WinError()
    try:
        yield descriptor, size.value
    finally:
        kernel.LocalFree(descriptor)


def validate(policies):
    from ..apps import APP_REGISTRY
    allowed = {app.id for app in APP_REGISTRY}
    if not isinstance(policies, dict) or not policies.keys() <= allowed:
        raise ValueError("Invalid network guard applications")
    seen = set()
    for policy in policies.values():
        if not isinstance(policy, dict) or set(policy) != {"executables", "proxy"}:
            raise ValueError("Invalid network guard policy")
        paths = policy["executables"]
        if not isinstance(paths, list) or not 0 < len(paths) <= 128:
            raise ValueError("Invalid executable list")
        for path in paths:
            if not isinstance(path, str) or not os.path.isabs(path) or not path.lower().endswith(".exe") or "\0" in path:
                raise ValueError("Invalid executable path")
            identity = os.path.normcase(str(Path(path).resolve()))
            if identity in seen:
                raise ValueError("Applications cannot share protected executables")
            seen.add(identity)
        endpoint = policy["proxy"]
        if (not isinstance(endpoint, dict) or set(endpoint) != {"addresses", "port"}
                or type(endpoint["port"]) is not int or not 1 <= endpoint["port"] <= 65535
                or not isinstance(endpoint["addresses"], list) or not 1 <= len(endpoint["addresses"]) <= 2):
            raise ValueError("Invalid proxy endpoint")
        for value in endpoint["addresses"]:
            ip = ipaddress.ip_address(value)
            if str(ip) != value or ip.is_unspecified or ip.is_multicast or ip.is_link_local or "%" in value:
                raise ValueError("Invalid proxy IP")


class Engine:
    def __init__(self, owner=None, scope="apps"):
        self.owner = owner or current_sid()
        if not re.fullmatch(r"S-1-(?:\d+-)+\d+", self.owner):
            raise ValueError("Invalid Windows user")
        self.key = GUID(uuid.uuid5(NAMESPACE, self.owner + ":" + scope))
        self.sublayer = GUID(uuid.uuid5(uuid.UUID(str(self.key)), "sublayer"))
        self.api = _api()
        self.handle = PTR()

    def __enter__(self):
        _check(self.api.FwpmEngineOpen0(None, 10, None, None, C.byref(self.handle)))
        return self

    def __exit__(self, *_):
        if self.handle:
            self.api.FwpmEngineClose0(self.handle)
            self.handle = PTR()

    def _free(self, pointer):
        memory = C.cast(pointer, PTR)
        self.api.FwpmFreeMemory0(C.byref(memory))

    def read(self):
        # Container enumeration needs administrator privileges. A specific
        # object lookup uses the read-only ACL granted to the requesting user.
        pointer = C.POINTER(Provider)()
        code = self.api.FwpmProviderGetByKey0(self.handle, C.byref(self.key), C.byref(pointer))
        if code == PROVIDER_MISSING:
            return {}
        _check(code)
        try:
            item = pointer.contents
            if item.data.size > 1024 * 1024:
                raise ValueError("Invalid provider metadata")
            data = json.loads(C.string_at(item.data.data, item.data.size))
            if data.get("schema") != 1 or data.get("owner") != self.owner:
                raise ValueError("Foreign provider metadata")
            policies = data["policies"]
            validate(policies)
            return policies
        finally:
            self._free(pointer)

    def _filters(self, callback):
        for layer in LAYERS.values():
            self._filters_at(layer, callback)

    def _filters_at(self, layer, callback):
        template = EnumTemplate()
        template.layer = GUID(layer)
        template.provider, template.action_mask = C.pointer(self.key), 0xffffffff
        enumeration = PTR()
        _check(self.api.FwpmFilterCreateEnumHandle0(self.handle, C.byref(template), C.byref(enumeration)))
        try:
            while True:
                entries = C.POINTER(C.POINTER(Filter))()
                count = U32()
                _check(self.api.FwpmFilterEnum0(self.handle, enumeration, 128, C.byref(entries), C.byref(count)))
                try:
                    for index in range(count.value):
                        item = entries[index].contents
                        if not item.provider or str(item.provider.contents) != str(self.key):
                            raise ValueError("Foreign filter")
                        callback(item)
                finally:
                    if entries:
                        self._free(entries)
                if count.value < 128:
                    break
        finally:
            self.api.FwpmFilterDestroyEnumHandle0(self.handle, enumeration)

    @staticmethod
    def _value(value):
        if value.type == 1:
            return value.u8
        if value.type == 2:
            return value.u16
        if value.type == 3:
            return value.u32
        if value.type == 4:
            return value.u64.contents.value
        if value.type in (12, 14):
            blob = value.blob.contents
            return C.string_at(blob.data, blob.size).hex()
        if value.type == 11:
            return C.string_at(value.pointer, 16).hex()
        raise ValueError("Unexpected filter condition")

    def _signature(self, item):
        conditions = sorted((str(item.conditions[i].field), item.conditions[i].match,
                             item.conditions[i].value.type, self._value(item.conditions[i].value))
                            for i in range(item.count))
        # BFE may add INDEXED (0x40) as an optimization when storing a filter.
        return (str(item.key), item.flags & ~0x40, str(item.layer), str(item.sublayer),
                item.action.type, item.weight.type, self._value(item.weight), conditions)

    def _build(self, policies, callback):
        """Higher-weight proxy permits precede default deny in our own sublayer.

        Permits are soft: another provider's block is never overridden.
        User SID + exact executable path scope every rule, including loopback.
        """
        advapi = C.WinDLL("advapi32", use_last_error=True)
        kernel = C.WinDLL("kernel32", use_last_error=True)
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [C.c_wchar_p, U32, C.POINTER(PTR), C.POINTER(U32)]
        kernel.LocalFree.argtypes = [PTR]
        descriptor, size = PTR(), U32()
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                "D:(A;;CC;;;" + self.owner + ")", 1, C.byref(descriptor), C.byref(size)):
            raise C.WinError()
        sd = Blob(size.value, C.cast(descriptor, C.POINTER(U8)))
        try:
            for app_id, policy in sorted(policies.items()):
                for path in policy["executables"]:
                    app_blob = C.POINTER(Blob)()
                    # TEMP and installers can return DOS 8.3 aliases. WFP's app
                    # identity must match the kernel's canonical image path.
                    canonical = str(Path(path).resolve())
                    _check(self.api.FwpmGetAppIdFromFileName0(canonical, C.byref(app_blob)))
                    try:
                        for version in (4, 6):
                            self._filter(app_id, path, version, app_blob, sd, None, callback)
                            for address in policy["proxy"]["addresses"]:
                                ip = ipaddress.ip_address(address)
                                if ip.version == version:
                                    self._filter(app_id, path, version, app_blob, sd,
                                                 (ip, policy["proxy"]["port"]), callback)
                    finally:
                        self._free(app_blob)
        finally:
            kernel.LocalFree(descriptor)

    def _filter(self, app_id, path, version, app_blob, sd, endpoint, callback):
        item = Filter()
        suffix = "block" if endpoint is None else str(endpoint[0]) + ":" + str(endpoint[1])
        item.key = GUID(uuid.uuid5(uuid.UUID(str(self.key)), app_id + "|" + path.casefold() + "|" + str(version) + "|" + suffix))
        item.display = Display("Claude China: " + app_id, "Proxy-only outbound network guard")
        item.flags, item.provider = PERSISTENT, C.pointer(self.key)
        item.layer, item.sublayer = GUID(LAYERS[version]), self.sublayer
        weight = U64(100 if endpoint else 1)
        item.weight.type, item.weight.u64 = 4, C.pointer(weight)
        conditions = (Condition * (5 if endpoint else 2))()
        conditions[0].field, conditions[0].value.type = GUID(APP_ID), 12
        conditions[0].value.blob = app_blob
        conditions[1].field, conditions[1].value.type = GUID(USER_ID), 14
        conditions[1].value.blob = C.pointer(sd)
        if endpoint:
            ip, port = endpoint
            conditions[2].field, conditions[2].value.type = GUID(PROTOCOL), 1
            conditions[2].value.u8 = 6  # TCP only; UDP is never implicitly allowed.
            conditions[3].field, conditions[3].value.type = GUID(REMOTE_PORT), 2
            conditions[3].value.u16 = port
            conditions[4].field = GUID(REMOTE_IP)
            if version == 4:
                conditions[4].value.type, conditions[4].value.u32 = 3, int(ip)
            else:
                address = (U8 * 16).from_buffer_copy(ip.packed)
                conditions[4].value.type, conditions[4].value.pointer = 11, C.cast(address, PTR)
        item.count, item.conditions = len(conditions), conditions
        item.action.type = PERMIT if endpoint else BLOCK
        callback(item)

    def verify(self, policies):
        if self.read() != policies:
            return False
        expected = {}
        self._build(policies, lambda item: expected.update({str(item.key): self._signature(item)}))
        for value, signature in expected.items():
            key, pointer = GUID(value), C.POINTER(Filter)()
            code = self.api.FwpmFilterGetByKey0(self.handle, C.byref(key), C.byref(pointer))
            if code == 0x80320003:  # FWP_E_FILTER_NOT_FOUND
                return False
            _check(code)
            try:
                item = pointer.contents
                if (not item.provider or str(item.provider.contents) != str(self.key)
                        or self._signature(item) != signature):
                    return False
            finally:
                self._free(pointer)
        return True

    def replace(self, policies, expected=None):
        validate(policies)
        _check(self.api.FwpmTransactionBegin0(self.handle, 0))
        try:
            before = self.read()
            if expected is not None and before != expected:
                raise ValueError("Network protection changed; retry")
            keys = []
            self._filters(lambda item: keys.append(GUID(str(item.key))))
            for key in keys:
                _check(self.api.FwpmFilterDeleteByKey0(self.handle, C.byref(key)))
            for function, key, missing in ((self.api.FwpmSubLayerDeleteByKey0, self.sublayer, SUBLAYER_MISSING),
                                            (self.api.FwpmProviderDeleteByKey0, self.key, PROVIDER_MISSING)):
                code = function(self.handle, C.byref(key))
                if code != missing:
                    _check(code)
            if policies:
                raw = json.dumps({"schema": 1, "owner": self.owner, "policies": policies},
                                 ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                buffer = (U8 * len(raw)).from_buffer_copy(raw)
                provider = Provider()
                provider.key, provider.flags = self.key, PERSISTENT
                provider.display = Display("Claude China network protection", "User-scoped proxy enforcement")
                provider.data = Blob(len(raw), buffer)
                # The regular desktop process may query its objects, but only
                # administrators/SYSTEM can modify them. No global ACL changes.
                acl = "D:(A;;GA;;;SY)(A;;GA;;;BA)(A;;GR;;;" + self.owner + ")"
                with security_descriptor(acl) as (descriptor, _):
                    _check(self.api.FwpmProviderAdd0(self.handle, C.byref(provider), descriptor))
                    sublayer = Sublayer()
                    sublayer.key, sublayer.provider, sublayer.flags = self.sublayer, C.pointer(self.key), PERSISTENT
                    sublayer.display = Display("Claude China proxy allowlist", "Default deny, soft proxy permits")
                    sublayer.weight = 0x8000
                    _check(self.api.FwpmSubLayerAdd0(self.handle, C.byref(sublayer), descriptor))
                    self._build(policies, lambda item: _check(self.api.FwpmFilterAdd0(
                        self.handle, C.byref(item), descriptor, None)))
            _check(self.api.FwpmTransactionCommit0(self.handle))
        except BaseException:
            self.api.FwpmTransactionAbort0(self.handle)
            raise


class Store:
    def read(self):
        with Engine() as engine:
            return engine.read()

    def verify(self, policies):
        with Engine() as engine:
            return engine.verify(policies)


def _elevate(arguments):
    from ctypes import wintypes as W

    class ExecuteInfo(C.Structure):
        _fields_ = [("size", W.DWORD), ("mask", W.ULONG), ("window", W.HWND),
                    ("verb", W.LPCWSTR), ("file", W.LPCWSTR), ("parameters", W.LPCWSTR),
                    ("directory", W.LPCWSTR), ("show", C.c_int), ("instance", W.HINSTANCE),
                    ("id_list", PTR), ("class_name", W.LPCWSTR), ("class_key", W.HKEY),
                    ("hot_key", W.DWORD), ("icon", W.HANDLE), ("process", W.HANDLE)]

    command = list(arguments)
    if not getattr(sys, "frozen", False):
        command = ["-m", "claude_china.desktop.entry"] + command
    info = ExecuteInfo()
    info.size, info.mask = C.sizeof(info), 0x40
    info.verb, info.file, info.parameters = "runas", sys.executable, list2cmdline(command)
    info.directory, info.show = str(Path(__file__).resolve().parents[4]), 0
    shell = C.WinDLL("shell32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = [C.POINTER(ExecuteInfo)]
    if not shell.ShellExecuteExW(C.byref(info)):
        raise OSError("管理员授权被取消，系统网络防护未更改。")
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.WaitForSingleObject.argtypes = [PTR, U32]
    kernel.GetExitCodeProcess.argtypes = [PTR, C.POINTER(U32)]
    kernel.CloseHandle.argtypes = [PTR]
    try:
        if kernel.WaitForSingleObject(info.process, 120000) != 0:
            raise OSError("系统网络防护操作仍未完成，请检查管理员授权窗口。")
        code = U32()
        if not kernel.GetExitCodeProcess(info.process, C.byref(code)) or code.value:
            raise OSError("无法修改系统网络防护，请检查管理员授权与网络筛选服务。")
    finally:
        kernel.CloseHandle(info.process)


def write_policies(policies, expected=None):
    validate(policies)
    owner = current_sid()
    before = Store().read() if expected is None else expected
    if C.windll.shell32.IsUserAnAdmin():
        with Engine(owner) as engine:
            engine.replace(policies, before)
        return
    request = json.dumps({"owner": owner, "before": before, "policies": policies},
                         ensure_ascii=False).encode("utf-8")
    descriptor, name = tempfile.mkstemp(prefix="claudec-network-", suffix=".json")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(request)
        _elevate(["--network-guard-request", name, "--network-guard-digest", hashlib.sha256(request).hexdigest()])
    finally:
        Path(name).unlink(missing_ok=True)


def apply_request(path, digest):
    """Privileged helper: validate a bounded, digest-pinned request before writes."""
    if sys.platform != "win32" or not C.windll.shell32.IsUserAnAdmin():
        return 1
    try:
        with open(path, "rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != digest:
            return 1
        data = json.loads(raw)
        validate(data["before"])
        validate(data["policies"])
        with Engine(data["owner"]) as engine:
            engine.replace(data["policies"], data["before"])
        return 0
    except Exception:
        return 1
