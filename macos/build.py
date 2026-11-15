#!/usr/bin/env python3
"""Build a universal macOS app using a universal framework Python.org installation."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

PROJECT = Path(__file__).resolve().parent.parent
APP_NAME = 'Sasquatch Save Studio'
STANDARD_LIBRARY_EXCLUSIONS = {
    '__pycache__', 'site-packages', 'test', 'idlelib', 'tkinter',
    'ensurepip', 'turtledemo',
}


def run(*command):
    subprocess.run(command, check=True)


def bundled_extension(path):
    links = subprocess.check_output(['otool', '-L', path], text=True)
    dependencies = (line.strip() for line in links.splitlines() if line.startswith('\t'))
    # The loopback editor only needs modules with system library dependencies.
    return all(link.startswith(('/usr/lib/', '/System/Library/')) for link in dependencies)


def python_runtime(python, contents):
    prefix, version = subprocess.check_output(
        [python, '-I', '-c', 'import sys; print(sys.base_prefix); print("%s.%s" % sys.version_info[:2])'],
        text=True,
    ).splitlines()
    prefix = Path(prefix)
    # The bin/python launcher re-executes this executable inside the installed framework.
    original_binary = prefix / 'Resources/Python.app/Contents/MacOS/Python'
    original_library = prefix / 'Python'
    if 'Python.framework' not in prefix.parts or not original_binary.is_file() or not original_library.is_file():
        raise SystemExit('Use a universal framework installer from python.org.')
    for binary in (original_binary, original_library):
        arches = subprocess.check_output(['lipo', '-archs', binary], text=True).split()
        if set(arches) != {'arm64', 'x86_64'}:
            raise SystemExit('The Python interpreter and framework must both be universal.')

    binary = contents / 'MacOS' / 'studio-python'
    library = contents / 'Frameworks' / 'Python.dylib'
    shutil.copy2(original_binary, binary)
    shutil.copy2(original_library, library)
    run('install_name_tool', '-id', '@loader_path/Python.dylib', library)
    run('install_name_tool', '-change', str(original_library), '@loader_path/../Frameworks/Python.dylib', binary)

    standard_library = prefix / 'lib' / f'python{version}'
    runtime = contents / 'Resources' / 'Python'
    target = runtime / 'lib' / standard_library.name
    excluded = STANDARD_LIBRARY_EXCLUSIONS | {'lib-dynload'}
    shutil.copytree(standard_library, target, ignore=shutil.ignore_patterns(*excluded, 'config-*', '*.pyc'))
    extensions = target / 'lib-dynload'
    extensions.mkdir()
    for extension in (standard_library / 'lib-dynload').glob('*.so'):
        if bundled_extension(extension):
            shutil.copy2(extension, extensions / extension.name)

    for item in (binary, library, *extensions.glob('*.so')):
        run('codesign', '--force', '--sign', '-', item)
    subprocess.run(
        [binary, '-B', '-s', '-c', 'import fcntl, hashlib, http.server, json, secrets, socket'],
        env={**os.environ, 'PYTHONHOME': str(runtime)},
        check=True,
    )


def icon(resources, temporary):
    image = PROJECT / 'ipad/App/Assets.xcassets/AppIcon.appiconset/AppIcon.png'
    iconset = temporary / 'AppIcon.iconset'
    iconset.mkdir()
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            width = str(size * scale)
            filename = f'icon_{size}x{size}' + ('@2x' if scale == 2 else '') + '.png'
            run('sips', '-z', width, width, image, '--out', iconset / filename)
    run('iconutil', '-c', 'icns', iconset, '-o', resources / 'AppIcon.icns')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', type=Path, required=True, help='Location of the universal python.org interpreter')
    parser.add_argument('--output', type=Path, required=True, help='Directory to receive the .app bundle')
    args = parser.parse_args()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f'{APP_NAME}.app'
    if destination.exists():
        raise SystemExit(f'Refusing to overwrite {destination}')

    with tempfile.TemporaryDirectory(prefix='ssm-mac-build-', dir=output) as directory:
        temporary = Path(directory)
        app = temporary / destination.name
        contents = app / 'Contents'
        for folder in ('MacOS', 'Frameworks', 'Resources/tools', 'Resources/web'):
            (contents / folder).mkdir(parents=True)
        resources = contents / 'Resources'
        shutil.copy2(PROJECT / 'macos/Info.plist', contents / 'Info.plist')
        for relative in ('LICENSE', 'tools/ss_web.py', 'tools/ss_console.py', 'tools/slot3_mod.py',
                         'web/index.html', 'web/save-fields.js'):
            shutil.copy2(PROJECT / relative, resources / relative)

        sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
        products = []
        for arch in ('arm64', 'x86_64'):
            executable = temporary / arch
            run('xcrun', '--sdk', 'macosx', 'swiftc', '-O', '-parse-as-library', '-sdk', sdk,
                '-module-cache-path', temporary / 'ModuleCache',
                '-target', f'{arch}-apple-macos13.0', PROJECT / 'macos/StudioApp.swift', '-o', executable)
            products.append(executable)
        run('lipo', '-create', *products, '-output', contents / 'MacOS/SasquatchSaveStudio')
        python_runtime(args.python, contents)
        icon(resources, temporary)

        run('codesign', '--force', '--sign', '-', app)
        run('codesign', '--verify', '--deep', '--strict', app)
        app.rename(destination)
    print(destination)


if __name__ == '__main__':
    main()
