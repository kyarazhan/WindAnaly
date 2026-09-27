"""导入解析器注册表回归测试（S3-3：插件化分发）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import io_import as io


def test_registry_content_and_order():
    names = [e['name'] for e in io._PARSERS]
    # 注册顺序 = 兜底探测优先级（Symphonie 最先，WRA 最后）
    assert names == ['NRG Symphonie', 'Windographer 文本', 'Molas 雷达',
                     'WRA 标准列名']
    assert len(names) == len(set(names))
    for e in io._PARSERS:
        assert callable(e['match']) and callable(e['parser'])


def test_match_predicates():
    sym, wind, molas, wra = (e['match'] for e in io._PARSERS)
    assert sym('x.txt', 'SymphoniePRO Records')
    assert sym('x.txt', 'NRG Systems SymphoniePRO')
    assert not sym('x.txt', 'plain csv')
    assert wind('a.rwd', '')
    assert wind('a.txt', 'Windographer Format')
    assert not wind('a.txt', 'plain csv')
    assert molas('x.txt', 'ID System=WS100\nRange Gate 1')
    assert molas('x.txt', 'Molas B300M')
    assert not molas('x.txt', 'plain csv')
    assert wra('x.txt', 'Elevation 80m\nSPEED 8.1')
    assert wra('x.txt', 'Elevation 80m\nspeed 8.1')
    assert not wra('x.txt', 'plain csv')


def test_parse_file_excel_and_binary_guard(tmp_path):
    # NRG 二进制给出友好报错（而不是晦涩异常）
    p = tmp_path / 'bad.rld'
    p.write_bytes(b'\x00\x01')
    try:
        io.parse_file(str(p))
        raised = ''
    except ValueError as e:
        raised = str(e)
    assert 'NRG' in raised and 'TXT/CSV' in raised

    # Excel 走专用分支（空表也应返回 ParsedData 而不是误入通用解析）
    import pandas as pd
    x = tmp_path / 't.xlsx'
    pd.DataFrame({'Time': ['2026-01-01 00:00'], 'Spd80': [7.0]}).to_excel(
        x, index=False)
    parsed = io.parse_file(str(x))
    assert parsed.fmt == 'Excel'


def test_parse_file_fallback_uses_registry(tmp_path, monkeypatch):
    """通用解析结果过弱时，应按注册表匹配命中专用解析器。"""
    calls = []
    for e in io._PARSERS:
        orig = e['parser']

        def wrap(path, _orig=orig, _e=e):
            calls.append(_e['name'])
            return _orig(path)
        e['parser'] = wrap
    # 头部带 SymphoniePRO 标记的弱数据文件 → 应命中 NRG Symphonie
    p = tmp_path / 'weak.txt'
    p.write_text('SymphoniePRO Station\nCol1,Col2\n1,2\n', encoding='utf-8')
    try:
        io.parse_file(str(p))
    except Exception:
        pass                      # 专用解析器对假数据可能失败，只看分发
    assert calls and calls[0] == 'NRG Symphonie', calls
