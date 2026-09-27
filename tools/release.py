"""发布自动化（S4-4）：一条龙出完整包 + 增量包 + 版本索引 + 本地归档。

用法:
    python tools/release.py 1.0.3 --notes "本版更新说明"
    python tools/release.py 1.0.3 --skip-build     # dist 已是新版时复用

流程:
  1. 校验 core/version.py 与参数一致；run_checks 已由调用方负责
  2. PyInstaller 打包（--skip-build 跳过）
  3. 冻结 exe 冒烟（offscreen 启动 6s 存活）
  4. 完整包   release/WindAnaly-<版本>.zip
  5. 基线重演 release/ 里找上一版全量包，按顺序叠加其后的增量包
  6. 文件级 diff（sha256）→ release/<旧>-<新>-patch.zip
  7. 版本索引 release/<新>/versions.json（changelog 来自 --notes）
  8. 打印上传清单（GitHub Release 只传增量包 + versions.json）

发版后手工步骤（见 RELEASE.md）：git tag → push → GitHub Release 上传
增量包与 versions.json → git archive 导出源码归档。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
REL = os.path.join(ROOT, 'release')
DIST = os.path.join(ROOT, 'dist', 'WindAnaly')


def sha256(p: str) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def vtuple(v: str):
    return tuple(int(x) for x in v.split('.'))


def run(cmd, **kw):
    print('>', ' '.join(cmd))
    subprocess.run(cmd, check=True, **kw)


def build(new: str) -> None:
    cur = re.search(r"VERSION = '([^']+)'",
                    open('core/version.py', encoding='utf-8').read()).group(1)
    assert cur == new, f'core/version.py 是 {cur}，先改成 {new} 再发版'
    run([sys.executable, '-X', 'utf8', 'build.py'])


def smoke_exe() -> None:
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    proc = subprocess.Popen([os.path.join(DIST, 'WindAnaly.exe')], cwd=DIST,
                            env=env,
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    time.sleep(6)
    alive = proc.poll() is None
    if alive:
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/F'],
                       capture_output=True)
    assert alive, '冻结 exe 启动后闪退'
    # 清理冒烟运行产生的运行时残留，但保留 data/app_version.txt
    # （程序元数据，完整包必须携带——独立更新器靠它识别已装版本）
    data = os.path.join(DIST, 'data')
    if os.path.isdir(data):
        for entry in os.listdir(data):
            if entry == 'app_version.txt':
                continue
            p = os.path.join(data, entry)
            shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) \
                else os.remove(p)
    print('exe smoke: alive OK')


def find_baseline(new: str):
    """在 release/<版本>/ 各目录里找上一版全量包与其后的增量包。

    返回 (基线版本号, 全量包路径, [补丁路径...])。"""
    fulls = []
    patches = []
    for dirpath, _dirs, files in os.walk(REL):
        for f in files:
            m = re.fullmatch(r'WindAnaly-(\d+(?:\.\d+)+)\.zip', f)
            if m and vtuple(m.group(1)) < vtuple(new):
                fulls.append((vtuple(m.group(1)), m.group(1),
                              os.path.join(dirpath, f)))
                continue
            m = re.fullmatch(r'(\d+(?:\.\d+)+)-(\d+(?:\.\d+)+)-patch\.zip', f)
            if m and vtuple(m.group(2)) <= vtuple(new):
                patches.append((vtuple(m.group(1)), vtuple(m.group(2)),
                                os.path.join(dirpath, f)))
    assert fulls, 'release/ 里没有历史全量包，无法制作增量包'
    fulls.sort()
    base_v, base_zip = fulls[-1][1], fulls[-1][2]
    chain = [p for p in sorted(patches) if p[0] >= vtuple(base_v)]
    return base_v, base_zip, [p[2] for p in chain]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('version')
    ap.add_argument('--notes', default='', help='本版更新说明（进 versions.json）')
    ap.add_argument('--skip-build', action='store_true')
    args = ap.parse_args()
    new = args.version
    os.makedirs(REL, exist_ok=True)
    vdir = os.path.join(REL, new)          # 本版全部产物集中于此
    os.makedirs(vdir, exist_ok=True)

    if not args.skip_build:
        build(new)
    smoke_exe()

    # ---- 完整包 ----
    full_name = f'WindAnaly-{new}.zip'
    full_path = os.path.join(vdir, full_name)
    shutil.make_archive(full_path[:-4], 'zip', root_dir=os.path.join(ROOT,
                                                                     'dist'),
                        base_dir='WindAnaly')
    print(f'full : {full_name} {os.path.getsize(full_path) / 1048576:.1f} MB')

    # ---- 基线重演 ----
    base_v, base_zip, patches = find_baseline(new)
    work = os.path.join(ROOT, '_release_base')
    shutil.rmtree(work, ignore_errors=True)
    with zipfile.ZipFile(base_zip) as zf:
        zf.extractall(work)
    base_dir = os.path.join(work, 'WindAnaly')
    for p in patches:
        print('baseline +=', os.path.basename(p))
        with zipfile.ZipFile(p) as zf:
            zf.extractall(base_dir)
    print(f'baseline: v{base_v} + {len(patches)} patch(es)')

    # ---- diff → 增量包 ----
    old = {}
    for r, d, fs in os.walk(base_dir):
        d[:] = [x for x in d if x not in ('.update', 'data')]
        for f in fs:
            p = os.path.join(r, f)
            old[os.path.relpath(p, base_dir).replace('\\', '/')] = sha256(p)
    changed = []
    for r, d, fs in os.walk(DIST):
        d[:] = [x for x in d if x not in ('.update', 'data')]
        for f in fs:
            p = os.path.join(r, f)
            rel = os.path.relpath(p, DIST).replace('\\', '/')
            if old.get(rel) != sha256(p):
                changed.append(rel)
    # data/ 目录整体排除（用户数据），但 app_version.txt 是程序元数据，
    # 必须随每个补丁更新——独立更新器靠它识别已装版本（1.0.4 修复）
    changed.append('data/app_version.txt')
    changed.sort()
    base_full = base_v
    patch_name = f'{base_full}-{new}-patch.zip'
    patch_path = os.path.join(vdir, patch_name)
    with zipfile.ZipFile(patch_path, 'w', zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zf:
        for rel in changed:
            if rel == 'data/app_version.txt':
                zf.writestr(rel, new + '\n')
            else:
                zf.write(os.path.join(DIST, *rel.split('/')), rel)
    print(f'patch: {patch_name} {len(changed)} files, '
          f'{os.path.getsize(patch_path) / 1048576:.1f} MB')
    shutil.rmtree(work, ignore_errors=True)

    # ---- versions.json ----
    psha = sha256(patch_path)
    vdir = os.path.join(REL, new)
    os.makedirs(vdir, exist_ok=True)
    idx = {'versions': [{
        'version': new,
        'date': time.strftime('%Y-%m-%d'),
        'changelog': args.notes or '缺陷修复与内部优化。',
        'patch': {'base': base_v, 'url': patch_name, 'sha256': psha},
    }]}
    with open(os.path.join(vdir, 'versions.json'), 'w', encoding='utf-8') as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)

    print('\n===== 发布清单 =====')
    print(f'本地留存: {full_name} | {patch_name} | '
          f'release/{new}/versions.json')
    print(f'  patch sha256: {psha}')
    print('GitHub Release 只上传: '
          f'{patch_name} + release/{new}/versions.json')
    print('后续手工: git tag v' + new + ' && git push origin main v' + new
          + '；Release 上传两个资产；git archive 导出源码归档')


if __name__ == '__main__':
    main()
