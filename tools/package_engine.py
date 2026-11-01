"""Collect a Windows engine without relying on the build host's DLL search path."""
import argparse
import bz2
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import struct
import subprocess


def pe_imports(path):
    data = path.read_bytes()
    if data[:2] != b'MZ':
        raise ValueError(f'Not a PE executable: {path.name}')
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    if data[pe:pe+4] != b'PE\0\0':
        raise ValueError(f'Invalid PE header: {path.name}')
    machine, sections = struct.unpack_from('<HH', data, pe+4)
    if machine != 0x8664:
        raise ValueError(f'Expected x64 PE: {path.name}')
    optional = pe+24
    if struct.unpack_from('<H', data, optional)[0] != 0x20b:
        raise ValueError('Expected PE32+')
    table = optional + struct.unpack_from('<H', data, pe+20)[0]
    image_base = struct.unpack_from('<Q', data, optional+24)[0]

    def offset(rva):
        for i in range(sections):
            size, virtual, raw_size, raw = struct.unpack_from('<IIII', data, table+i*40+8)
            if virtual <= rva < virtual+max(size, raw_size):
                value = raw+rva-virtual
                if value >= len(data):
                    break
                return value
        raise ValueError(f'PE RVA outside file: {path.name}')

    def name(rva):
        start = offset(rva)
        value = data[start:data.index(b'\0', start)].decode('ascii').lower()
        if not value.endswith('.dll') or any(c in value for c in '/\\:'):
            raise ValueError(f'Invalid DLL name: {value}')
        return value

    imports = set()
    # Both ordinary and delay-load imports participate in the closure.
    for directory, stride in [(1, 20), (13, 32)]:
        rva, size = struct.unpack_from('<II', data, optional+112+directory*8)
        if not rva:
            continue
        start = offset(rva)
        for at in range(start, start+size, stride):
            descriptor = struct.unpack_from('<'+'I'*(stride//4), data, at)
            if not any(descriptor):
                break
            rva = descriptor[3] if directory == 1 else descriptor[1]
            if directory == 13 and not descriptor[0] & 1:
                rva -= image_base
            imports.add(name(rva))
    return imports


def collect_dlls(seeds, destination, search, system):
    candidates = {}
    for directory in reversed(search):
        candidates.update({p.name.lower(): p for p in directory.glob('*.dll')})
    windows = {p.name.lower() for p in system.glob('*.dll')}
    queue = list(seeds)
    seen = set()
    while queue:
        source = queue.pop()
        name = source.name.lower()
        if name in seen:
            continue
        seen.add(name)
        shutil.copy2(source, destination/source.name)
        for dependency in pe_imports(source):
            if dependency in candidates:
                queue.append(candidates[dependency])
            elif dependency not in windows and not dependency.startswith(('api-ms-win-', 'ext-ms-win-')):
                raise ValueError(f'Missing DLL dependency: {source.name} -> {dependency}')
    return sorted(seen)


def validate_source(directory, name, pin):
    head = subprocess.run(['git', '-C', str(directory), 'rev-parse', 'HEAD'],
                          check=True, capture_output=True, text=True).stdout.strip()
    status = ['git', '-C', str(directory), 'status', '--porcelain', '--untracked-files=no']
    if name == 'reims':
        # The engine may intentionally select a newer, independently checked
        # QEMU than the gitlink recorded by the unchanged Reims source pin.
        status += ['--', '.', ':(exclude)vendor/qemu']
    changes = subprocess.run(status, check=True,
                             capture_output=True, text=True).stdout.strip()
    if head != pin['commit'] or changes:
        raise ValueError(f'Source revision changed or is dirty: {name}')


def validate_sources(source, qemu_source, lock):
    for directory, name in ((source, 'reims'), (qemu_source, 'qemu')):
        validate_source(directory, name, lock['sources'][name])
    cargo = (source/'Cargo.toml').read_text(encoding='utf-8')
    if lock['sources']['metal2vulkan']['commit'] not in cargo:
        raise ValueError('Reims does not pin the expected graphics runtime')


def pinned_payload(path, pin):
    if (not path.is_file() or path.resolve() != path.absolute() or
            path.stat().st_size != pin['bytes'] or
            hashlib.sha256(path.read_bytes()).hexdigest() != pin['sha256']):
        raise ValueError(f'Pinned USB payload changed: {path.name}')
    return path


def iphone_driver_lock():
    pin = json.loads((Path(__file__).parent.parent/
                      'backend/iphone-usb-driver-lock.json').read_text())
    if pin['schema'] != 1:
        raise ValueError('Unknown iPhone driver lock schema')
    return pin


def libusb_inputs(args, lock):
    names = ('libusb_source', 'libusb_build', 'iphone_driver_package')
    supplied = [getattr(args, name, None) for name in names]
    pin = lock['sources'].get('libusb')
    if pin is None:
        if any(supplied):
            raise ValueError('libusb inputs require a pinned libusb source')
        return None
    if not all(supplied):
        raise ValueError('Pinned libusb requires source, installed build and iPhone driver package')
    source, build, driver = supplied
    validate_source(source, 'libusb', pin)
    receipt_path = build/'reims-libusb-build.json'
    if (not receipt_path.is_file() or receipt_path.resolve() != receipt_path.absolute()
            or receipt_path.stat().st_size > 65536):
        raise ValueError('Missing or invalid libusb build receipt')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8-sig'))
    if (not isinstance(receipt, dict) or
            set(receipt) != {'schema', 'source', 'sha256'} or
            type(receipt.get('schema')) is not int or receipt['schema'] != 1 or receipt.get('source') != pin or
            not isinstance(receipt.get('sha256'), str) or
            not re.fullmatch('[a-f0-9]{64}', receipt['sha256'])):
        raise ValueError('libusb build provenance does not match the source pin')
    dll = build/'bin/libusb-1.0.dll'
    if (not dll.is_file() or dll.resolve() != dll.absolute() or
            hashlib.sha256(dll.read_bytes()).hexdigest() != receipt['sha256']):
        raise ValueError('libusb build DLL changed')
    if any(name.startswith(('vcruntime', 'msvcp', 'msys-')) for name in pe_imports(dll)):
        raise ValueError('Pinned libusb must be a native UCRT build')
    copying = source/'COPYING'
    if not copying.is_file():
        raise ValueError('Pinned libusb license is missing')
    driver_pin = iphone_driver_lock()
    api = pinned_payload(driver/driver_pin['api']['file'], driver_pin['api'])
    pe_imports(api)
    bsd_pin = next(p for p in driver_pin['licenses']
                   if p['file'] == 'LICENSE-libusbK-BSD.txt')
    bsd = pinned_payload(driver/'licenses'/bsd_pin['file'], bsd_pin)
    return dll, api, bsd, copying


def main():
    parser = argparse.ArgumentParser()
    for name in ('source', 'msys', 'downloads', 'sevenzip', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--qemu-build', type=Path,
                        help='Existing build of the pinned QEMU (default: SOURCE/build/qemu)')
    parser.add_argument('--qemu-source', type=Path,
                        help='Pinned QEMU checkout (default: SOURCE/vendor/qemu)')
    parser.add_argument('--reims-dist', type=Path,
                        help='Source-matched Release dist containing lib/, include/ and share/')
    parser.add_argument('--libusb-source', type=Path, help='Clean pinned libusb checkout')
    parser.add_argument('--libusb-build', type=Path, help='Installed UCRT libusb prefix with build receipt')
    parser.add_argument('--iphone-driver-package', type=Path, help='Verified expanded official driver/API bundle')
    args = parser.parse_args()
    lock = json.loads((Path(__file__).parent.parent/'backend/engine-lock.json').read_text())
    package_engine(args, lock)


def package_engine(args, lock):
    qemu = args.qemu_build or args.source/'build/qemu'
    qemu_source = args.qemu_source or args.source/'vendor/qemu'
    validate_sources(args.source, qemu_source, lock)
    usb = libusb_inputs(args, lock)
    library = args.reims_dist/'lib' if args.reims_dist else qemu
    rom = args.reims_dist/'share/reims-vgpu/ReimsVgpu.rom' if args.reims_dist else qemu/'ReimsVgpu.rom'
    if args.reims_dist:
        expected = args.source/'crates/reims-vgpu-c/include/reims_vgpu.h'
        if (args.reims_dist/'include/reims_vgpu.h').read_bytes() != expected.read_bytes():
            raise ValueError('Release dist header does not match pinned Reims source')
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    for folder in ('bin', 'share/qemu', 'share/reims', 'downloads', 'licenses'):
        (out/folder).mkdir(parents=True, exist_ok=True)
    runtime = args.msys/'ucrt64/bin'
    seeds = [qemu/n for n in ('qemu-system-x86_64.exe', 'qemu-img.exe', 'qemu-io.exe')]
    seeds += [library/'reims_vgpu_c.dll']
    # Vulkan is loaded dynamically, so the PE import table cannot discover it.
    seeds += [runtime/'vulkan-1.dll', args.sevenzip/'7z.exe', args.sevenzip/'7z.dll']
    search = [library, qemu, args.sevenzip, runtime]
    if usb:
        dll, api, bsd, copying = usb
        seeds += [dll, api]  # libusbK is dynamically loaded, absent from PE imports.
        search = [dll.parent, api.parent] + search
    collect_dlls(seeds, out/'bin', search, Path(os.environ['SystemRoot'])/'System32')
    bios = qemu_source/'pc-bios'
    for name in ('bios.bin', 'bios-256k.bin', 'vgabios-stdvga.bin', 'kvmvapic.bin', 'efi-e1000.rom', 'efi-e1000e.rom', 'efi-virtio.rom', 'efi-vmxnet3.rom'):
        shutil.copy2(bios/name, out/'share/qemu'/name)
    for name, digest in lock['firmware']['files'].items():
        source = args.downloads/name
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError(f'Firmware download changed: {name}')
        target = out/'share/qemu'/name.removesuffix('.bz2')
        target.write_bytes(bz2.decompress(source.read_bytes()) if name.endswith('.bz2') else source.read_bytes())
    shutil.copy2(rom, out/'share/reims/ReimsVgpu.rom')
    shutil.copy2(args.downloads/lock['opencore']['file'], out/'downloads'/lock['opencore']['file'])
    for name in ('GPL-2.0-or-later.txt', 'GPL-3.0-or-later.txt', 'LGPL-3.0-or-later.txt'):
        # Reims uses SPDX-named LICENSES; fail rather than omit its licenses.
        shutil.copy2(args.source/'LICENSES'/name, out/'licenses'/name)
    shutil.copy2(qemu_source/'COPYING', out/'licenses/QEMU-COPYING')
    shutil.copytree(args.msys/'ucrt64/share/licenses', out/'licenses/native-dependencies')
    if usb:
        shutil.copy2(bsd, out/'licenses'/bsd.name)
        shutil.copy2(copying, out/'licenses/libusb-COPYING')
    for name in ('License.txt', 'readme.txt'):
        shutil.copy2(args.sevenzip/name, out/'licenses'/('7zip-'+name))
    shutil.copy2(args.source/'.work/diagnostics/msys2-packages-current.txt', out/'licenses/msys2-packages.txt')
    shutil.copy2(Path(__file__).parent.parent/'docs/engine-setup.md', out/'README.md')
    if usb:
        shutil.copy2(Path(__file__).parent.parent/'docs/iphone-usb.md', out/'iphone-usb.md')
    paths = dict(qemu='bin/qemu-system-x86_64.exe', qemu_img='bin/qemu-img.exe', qemu_io='bin/qemu-io.exe',
                 seven_zip='bin/7z.exe', firmware='share/qemu', firmware_code='share/qemu/edk2-x86_64-code.fd',
                 firmware_vars='share/qemu/edk2-i386-vars.fd', rom='share/reims/ReimsVgpu.rom',
                 opencore_archive='downloads/'+lock['opencore']['file'])
    files = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(out.rglob('*')) if p.is_file()}
    manifest = dict(schema=1, id=lock['id'], sources=lock['sources'], paths=paths, files=files)
    (out/'reims-engine.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
