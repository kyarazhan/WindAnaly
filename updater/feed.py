"""更新器独立取数模块：多源拉取「版本索引」（纯标准库，不导入 core/*）。

主程序启动更新器时通过任务 JSON 传入更新源列表，更新器据此独立获取
全部可用版本 —— 与主程序完全解耦（主程序退出/无响应均不影响）。

版本索引统一为条目列表（新→旧）：
    {"version": "1.0.13", "date": "2026-09-24", "changelog": "...",
     "full":  {"url": ..., "sha256": ...},                  # 可缺省
     "patch": {"base": "1.0.12", "url": ..., "sha256": ...}}  # 可缺省

支持的源：
  A) versions.json（与 manifest.json 同目录，http/https/UNC/本地路径）：
     {"versions": [条目...]}，url 为相对名时按索引所在目录解析。
  B) github-releases：解析 releases 列表页 + expanded_assets 资产页
     （普通网页，不受 GitHub API 匿名配额限制），按文件名识别全量包
     与增量包（*-patch.zip）。
  C) 兜底：单 manifest.json → 单版本条目（旧版发布物兼容）。
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

from version import compare_versions, is_newer, parse_version  # 同目录兄弟模块

_UA = 'WindAnaly-Updater'


# --------------------------------------------------------------- 基础请求
def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _get_json(url: str, timeout: int = 20):
    return json.loads(_get(url, timeout).decode('utf-8', 'replace'))


def _get_text(url: str, timeout: int = 20) -> str:
    return _get(url, timeout).decode('utf-8', 'replace')


def _get_json_any(url: str, timeout: int = 20):
    """读 JSON：http(s) 走 urlopen；本地/UNC 路径直接 open。"""
    if str(url).lower().startswith(('http://', 'https://')):
        return _get_json(url, timeout)
    with open(url, 'r', encoding='utf-8') as f:
        return json.load(f)


def _retry(fn, times: int = 2, pause: float = 1.5):
    last = None
    for _ in range(times):
        try:
            return fn()
        except Exception as e:      # noqa: BLE001 - 网络波动统一重试
            last = e
            time.sleep(pause)
    raise last if last else RuntimeError('request failed')


def _resolve_url(base: str, name: str) -> str:
    """相对名 → 与索引/manifest 同目录的绝对地址。"""
    name = str(name).replace('\\', '/')
    low = name.lower()
    if low.startswith(('http://', 'https://', '\\\\')) or os.path.isabs(name):
        return name
    if base.lower().startswith(('http://', 'https://')):
        return base.rsplit('/', 1)[0] + '/' + name
    return os.path.join(os.path.dirname(os.path.abspath(base)), name)


# --------------------------------------------------------------- 归一化
def _normalize(entries, base, local_version, include_pre):
    """清洗版本条目：解析绝对 URL、过滤损坏条目、新→旧排序。"""
    out = []
    for e in entries or []:
        try:
            v = str(e.get('version', '')).lstrip('v').strip()
            if not v or not re.match(r'^\d+(\.\d+)*$', v):
                continue
            item = {'version': v,
                    'date': str(e.get('date', '')).strip(),
                    'changelog': str(e.get('changelog', '')).strip()}
            full = e.get('full') or {}
            if full.get('url'):
                item['full'] = {'url': _resolve_url(base, full['url']),
                                'sha256': str(full.get('sha256', '') or '')}
            pat = e.get('patch') or {}
            if pat.get('url') and pat.get('base'):
                item['patch'] = {'base': str(pat['base']).lstrip('v'),
                                 'url': _resolve_url(base, pat['url']),
                                 'sha256': str(pat.get('sha256', '') or '')}
            if item.get('pre') and not include_pre:
                continue
            if 'full' not in item and 'patch' not in item:
                continue
            out.append(item)
        except Exception:
            continue
    # 本地版本不比它新的（全量包视角）仅保留最新一条兜底展示
    out.sort(key=lambda x: parse_version(x['version']), reverse=True)
    return out


# --------------------------------------------------------------- 源 A：versions.json
def _from_manifest_url(manifest_url: str, task: dict) -> list:
    """http/UNC/本地源：优先 versions.json，回退单 manifest.json。"""
    low = manifest_url.lower()
    is_http = low.startswith(('http://', 'https://'))
    if is_http:
        idx_url = manifest_url.rsplit('/', 1)[0] + '/versions.json'
    else:
        idx_url = os.path.join(os.path.dirname(os.path.abspath(manifest_url)),
                               'versions.json')
    try:
        data = _get_json_any(idx_url)
        if isinstance(data, dict) and data.get('versions'):
            ents = _normalize(data['versions'], idx_url,
                              task.get('current_version'),
                              bool(task.get('include_prerelease', True)))
            if ents:
                return ents
    except Exception:
        pass
    # 兜底：单 manifest.json
    m = _get_json_any(manifest_url)
    if not isinstance(m, dict) or not str(m.get('version', '')).strip():
        raise ValueError('manifest 无 version 字段')
    base_url = manifest_url if is_http else \
        os.path.dirname(os.path.abspath(manifest_url)) + os.sep
    pkg = str(m.get('url', ''))
    kind = 'patch' if (m.get('base_version') or m.get('kind') == 'patch') \
        else 'full'
    entry = {'version': str(m['version']).lstrip('v'),
             'date': '', 'changelog': str(m.get('changelog', '') or '')}
    info = {'url': _resolve_url(base_url, pkg),
            'sha256': str(m.get('sha256', '') or '')}
    if kind == 'patch':
        entry['patch'] = {'base': str(m.get('base_version', '')).lstrip('v'),
                          **info}
    else:
        entry['full'] = info
    return _normalize([entry], base_url, task.get('current_version'),
                      bool(task.get('include_prerelease', True)))


# --------------------------------------------------------------- 源 B：GitHub Releases
def _gh_releases_page_tags(repo: str, want: int = 10) -> list:
    """解析 releases 列表页 → [(tag, 是否预发布)]（新→旧）。"""
    tags: list = []
    for page in (1, 2):
        html = _get_text(
            f'https://github.com/{repo}/releases?page={page}', timeout=10)
        for m in re.finditer(
                r'href="/[^"]+?/releases/tag/([^"?#/]+)"', html):
            tag = m.group(1)
            if any(t == tag for t, _ in tags):
                continue
            seg = html[m.end(): m.end() + 2500]
            tags.append((tag, 'Pre-release' in seg))
            if len(tags) >= want:
                return tags
    return tags


def _gh_assets(repo: str, tag: str) -> dict:
    """expanded_assets 资产页 → {文件名: 下载直链}。"""
    for url in (f'https://github.com/{repo}/releases/expanded_assets/{tag}',
                f'https://github.com/{repo}/releases/tag/{tag}'):
        try:
            html = _get_text(url, timeout=10)
        except Exception:
            continue
        found: dict = {}
        for href in re.findall(
                r'href="([^"]+?/releases/download/[^"]+?\.zip)"', html):
            if href.startswith('/'):
                href = 'https://github.com' + href
            found[href.rsplit('/', 1)[-1]] = href
        if found:
            return found
    return {}


_PATCH_RE = re.compile(r'(\d+(?:\.\d+)+)-(\d+(?:\.\d+)+)-patch\.zip$',
                       re.I)


def _from_github(repo: str, task: dict) -> list:
    """GitHub Releases → 版本条目（网页通道，不消耗 API 配额）。

    优先读该版本的 versions.json 资产（发布时生成，含全量/增量/说明）；
    没有才解析资产文件名。全量包只认 WindAnaly-<版本>.zip 精确名，
    其余 zip（如 -src.zip 源码存档）一律不当作更新包。"""
    include_pre = bool(task.get('include_prerelease', True))
    entries = []
    for tag, is_pre in _gh_releases_page_tags(repo):
        if is_pre and not include_pre:
            continue
        version = tag.lstrip('v')
        entry = None
        try:
            data = _get_json(
                f'https://github.com/{repo}/releases/download/{tag}'
                f'/versions.json', timeout=10)
            if isinstance(data, dict) and data.get('versions'):
                by_ver = {str(e.get('version')).lstrip('v')
                          for e in data['versions']}
                if version in by_ver:
                    e = next(e for e in data['versions']
                             if str(e.get('version')).lstrip('v') == version)
                    entry = {'version': version,
                             'date': str(e.get('date', '')),
                             'changelog': str(e.get('changelog', '')),
                             'pre': is_pre}
                    full = e.get('full') or {}
                    if full.get('url'):
                        entry['full'] = {
                            'url': _resolve_url(
                                f'https://github.com/{repo}/releases/'
                                f'download/{tag}/', str(full['url'])),
                            'sha256': str(full.get('sha256', '') or '')}
                    pat = e.get('patch') or {}
                    if pat.get('url') and pat.get('base'):
                        entry['patch'] = {
                            'base': str(pat['base']).lstrip('v'),
                            'url': _resolve_url(
                                f'https://github.com/{repo}/releases/'
                                f'download/{tag}/', str(pat['url'])),
                            'sha256': str(pat.get('sha256', '') or '')}
        except Exception:
            entry = None
        if entry is None:
            entry = _entry_from_assets(repo, tag, version, is_pre)
        if entry and ('full' in entry or 'patch' in entry):
            entries.append(entry)
    if not entries:
        raise ValueError('releases 页未解析到任何更新包资产')
    return entries


def _entry_from_assets(repo: str, tag: str, version: str,
                       is_pre: bool) -> dict | None:
    """资产文件名兜底解析（无 versions.json 时的兼容路径）。"""
    assets = _gh_assets(repo, tag)
    entry = {'version': version, 'date': '', 'changelog': '', 'pre': is_pre}
    # 全量包：精确名（忽略 -src.zip 等任何其它 zip）
    exact = f'WindAnaly-{version}.zip'
    for n, u in assets.items():
        if n.lower() == exact.lower():
            entry['full'] = {'url': u, 'sha256': ''}
            break
    for n, u in assets.items():
        m = _PATCH_RE.search(n)
        if m:
            entry['patch'] = {'base': m.group(1), 'url': u, 'sha256': ''}
            break
    if 'full' not in entry and 'patch' not in entry:
        return None
    return entry


# --------------------------------------------------------------- 入口
def fetch_index(task: dict):
    """按源顺序拉取版本索引。返回 (条目列表, 各源状态说明列表)。"""
    notes: list = []
    for src in task.get('sources', []) or []:
        name = src.get('name', src.get('manifest_url', src.get('repo', '?')))
        try:
            if src.get('type') == 'github-releases':
                ents = _retry(lambda: _from_github(src['repo'], task))
            else:
                ents = _retry(
                    lambda: _from_manifest_url(src['manifest_url'], task))
            if ents:
                notes.append(f'{name}：成功（{len(ents)} 个版本）')
                return ents, notes
            notes.append(f'{name}：无可用版本')
        except Exception as e:
            notes.append(f'{name}：{type(e).__name__} {str(e)[:90]}')
    return [], notes


# --------------------------------------------------------------- 体积探测
_SIZE_CACHE: dict = {}


def probe_size(url: str):
    """探测包体积（http HEAD / 本地 getsize），失败返回 None。带缓存。"""
    if url in _SIZE_CACHE:
        return _SIZE_CACHE[url]
    low = str(url).lower()
    size = None
    try:
        if low.startswith(('http://', 'https://')):
            import urllib.request
            req = urllib.request.Request(url, method='HEAD',
                                         headers={'User-Agent': _UA})
            with urllib.request.urlopen(req, timeout=10) as r:
                n = r.headers.get('Content-Length')
                size = int(n) if n else None
        else:
            size = os.path.getsize(url)
    except Exception:
        size = None
    _SIZE_CACHE[url] = size
    return size


# --------------------------------------------------------------- 下载规划
def newer_versions(entries, local_version):
    """比本机新的版本（新→旧）。"""
    return [e for e in entries
            if is_newer(e['version'], local_version)]


def plan_packages(entries, local_version: str, target: str, mode: str):
    """规划下载清单。mode='full' 单全量包；mode='patch' 增量链。

    返回 (下载清单, 错误说明)。清单元素 = {url, sha256, label}，
    按应用顺序排列（增量链从最旧的一跳开始）。"""
    ents = {e['version']: e for e in entries}
    if mode == 'full':
        e = ents.get(target)
        if not e or not e.get('full'):
            return None, f'v{target} 没有全量包，请改用增量包或选择其它版本'
        return [{'url': e['full']['url'], 'sha256': e['full']['sha256'],
                 'label': f'全量包 WindAnaly-{target}.zip'}], ''

    hops: list = []
    cur = local_version
    for _ in range(30):
        if compare_versions(cur, target) >= 0:
            break
        cands = []
        for v, e in ents.items():
            p = e.get('patch')
            if not p:
                continue
            if p.get('base', '') != cur:
                continue
            if not is_newer(v, cur):
                continue
            if compare_versions(v, target) > 0:
                continue            # 不越过目标版本
            cands.append((v, p))
        if not cands:
            return None, (f'没有适用于 v{cur} 的增量包，'
                          f'无法逐级补齐到 v{target}，请改用全量包')
        v, p = max(cands, key=lambda x: parse_version(x[0]))
        hops.append({'url': p['url'], 'sha256': p.get('sha256', ''),
                     'label': f'增量包 v{cur} → v{v}'})
        cur = v
    if compare_versions(cur, target) < 0:
        return None, (f'增量链最多只能到 v{cur}，'
                      f'请改用全量包或选择其它目标版本')
    return hops, ''
