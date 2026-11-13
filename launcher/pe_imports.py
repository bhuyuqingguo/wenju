"""Read PE import tables and reject binaries that cannot load on Windows 7 SP1 x64.

api-ms-win-crt-* is accepted when a same-named DLL is present in the tree
(Universal CRT forwarders shipped beside the executables). Other API sets that
Windows 7 does not provide are rejected, along with kernel32 exports added in
Windows 8 or later.
"""
from pathlib import Path
import struct, sys

# These API sets have no Windows 7 implementation. Other api-ms-win-core-*
# names are the Universal CRT's downlevel forwarders; they are accepted when
# the package ships the DLL next to pythonw.exe.
ALWAYS_BANNED_DLL_PARTS = (
    'api-ms-win-core-path',
    'api-ms-win-core-winrt',
    'api-ms-win-shcore',
    'bcryptprimitives.dll',
)
# kernel32 exports that are absent on Windows 7. AddDllDirectory is intentionally
# not listed: it is present after KB2533623, which current Python 3.8 builds import.
BANNED_KERNEL32 = {
    'CopyFile2', 'CreateFile2', 'GetSystemTimePreciseAsFileTime', 'SetThreadDescription',
    'GetCurrentThreadStackLimits', 'GetProcessMitigationPolicy', 'SetProcessMitigationPolicy',
    'PrefetchVirtualMemory', 'GetTempPath2W', 'GetTempPath2A', 'QueryInterruptTime',
    'QueryUnbiasedInterruptTime', 'DiscardVirtualMemory', 'OfferVirtualMemory',
    'ReclaimVirtualMemory', 'SetProcessDpiAwarenessContext', 'GetDpiForSystem',
}


def _rva_to_off(sections, rva):
    for va, span, raw in sections:
        if va <= rva < va + span:
            return raw + (rva - va)
    return None


def pe_imports(path):
    data = path.read_bytes()
    if data[:2] != b'MZ':
        return None
    e = struct.unpack_from('<I', data, 0x3C)[0]
    if data[e:e + 4] != b'PE\0\0':
        return None
    nsec, optsz = struct.unpack_from('<H', data, e + 6)[0], struct.unpack_from('<H', data, e + 20)[0]
    magic = struct.unpack_from('<H', data, e + 24)[0]
    if magic == 0x10B:
        dd, nentries = e + 24 + 96, struct.unpack_from('<I', data, e + 24 + 92)[0]
        is64 = False
    elif magic == 0x20B:
        dd, nentries = e + 24 + 112, struct.unpack_from('<I', data, e + 24 + 108)[0]
        is64 = True
    else:
        return None
    sections = []
    sec = e + 24 + optsz
    for i in range(nsec):
        vs, va, rs, rp = struct.unpack_from('<IIII', data, sec + i * 40 + 8)
        sections.append((va, max(vs, rs), rp))

    def names(rva, delay):
        if not rva:
            return []
        off = _rva_to_off(sections, rva)
        found = []
        while off is not None:
            if delay:
                attrs, name_rva, mod, iat, int_, bound, unload, ts = struct.unpack_from('<IIIIIIII', data, off)
                if name_rva == 0 and iat == 0:
                    break
                thunk_rva = int_ or iat
                step_desc = 32
            else:
                ilt, td, fwd, name_rva, iat = struct.unpack_from('<IIIII', data, off)
                if name_rva == 0 and iat == 0:
                    break
                thunk_rva = ilt or iat
                step_desc = 20
            no = _rva_to_off(sections, name_rva)
            dll = data[no:data.index(b'\0', no)].decode('ascii', 'replace')
            thunk = _rva_to_off(sections, thunk_rva)
            step = 8 if is64 else 4
            funcs = []
            while True:
                val = struct.unpack_from('<Q' if is64 else '<I', data, thunk)[0]
                if val == 0:
                    break
                ordinal_bit = (val >> 63) if is64 else (val >> 31)
                if ordinal_bit:
                    funcs.append('#' + str(val & 0xFFFF))
                else:
                    fo = _rva_to_off(sections, val & (0x7FFFFFFFFFFFFFFF if is64 else 0x7FFFFFFF))
                    funcs.append(data[fo + 2:data.index(b'\0', fo + 2)].decode('ascii', 'replace') if fo is not None else '?')
                thunk += step
            found.append((dll, funcs))
            off += step_desc
        return found

    hard = names(struct.unpack_from('<I', data, dd + 8)[0], False)
    delay = names(struct.unpack_from('<I', data, dd + 13 * 8)[0], True) if nentries > 13 else []
    return hard, delay


def scan(root):
    root = Path(root)
    present = {p.name.lower() for p in root.rglob('*') if p.is_file()}
    problems = []
    checked = 0
    for path in root.rglob('*'):
        if path.suffix.lower() not in ('.exe', '.dll', '.pyd'):
            continue
        parsed = pe_imports(path)
        if parsed is None:
            continue
        checked += 1
        rel = path.relative_to(root).as_posix()
        for kind, block in (('import', parsed[0]), ('delay', parsed[1])):
            for dll, funcs in block:
                low = dll.lower()
                if any(part in low for part in ALWAYS_BANNED_DLL_PARTS):
                    problems.append((rel, kind, dll, 'DLL'))
                    continue
                if low.startswith('api-ms-win-'):
                    if low not in present:
                        problems.append((rel, kind, dll, 'missing bundled forwarder'))
                    continue
                if low in ('kernel32.dll', 'kernelbase.dll'):
                    for name in funcs:
                        if name in BANNED_KERNEL32:
                            problems.append((rel, kind, dll, name))
    return checked, problems


def main(argv):
    root = Path(argv[1] if len(argv) > 1 else '.')
    checked, problems = scan(root)
    print(f'PE files: {checked}')
    if not problems:
        print('No Windows 7 import violations.')
        return 0
    for item in problems:
        print('\t'.join(item))
    print(f'Violations: {len(problems)}')
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
