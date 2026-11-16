#!/usr/bin/env python3
"""Create separate Intel and Apple Silicon DMGs from a universal Studio app."""
import argparse
import plistlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ARCHITECTURES = {'x86_64': 'Intel', 'arm64': 'AppleSilicon'}
MACH_MAGIC = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf',
              b'\xfe\xed\xfa\xce', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
              b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}


def run(*args):
    return subprocess.check_output([str(x) for x in args], text=True)


def native_files(app):
    for path in app.rglob('*'):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as stream:
                if stream.read(4) in MACH_MAGIC:
                    yield path


def check_minimum(path):
    commands = run('otool', '-l', path)
    versions = []
    for block in re.split(r'Load command \d+', commands):
        if 'cmd LC_BUILD_VERSION\n' in block:
            versions += re.findall(r'^\s*minos\s+(\d+\.\d+(?:\.\d+)?)\s*$', block, re.M)
        elif 'cmd LC_VERSION_MIN_MACOSX\n' in block:
            versions += re.findall(r'^\s*version\s+(\d+\.\d+(?:\.\d+)?)\s*$', block, re.M)
    if not versions:
        raise RuntimeError(f'Missing minimum macOS version in {path}')
    for version in versions:
        parts = tuple(int(x) for x in version.split('.'))
        if (parts + (0, 0))[:3] > (12, 0, 0):
            raise RuntimeError(f'{path.name} requires macOS {version}, above the advertised 12.0 minimum')


def package(source, output):
    output.mkdir(parents=True, exist_ok=True)
    info = plistlib.loads((source / 'Contents/Info.plist').read_bytes())
    if info.get('LSMinimumSystemVersion') != '12.0':
        raise RuntimeError('Expected a macOS 12.0 app build.')
    for arch, label in ARCHITECTURES.items():
        dmg = output / f'SasquatchSaveStudio-macOS-{label}.dmg'
        if dmg.exists():
            raise RuntimeError(f'Refusing to overwrite {dmg}')
        with tempfile.TemporaryDirectory(prefix='ssm-dmg-', dir=output) as directory:
            stage = Path(directory)
            app = stage / source.name
            shutil.copytree(source, app, symlinks=True)
            paths = list(native_files(app))
            for path in paths:
                arches = run('lipo', '-archs', path).split()
                if arch not in arches:
                    raise RuntimeError(f'{path.name} does not contain {arch}')
                if len(arches) > 1:
                    thin = path.with_name(path.name + '.thin')
                    run('lipo', path, '-thin', arch, '-output', thin)
                    thin.chmod(path.stat().st_mode)
                    thin.replace(path)
                check_minimum(path)
                run('codesign', '--force', '--sign', '-', path)
            run('codesign', '--force', '--sign', '-', app)
            run('codesign', '--verify', '--deep', '--strict', app)
            (stage / 'Applications').symlink_to('/Applications', target_is_directory=True)
            (stage / 'Install.txt').write_text(
                f'Sasquatch Save Studio — {label}\nRequires macOS 12 Monterey or later.\n\n'
                'Drag Sasquatch Save Studio.app onto the Applications shortcut.\n'
                'Then open the app from Applications and eject this disk image.\n\n'
                'The game is not included. Game launch uses your installed game and existing saves.\n'
                'This community build is locally signed, not Apple-notarized.\n'
            )
            print(f'{label}: verified {len(paths)} native binaries, macOS 12.0 or earlier', flush=True)
            print(run('hdiutil', 'create', '-volname', 'Sasquatch Save Studio',
                      '-srcfolder', stage, '-format', 'UDZO', dmg), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    package(args.app.resolve(), args.output.resolve())


if __name__ == '__main__':
    main()
