import sqlite3
from typing import Optional


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bookings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    user_name TEXT,
                    phone TEXT,
                    service TEXT,
                    date TEXT NOT NULL,
                    time TEXT NOT NULL,
                    source TEXT DEFAULT 'bot',
                    notes TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Миграция: добавляем колонки если их нет (для старых БД)
            existing = [row[1] for row in conn.execute("PRAGMA table_info(bookings)").fetchall()]
            for col, typedef in [
                ("phone", "TEXT DEFAULT ''"),
                ("service", "TEXT DEFAULT ''"),
                ("source", "TEXT DEFAULT 'bot'"),
                ("notes", "TEXT DEFAULT ''"),
            ]:
                if col not in existing:
                    conn.execute(f"ALTER TABLE bookings ADD COLUMN {col} {typedef}")

    def add_booking(self, user_id: Optional[int], user_name: str, date: str, time: str,
                    phone: str = "", service: str = "", source: str = "bot", notes: str = ""):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO bookings (user_id, user_name, phone, service, date, time, source, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, user_name, phone, service, date, time, source, notes)
            )

    def get_bookings_for_date(self, date: str) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM bookings WHERE date = ? ORDER BY time", (date,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_user_bookings(self, user_id: int) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM bookings WHERE user_id = ? AND date >= date('now') ORDER BY date, time",
                (user_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_booking_by_id(self, booking_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM bookings WHERE id = ?", (booking_id,)
            ).fetchone()
            return dict(row) if row else None

    def delete_booking(self, booking_id: int):
        with self._conn() as conn:
            conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))

    def get_all_bookings(self, from_date: str = None, to_date: str = None) -> list:
        with self._conn() as conn:
            if from_date and to_date:
                rows = conn.execute(
                    "SELECT * FROM bookings WHERE date BETWEEN ? AND ? ORDER BY date, time",
                    (from_date, to_date)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM bookings WHERE date >= date('now') ORDER BY date, time"
                ).fetchall()
            return [dict(r) for r in rows]

    def get_stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
            today = conn.execute(
                "SELECT COUNT(*) FROM bookings WHERE date = date('now')"
            ).fetchone()[0]
            this_month = conn.execute(
                "SELECT COUNT(*) FROM bookings WHERE strftime('%Y-%m', date) = strftime('%Y-%m', 'now')"
            ).fetchone()[0]
            by_source = conn.execute(
                "SELECT source, COUNT(*) as cnt FROM bookings GROUP BY source"
            ).fetchall()
            by_service = conn.execute(
                "SELECT service, COUNT(*) as cnt FROM bookings WHERE service != '' GROUP BY service ORDER BY cnt DESC"
            ).fetchall()
            return {
                "total": total,
                "today": today,
                "this_month": this_month,
                "by_source": [dict(r) for r in by_source],
                "by_service": [dict(r) for r in by_service],
            }
