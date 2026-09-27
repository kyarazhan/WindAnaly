"""总数据库（测风塔台账）：SQLite 单文件，stdlib 内置，零新增依赖。

台账表 masts 即「数据管理」主界面的展示内容，列定义（用户要求）：
  序列号 serial_no   自 10001 起、唯一，用于区分重复站点号；
  站点号 station_no  测风塔/雷达的站点编号（可重复）；
  位置   location；
  设备类型 device_type（测风塔 / 雷达 / 未知）；
  时间范围 t_start ~ t_end；
  完整率 completeness（按时间步长推算：10min → 一年 52560 个点）。

数据集 datasets 记录每个导入来源（库内/外链）、路径、通道与覆盖。
库内（internal）模式的时序整体写入 series_<id> 宽表，由 pandas 直接读写。
"""

import json
import os
import sqlite3

import pandas as pd

_DB_NAME = 'windkit.db'
_SERIAL_BASE = 10000          # 下一个序列号 = MAX+1 → 首条 10001

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS masts(
        serial_no    INTEGER PRIMARY KEY,
        station_no   TEXT DEFAULT '',
        location     TEXT DEFAULT '',
        device_type  TEXT DEFAULT '未知',
        lat          REAL,
        lon          REAL,
        elevation    REAL,
        t_start      TEXT,
        t_end        TEXT,
        completeness REAL,
        note         TEXT DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS datasets(
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        serial_no   TEXT NOT NULL,
        name        TEXT NOT NULL,
        mode        TEXT NOT NULL DEFAULT 'internal',
        path        TEXT DEFAULT '',
        t_start     TEXT,
        t_end       TEXT,
        dt_min      REAL,
        channels_json TEXT DEFAULT '',
        coverage    REAL,
        note        TEXT DEFAULT ''
    )""",
]


class Library:
    """测风塔台账库。"""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            from core.paths import user_data_dir
            base = user_data_dir()
            os.makedirs(base, exist_ok=True)
            db_path = os.path.join(base, _DB_NAME)
        self.db_path = db_path

    # ---- 连接 ----
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    def ensure_db(self):
        """建表；若存在旧 schema（无 serial_no）则重建以兼容。"""
        with self._conn() as conn:
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(masts)").fetchall()]
            if cols and 'serial_no' not in cols:
                conn.execute('DROP TABLE IF EXISTS datasets')
                conn.execute('DROP TABLE IF EXISTS masts')
                cols = []
            for sql in _SCHEMA:
                conn.execute(sql)
            # 旧表迁移：缺列则 ALTER（兼容此前只有 lat/lon 的版本）
            if cols:
                if 'elevation' not in cols:
                    conn.execute('ALTER TABLE masts ADD COLUMN elevation REAL')

    # ---- 序列号 ----
    def next_serial(self) -> int:
        self.ensure_db()
        with self._conn() as conn:
            row = conn.execute('SELECT MAX(serial_no) FROM masts').fetchone()
        return (row[0] or _SERIAL_BASE) + 1

    def station_no_exists(self, station_no: str) -> bool:
        if not station_no:
            return False
        self.ensure_db()
        with self._conn() as conn:
            n = conn.execute(
                'SELECT COUNT(*) FROM masts WHERE station_no=?',
                (station_no,)).fetchone()[0]
        return n > 0

    # ---- 测风塔台账（= 主界面行）----
    def list_stations(self) -> list[dict]:
        self.ensure_db()
        with self._conn() as conn:
            rows = conn.execute(
                'SELECT serial_no,station_no,location,device_type,lat,lon,'
                'elevation,t_start,t_end,completeness,note FROM masts '
                'ORDER BY serial_no'
            ).fetchall()
        keys = ('serial_no', 'station_no', 'location', 'device_type', 'lat',
                'lon', 'elevation', 't_start', 't_end', 'completeness', 'note')
        return [dict(zip(keys, r)) for r in rows]

    def add_station(self, serial_no: int, station_no: str, location: str,
                    device_type: str, t_start: str, t_end: str,
                    completeness: float, lat=None, lon=None, elevation=None,
                    note: str = '') -> int:
        self.ensure_db()
        with self._conn() as conn:
            conn.execute(
                'INSERT INTO masts(serial_no,station_no,location,device_type,'
                'lat,lon,elevation,t_start,t_end,completeness,note) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (serial_no, station_no, location, device_type, lat, lon,
                 elevation, t_start, t_end, completeness, note))
        return serial_no

    def get_station(self, serial_no: int) -> dict | None:
        self.ensure_db()
        with self._conn() as conn:
            r = conn.execute(
                'SELECT serial_no,station_no,location,device_type,lat,lon,'
                'elevation,t_start,t_end,completeness,note FROM masts '
                'WHERE serial_no=?',
                (serial_no,)).fetchone()
        if not r:
            return None
        keys = ('serial_no', 'station_no', 'location', 'device_type', 'lat',
                'lon', 'elevation', 't_start', 't_end', 'completeness', 'note')
        return dict(zip(keys, r))

    def update_station(self, serial_no: int, fields: dict):
        """按字段字典更新台账（只更新给定键）。"""
        allowed = {'station_no', 'location', 'device_type', 'lat', 'lon',
                   'elevation', 't_start', 't_end', 'completeness', 'note'}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        self.ensure_db()
        with self._conn() as conn:
            placeholders = ', '.join(f'{k}=?' for k in sets)
            conn.execute(
                f'UPDATE masts SET {placeholders} WHERE serial_no=?',
                (*sets.values(), serial_no))

    def remove_station(self, serial_no: int):
        self.ensure_db()
        with self._conn() as conn:
            ids = [r[0] for r in conn.execute(
                'SELECT id FROM datasets WHERE serial_no=?',
                (serial_no,)).fetchall()]
            for did in ids:
                conn.execute(f'DROP TABLE IF EXISTS series_{did}')
            conn.execute('DELETE FROM datasets WHERE serial_no=?',
                         (serial_no,))
            conn.execute('DELETE FROM masts WHERE serial_no=?', (serial_no,))

    # ---- 数据集登记 ----
    def register(self, serial_no: int, name: str, mode: str,
                 path: str = '', meta: dict | None = None) -> int:
        meta = meta or {}
        self.ensure_db()
        with self._conn() as conn:
            cur = conn.execute(
                'INSERT INTO datasets(serial_no,name,mode,path,t_start,t_end,'
                'dt_min,channels_json,coverage,note) '
                'VALUES(?,?,?,?,?,?,?,?,?,?)',
                (serial_no, name, mode, path,
                 meta.get('t_start'), meta.get('t_end'),
                 meta.get('dt_min'),
                 json.dumps(meta.get('channels', []), ensure_ascii=False),
                 meta.get('coverage'), meta.get('note', '')))
            return cur.lastrowid

    def list_datasets(self, serial_no: int | None = None) -> list[dict]:
        self.ensure_db()
        sql = ('SELECT id,serial_no,name,mode,path,t_start,t_end,dt_min,'
               'channels_json,coverage FROM datasets')
        args: tuple = ()
        if serial_no is not None:
            sql += ' WHERE serial_no=?'
            args = (serial_no,)
        sql += ' ORDER BY id'
        with self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        keys = ('id', 'serial_no', 'name', 'mode', 'path', 't_start',
                't_end', 'dt_min', 'channels_json', 'coverage')
        out = []
        for r in rows:
            d = dict(zip(keys, r))
            d['channels'] = json.loads(d.pop('channels_json') or '[]')
            out.append(d)
        return out

    def update_path(self, ds_id: int, path: str):
        self.ensure_db()
        with self._conn() as conn:
            conn.execute('UPDATE datasets SET path=? WHERE id=?',
                         (path, ds_id))

    def update_channels(self, ds_id: int, channels: list):
        """更新数据集通道注册（channels_json）。"""
        self.ensure_db()
        with self._conn() as conn:
            conn.execute(
                'UPDATE datasets SET channels_json=? WHERE id=?',
                (json.dumps(channels, ensure_ascii=False), ds_id))

    def remove_dataset(self, ds_id: int):
        self.ensure_db()
        with self._conn() as conn:
            conn.execute(f'DROP TABLE IF EXISTS series_{ds_id}')
            conn.execute('DELETE FROM datasets WHERE id=?', (ds_id,))

    # ---- 库内时序读写（internal 模式）----
    def store_series(self, ds_id: int, df: pd.DataFrame):
        """DataFrame（datetime 索引）→ series_<id> 宽表。"""
        self.ensure_db()
        store = df.copy()
        store.index.name = 't'
        store = store.reset_index()
        with self._conn() as conn:
            store.to_sql(f'series_{ds_id}', conn, if_exists='replace',
                         index=False)

    def load_series(self, ds_id: int) -> pd.DataFrame:
        self.ensure_db()
        with self._conn() as conn:
            df = pd.read_sql(f'SELECT * FROM series_{ds_id}', conn,
                             parse_dates=['t'])
        if 't' in df.columns:
            df = df.set_index('t').sort_index()
        return df
