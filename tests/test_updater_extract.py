"""独立更新器安装校验回归测试（1.0.5：顶层目录完整包误判修复）。"""
import os
import sys
import zipfile

UPD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'updater')
sys.path.insert(0, UPD)

import updater_main as um


def test_top_folder_full_package_installs(tmp_path):
    """带顶层文件夹的完整包（发布物形态）必须通过校验并正确解压。"""
    pkg = tmp_path / 'full.zip'
    with zipfile.ZipFile(pkg, 'w') as zf:
        zf.writestr('WindAnaly/WindAnaly.exe', b'MZ fake exe')
        zf.writestr('WindAnaly/_internal/runtime.dll', b'bin')
        zf.writestr('WindAnaly/app/core/version.pyc', b'pyc')
        zf.writestr('WindAnaly/data/settings.json', b'{}')       # 用户数据
        zf.writestr('WindAnaly/data/app_version.txt', b'1.0.5\n')
    install = tmp_path / 'install'
    install.mkdir()
    um.extract_preserve_data(str(pkg), str(install))
    assert (install / 'WindAnaly.exe').read_bytes() == b'MZ fake exe'
    assert (install / '_internal' / 'runtime.dll').exists()
    assert (install / 'app' / 'core' / 'version.pyc').exists()
    # data/app_version.txt 不在 _PRESERVE 白名单 → 随包更新
    assert (install / 'data' / 'app_version.txt').read_bytes() == b'1.0.5\n'


def test_preserved_user_data_not_overwritten(tmp_path):
    """data/ 下白名单文件（台账库/设置）解压时保留。"""
    pkg = tmp_path / 'full.zip'
    with zipfile.ZipFile(pkg, 'w') as zf:
        zf.writestr('WindAnaly/WindAnaly.exe', b'MZ')
        zf.writestr('WindAnaly/data/windkit.db', b'NEW DB')
        zf.writestr('WindAnaly/data/settings.json', b'{}')
    install = tmp_path / 'install'
    data = install / 'data'
    data.mkdir(parents=True)
    (data / 'windkit.db').write_bytes(b'USER DATA')
    (data / 'settings.json').write_bytes(b'USER SETTINGS')
    um.extract_preserve_data(str(pkg), str(install))
    assert (data / 'windkit.db').read_bytes() == b'USER DATA'
    assert (data / 'settings.json').read_bytes() == b'USER SETTINGS'


def test_root_relative_patch_installs(tmp_path):
    """根相对路径的差量补丁（发布形态二）同样通过校验。"""
    pkg = tmp_path / 'patch.zip'
    with zipfile.ZipFile(pkg, 'w') as zf:
        zf.writestr('app/app.pyc', b'pyc')
        zf.writestr('_internal/base_library.zip', b'zip')
        zf.writestr('data/app_version.txt', b'1.0.5\n')
    install = tmp_path / 'install'
    install.mkdir()
    um.extract_preserve_data(str(pkg), str(install))
    assert (install / 'app' / 'app.pyc').exists()


def test_source_archive_like_zip_rejected(tmp_path):
    """既无主程序、无运行时、也无 app/ 的 zip（如源码存档）必须拒绝。"""
    import pytest
    pkg = tmp_path / 'src.zip'
    with zipfile.ZipFile(pkg, 'w') as zf:
        zf.writestr('README.md', b'hi')
        zf.writestr('core/version.py', b'VERSION')
    with pytest.raises(ValueError):
        um.extract_preserve_data(str(pkg), str(tmp_path / 'install'))
