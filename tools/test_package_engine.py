import importlib.util
import argparse
import bz2
import hashlib
import json
from itertools import product
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('package_engine', Path(__file__).with_name('package_engine.py'))
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def pe(import_name=None, delayed=False):
    data = bytearray(2048)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 128)
    data[128:132] = b'PE\0\0'
    struct.pack_into('<HH', data, 132, 0x8664, 1)
    struct.pack_into('<H', data, 148, 240)
    struct.pack_into('<H', data, 152, 0x20b)
    struct.pack_into('<IIII', data, 400, 1024, 4096, 1024, 512)
    if import_name:
        directory = 13 if delayed else 1
        struct.pack_into('<II', data, 264+directory*8, 4096, 64 if delayed else 40)
        if delayed:
            struct.pack_into('<II', data, 512, 1, 4352)
        else:
            struct.pack_into('<I', data, 524, 4352)
        value = import_name.encode()+b'\0'
        data[768:768+len(value)] = value
    return data


class PackagingTests(unittest.TestCase):
    def test_package_default_and_split_release_layouts(self):
        for split, usb in product((False, True), repeat=2):
            with self.subTest(split=split, libusb=usb), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                source, msys = root/'source', root/'msys'
                qemu_source = root/'qemu-source' if split else source/'vendor/qemu'
                build = root/'qemu-build' if split else source/'build/qemu'
                dist = root/'release' if split else None
                library = dist/'lib' if split else build
                rom = dist/'share/reims-vgpu/ReimsVgpu.rom' if split else build/'ReimsVgpu.rom'
                seven, downloads, windows = root/'seven', root/'downloads', root/'windows'

                def write(path, data):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)

                for name in ('qemu-system-x86_64.exe', 'qemu-img.exe', 'qemu-io.exe'):
                    write(build/name, pe('libusb-1.0.dll' if usb else 'reims_vgpu_c.dll'))
                if split:
                    # Never pick up an old/dev DLL next to a cached QEMU EXE.
                    write(build/'reims_vgpu_c.dll', pe('stale-and-missing.dll'))
                    write(dist/'include/reims_vgpu.h', b'authored ABI fixture')
                    write(source/'crates/reims-vgpu-c/include/reims_vgpu.h', b'authored ABI fixture')
                release_library = pe('release-dependency.dll')
                write(library/'reims_vgpu_c.dll', release_library)
                write(library/'release-dependency.dll', pe('runtime-dependency.dll', delayed=True))
                write(msys/'ucrt64/bin/runtime-dependency.dll', pe())
                write(msys/'ucrt64/bin/vulkan-1.dll', pe())
                for name in ('7z.exe', '7z.dll'):
                    write(seven/name, pe())
                for name in ('License.txt', 'readme.txt'):
                    write(seven/name, b'authored license fixture')
                for name in ('bios.bin', 'bios-256k.bin', 'vgabios-stdvga.bin', 'kvmvapic.bin',
                             'efi-e1000.rom', 'efi-e1000e.rom', 'efi-virtio.rom', 'efi-vmxnet3.rom'):
                    write(qemu_source/'pc-bios'/name, b'authored firmware fixture')
                write(qemu_source/'COPYING', b'authored QEMU license fixture')
                write(rom, b'authored Reims ROM fixture')
                for name in ('GPL-2.0-or-later.txt', 'GPL-3.0-or-later.txt', 'LGPL-3.0-or-later.txt'):
                    write(source/'LICENSES'/name, b'authored license fixture')
                write(msys/'ucrt64/share/licenses/fixture.txt', b'authored dependency license')
                write(source/'.work/diagnostics/msys2-packages-current.txt', b'authored package list')
                firmware = bz2.compress(b'authored OVMF fixture')
                write(downloads/'code.fd.bz2', firmware)
                write(downloads/'OpenCore.zip', b'authored archive fixture')
                windows.joinpath('System32').mkdir(parents=True)
                lock = dict(id='authored-engine', sources={'reims': {'commit': 'a'*40}},
                            firmware={'files': {'code.fd.bz2': hashlib.sha256(firmware).hexdigest()}},
                            opencore={'file': 'OpenCore.zip'})
                args = argparse.Namespace(source=source, msys=msys, downloads=downloads,
                                          sevenzip=seven, output=root/'out',
                                          qemu_build=build if split else None,
                                          qemu_source=qemu_source if split else None, reims_dist=dist)
                driver_pin = None
                if usb:
                    args.libusb_source, args.libusb_build, args.iphone_driver_package = root/'libusb', root/'usb-install', root/'driver'
                    lock['sources']['libusb'] = {'repository': 'https://github.com/tqmane/reims-libusb', 'commit': 'f'*40}
                    driver_pin = self.usb_fixture(args, lock)
                    write(msys/'ucrt64/bin/libusb-1.0.dll', pe('wrong-stock.dll'))
                    write(build/'libusb-1.0.dll', pe('wrong-cached.dll'))
                    write(msys/'ucrt64/bin/usb-dependency.dll', pe())
                    write(msys/'ucrt64/bin/api-dependency.dll', pe())
                with patch.object(package, 'validate_sources') as validate, patch.object(package, 'validate_source'), patch.object(package, 'iphone_driver_lock', return_value=driver_pin), patch.dict(package.os.environ, SystemRoot=str(windows)):
                    package.package_engine(args, lock)
                    validate.assert_called_once_with(source, qemu_source, lock)
                self.assertEqual((args.output/'bin/reims_vgpu_c.dll').read_bytes(), release_library)
                self.assertTrue((args.output/'bin/runtime-dependency.dll').is_file())
                self.assertTrue((args.output/'bin/vulkan-1.dll').is_file())
                if usb:
                    self.assertEqual((args.output/'bin/libusb-1.0.dll').read_bytes(), (args.libusb_build/'bin/libusb-1.0.dll').read_bytes())
                    self.assertEqual((args.output/'bin/libusbK.dll').read_bytes(), (args.iphone_driver_package/'libusbK.dll').read_bytes())
                    self.assertTrue((args.output/'bin/api-dependency.dll').is_file())
                    self.assertTrue((args.output/'bin/usb-dependency.dll').is_file())
                    self.assertEqual((args.output/'licenses/LICENSE-libusbK-BSD.txt').read_bytes(), b'authored BSD license')
                    self.assertTrue((args.output/'licenses/libusb-COPYING').is_file())
                self.assertEqual((args.output/'share/reims/ReimsVgpu.rom').read_bytes(), rom.read_bytes())
                manifest = json.loads((args.output/'reims-engine.json').read_text())
                self.assertEqual(manifest['sources'], lock['sources'])
                self.assertNotIn(str(root), json.dumps(manifest))
                for name, digest in manifest['files'].items():
                    self.assertEqual(hashlib.sha256((args.output/name).read_bytes()).hexdigest(), digest)
                if split:
                    (dist/'include/reims_vgpu.h').write_bytes(b'wrong ABI')
                    args.output = root/'rejected'
                    with patch.object(package, 'validate_sources'), patch.object(package, 'validate_source'), patch.object(package, 'iphone_driver_lock', return_value=driver_pin), self.assertRaisesRegex(ValueError, 'header does not match'):
                        package.package_engine(args, lock)
                    self.assertFalse(args.output.exists())

    @staticmethod
    def usb_fixture(args, lock):
        files = {
            args.libusb_source/'COPYING': b'authored LGPL license',
            args.libusb_build/'bin/libusb-1.0.dll': pe('usb-dependency.dll'),
            args.iphone_driver_package/'libusbK.dll': pe('api-dependency.dll'),
            args.iphone_driver_package/'licenses/LICENSE-libusbK-BSD.txt': b'authored BSD license',
        }
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        def entry(path):
            return {'file': path.name, 'bytes': path.stat().st_size,
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        receipt = {'schema': 1, 'source': lock['sources']['libusb'],
                   'sha256': entry(args.libusb_build/'bin/libusb-1.0.dll')['sha256']}
        (args.libusb_build/'reims-libusb-build.json').write_text(json.dumps(receipt))
        return {'schema': 1, 'api': entry(args.iphone_driver_package/'libusbK.dll'),
                'licenses': [entry(args.iphone_driver_package/'licenses/LICENSE-libusbK-BSD.txt')]}

    def test_pinned_libusb_requires_inputs_and_clean_source_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            args = argparse.Namespace(source=root, qemu_source=None, qemu_build=None,
                                      output=root/'out', libusb_source=root/'usb',
                                      libusb_build=root/'build', iphone_driver_package=root/'driver')
            lock = {'sources': {'libusb': {'commit': 'f'*40}}}
            for replies in (('wrong', ''), ('f'*40, ' M libusb/core.c')):
                with patch.object(package, 'validate_sources'), patch.object(package.subprocess, 'run', side_effect=[SimpleNamespace(stdout=x) for x in replies]), self.assertRaisesRegex(ValueError, 'dirty: libusb'):
                    package.package_engine(args, lock)
                self.assertFalse(args.output.exists())
            for field in ('libusb_source', 'libusb_build', 'iphone_driver_package'):
                original = getattr(args, field)
                setattr(args, field, None)
                with patch.object(package, 'validate_sources'), self.assertRaisesRegex(ValueError, 'requires source'):
                    package.package_engine(args, lock)
                self.assertFalse(args.output.exists())
                setattr(args, field, original)
            with self.assertRaisesRegex(ValueError, 'require a pinned'):
                package.libusb_inputs(args, {'sources': {}})

    def test_libusb_build_and_official_api_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            args = argparse.Namespace(libusb_source=root/'source', libusb_build=root/'build', iphone_driver_package=root/'driver')
            lock = {'sources': {'libusb': {'repository': 'https://github.com/tqmane/reims-libusb', 'commit': 'f'*40}}}
            pin = self.usb_fixture(args, lock)
            receipt_path = args.libusb_build/'reims-libusb-build.json'
            original = receipt_path.read_bytes()
            with patch.object(package, 'validate_source'), patch.object(package, 'iphone_driver_lock', return_value=pin):
                package.libusb_inputs(args, lock)
                for invalid in ([], {'schema': True}, {'schema': 1, 'source': {'commit': '0'*40}, 'sha256': 'a'*64}):
                    receipt_path.write_text(json.dumps(invalid))
                    with self.assertRaisesRegex(ValueError, 'provenance'):
                        package.libusb_inputs(args, lock)
                receipt_path.write_bytes(original)
                dll = args.libusb_build/'bin/libusb-1.0.dll'
                dll.write_bytes(pe('vcruntime140.dll'))
                with self.assertRaisesRegex(ValueError, 'DLL changed'):
                    package.libusb_inputs(args, lock)
                receipt = json.loads(original)
                receipt['sha256'] = hashlib.sha256(dll.read_bytes()).hexdigest()
                receipt_path.write_text(json.dumps(receipt))
                with self.assertRaisesRegex(ValueError, 'native UCRT'):
                    package.libusb_inputs(args, lock)
                self.usb_fixture(args, lock)
                api = args.iphone_driver_package/'libusbK.dll'
                api.write_bytes(pe('tampered.dll'))  # Same PE size, different official bytes.
                with self.assertRaisesRegex(ValueError, 'Pinned USB payload changed: libusbK'):
                    package.libusb_inputs(args, lock)
                self.usb_fixture(args, lock)
                (args.iphone_driver_package/'licenses/LICENSE-libusbK-BSD.txt').write_bytes(b'wrong license')
                with self.assertRaisesRegex(ValueError, 'Pinned USB payload changed: LICENSE'):
                    package.libusb_inputs(args, lock)

    def test_source_revision_cleanliness_and_runtime_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp).resolve()
            runtime = 'e'*40
            (source/'Cargo.toml').write_text('rev = "'+runtime+'"', encoding='utf-8')
            lock = {'sources': {'reims': {'commit': 'a'*40}, 'qemu': {'commit': 'b'*40},
                                'metal2vulkan': {'commit': runtime}}}
            clean = [SimpleNamespace(stdout=x) for x in ('a'*40, '', 'b'*40, '')]
            with patch.object(package.subprocess, 'run', side_effect=clean) as run:
                package.validate_sources(source, source/'qemu', lock)
                self.assertEqual(run.call_args_list[0].args[0], ['git', '-C', str(source), 'rev-parse', 'HEAD'])
                self.assertEqual(run.call_args_list[1].args[0][-3:], ['--', '.', ':(exclude)vendor/qemu'])
                self.assertEqual(run.call_args_list[2].args[0], ['git', '-C', str(source/'qemu'), 'rev-parse', 'HEAD'])
                self.assertNotIn(':(exclude)vendor/qemu', run.call_args_list[3].args[0])
            for replies in (('wrong', ''), ('a'*40, ' M Cargo.toml'), ('a'*40, '', 'wrong', '')):
                with patch.object(package.subprocess, 'run', side_effect=[SimpleNamespace(stdout=x) for x in replies]), self.assertRaisesRegex(ValueError, 'Source revision changed or is dirty'):
                    package.validate_sources(source, source/'qemu', lock)
            (source/'Cargo.toml').write_text('rev = "wrong"', encoding='utf-8')
            with patch.object(package.subprocess, 'run', side_effect=clean), self.assertRaisesRegex(ValueError, 'expected graphics runtime'):
                package.validate_sources(source, source/'qemu', lock)

    def test_recursive_dll_closure_and_missing_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for folder in ('input', 'output', 'system'):
                (root/folder).mkdir()
            source = root/'input/qemu.exe'
            source.write_bytes(pe('first.dll'))
            (root/'input/first.dll').write_bytes(pe('SECOND.dll', delayed=True))
            (root/'input/second.dll').write_bytes(pe('kernel32.dll'))
            (root/'system/kernel32.dll').write_bytes(b'Windows fixture')
            copied = package.collect_dlls([source], root/'output', [root/'input'], root/'system')
            self.assertEqual(copied, ['first.dll', 'qemu.exe', 'second.dll'])
            (root/'input/second.dll').unlink()
            with self.assertRaisesRegex(ValueError, 'Missing DLL dependency'):
                package.collect_dlls([source], root/'output', [root/'input'], root/'system')

    def test_reject_non_pe_and_wrong_architecture(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve()/'bad.exe'
            path.write_bytes(b'not PE')
            with self.assertRaises(ValueError):
                package.pe_imports(path)
            data = pe()
            struct.pack_into('<H', data, 132, 0x14c)
            path.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'Expected x64'):
                package.pe_imports(path)


if __name__ == '__main__':
    unittest.main()
