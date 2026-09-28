"""Assemble the Chinese user-facing layout; never include local credentials/logs."""
import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
RUNTIME = {
    'README.md': 'README.md',
    '00_使用说明（先解压，再右键管理员运行安装）.txt': 'packaging/使用说明.txt',
    '01_一键安装（右键管理员运行）.bat': 'packaging/安装.bat',
    '02_卸载（右键管理员运行）.bat': 'packaging/卸载.bat',
    '程序文件/开源许可.txt': 'LICENSE',
}
for name in ('login.exe', 'install.bat', 'install.ps1', 'uninstall.bat', 'uninstall.ps1'):
    RUNTIME['程序文件/' + name] = 'dist/login.exe' if name == 'login.exe' else name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'dist')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = {name: name for name in ('ahu_login.py', 'login.pyw', 'build.ps1', 'package.py',
              'requirements-build.txt', 'version_info.txt', 'README.md', 'LICENSE',
              'install.bat', 'install.ps1', 'uninstall.bat', 'uninstall.ps1', 'diagnose.bat', '.env.example')}
    for folder in ('tests', 'packaging'):
        for path in (ROOT/folder).iterdir():
            if path.is_file() and path.suffix in ('.py', '.ps1', '.bat', '.txt'):
                if path.name == '诊断.bat':
                    continue
                relative = path.relative_to(ROOT).as_posix()
                source[relative] = relative
    hashes = []
    for name, mapping in (('AHU_AutoLogin_v1.2.zip', RUNTIME), ('AHU_AutoLogin_v1.2_source.zip', source)):
        path = args.output/name
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for target, original in mapping.items():
                data = (ROOT/original).read_bytes()
                if target.endswith('.bat'):
                    # CMD reads the UTF-8 paths after the initial ASCII chcp command.
                    data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
                elif target.endswith('.txt') and original.startswith('packaging/'):
                    data = b'\xef\xbb\xbf' + data.removeprefix(b'\xef\xbb\xbf').replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
                archive.writestr(target, data)
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            assert set(archive.namelist()) == set(mapping)
            assert not any(Path(n).name in ('.env', 'autologin.log') for n in archive.namelist())
        hashes.append(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}')
        print(f'Created {name}: {len(mapping)} files')
    (args.output/'SHA256SUMS_v1.2.txt').write_text('\n'.join(hashes)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
