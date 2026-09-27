"""版本号解析与比较（支持 "1.2" / "1.2.3" / "1.2.3.4" 等）。"""

from typing import Tuple


def parse_version(v: str) -> Tuple[int, ...]:
    """把 "1.2.3" 解析成 (1, 2, 3)；非数字段忽略。"""
    parts: list = []
    for seg in str(v).split('.'):
        num = ''
        for ch in seg:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def compare_versions(a: str, b: str) -> int:
    """a>b 返回 1，a<b 返回 -1，相等返回 0。"""
    pa, pb = parse_version(a), parse_version(b)
    if pa > pb:
        return 1
    if pa < pb:
        return -1
    return 0


def is_newer(remote: str, local: str) -> bool:
    return compare_versions(remote, local) > 0


def is_older(remote: str, local: str) -> bool:
    return compare_versions(remote, local) < 0
