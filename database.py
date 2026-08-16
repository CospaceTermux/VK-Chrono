import sqlite3
import json
from datetime import datetime, date
from typing import List, Dict, Any, Optional
from config import config

class Database:
    """Управление локальной базой данных SQLite для VK Chrono."""
    
    def __init__(self, db_path=None):
        self.db_path = str(db_path or config.DB_PATH)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def init_db(self):
        """Инициализация таблиц базы данных."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                domain TEXT DEFAULT '',
                avatar_path TEXT DEFAULT '',
                avatar_url TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Таблица сообщений
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vk_msg_id INTEGER,
                peer_id INTEGER NOT NULL,
                from_id INTEGER NOT NULL,
                text TEXT DEFAULT '',
                attachments_json TEXT DEFAULT '[]',
                reply_json TEXT DEFAULT NULL,
                fwd_json TEXT DEFAULT '[]',
                date_str TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (from_id) REFERENCES users(user_id)
            );
            """)

            # Индексы для быстрого поиска
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_date_peer ON messages(peer_id, date_str);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_vk_msg_id ON messages(vk_msg_id, peer_id);")

            # Таблица дневных сводок
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_summaries (
                date_str TEXT NOT NULL,
                peer_id INTEGER NOT NULL,
                summary_md TEXT NOT NULL,
                topics_json TEXT DEFAULT '[]',
                decisions_json TEXT DEFAULT '[]',
                participants_json TEXT DEFAULT '[]',
                message_count INTEGER DEFAULT 0,
                html_path TEXT DEFAULT '',
                md_path TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (date_str, peer_id)
            );
            """)

            # Таблица недельных отчетов
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS weekly_reports (
                week_key TEXT NOT NULL,
                peer_id INTEGER NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                summary_md TEXT NOT NULL,
                days_count INTEGER DEFAULT 0,
                message_count INTEGER DEFAULT 0,
                html_path TEXT DEFAULT '',
                md_path TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (week_key, peer_id)
            );
            """)

            # Таблица месячных отчетов
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS monthly_reports (
                month_key TEXT NOT NULL,
                peer_id INTEGER NOT NULL,
                summary_md TEXT NOT NULL,
                days_count INTEGER DEFAULT 0,
                message_count INTEGER DEFAULT 0,
                html_path TEXT DEFAULT '',
                md_path TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (month_key, peer_id)
            );
            """)
            conn.commit()

    # --- Методы для пользователей ---

    def upsert_user(self, user_id: int, first_name: str, last_name: str, 
                    domain: str = "", avatar_path: str = "", avatar_url: str = ""):
        """Добавляет или обновляет информацию о пользователе."""
        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO users (user_id, first_name, last_name, domain, avatar_path, avatar_url, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                domain = CASE WHEN excluded.domain != '' THEN excluded.domain ELSE users.domain END,
                avatar_path = CASE WHEN excluded.avatar_path != '' THEN excluded.avatar_path ELSE users.avatar_path END,
                avatar_url = CASE WHEN excluded.avatar_url != '' THEN excluded.avatar_url ELSE users.avatar_url END,
                updated_at = CURRENT_TIMESTAMP;
            """, (user_id, first_name, last_name, domain, avatar_path, avatar_url))
            conn.commit()

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Возвращает информацию о пользователе."""
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def get_all_users_dict(self) -> Dict[int, Dict[str, Any]]:
        """Возвращает словарь всех пользователей {user_id: user_dict}."""
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM users").fetchall()
            return {row["user_id"]: dict(row) for row in rows}

    # --- Методы для сообщений ---

    def save_message(self, vk_msg_id: int, peer_id: int, from_id: int, 
                     text: str, attachments: list = None, reply: dict = None, 
                     fwd: list = None, timestamp: int = None) -> int:
        """Сохраняет сообщение в базу данных."""
        if timestamp is None:
            timestamp = int(datetime.now().timestamp())
        date_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
        
        att_json = json.dumps(attachments or [], ensure_ascii=False)
        reply_json = json.dumps(reply, ensure_ascii=False) if reply else None
        fwd_json = json.dumps(fwd or [], ensure_ascii=False)

        with self.get_connection() as conn:
            cursor = conn.execute("""
            INSERT INTO messages (vk_msg_id, peer_id, from_id, text, attachments_json, reply_json, fwd_json, date_str, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (vk_msg_id, peer_id, from_id, text, att_json, reply_json, fwd_json, date_str, timestamp))
            conn.commit()
            return cursor.lastrowid

    def get_messages_for_date(self, peer_id: int, date_str: str) -> List[Dict[str, Any]]:
        """Возвращает сообщения за конкретную дату для беседы с объединенными данными пользователя."""
        with self.get_connection() as conn:
            query = """
            SELECT 
                m.id, m.vk_msg_id, m.peer_id, m.from_id, m.text,
                m.attachments_json, m.reply_json, m.fwd_json,
                m.date_str, m.timestamp,
                u.first_name, u.last_name, u.domain, u.avatar_path, u.avatar_url
            FROM messages m
            LEFT JOIN users u ON m.from_id = u.user_id
            WHERE m.peer_id = ? AND m.date_str = ?
            ORDER BY m.timestamp ASC
            """
            rows = conn.execute(query, (peer_id, date_str)).fetchall()
            
            result = []
            for row in rows:
                item = dict(row)
                item["attachments"] = json.loads(item["attachments_json"] or "[]")
                item["reply"] = json.loads(item["reply_json"]) if item["reply_json"] else None
                item["fwd"] = json.loads(item["fwd_json"] or "[]")
                item["time_str"] = datetime.fromtimestamp(item["timestamp"]).strftime("%H:%M:%S")
                item["full_name"] = f"{item.get('first_name') or 'Пользователь'} {item.get('last_name') or str(item['from_id'])}".strip()
                result.append(item)
            return result

    def get_messages_for_range(self, peer_id: int, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Возвращает сообщения за диапазон дат."""
        with self.get_connection() as conn:
            query = """
            SELECT 
                m.id, m.vk_msg_id, m.peer_id, m.from_id, m.text,
                m.attachments_json, m.reply_json, m.fwd_json,
                m.date_str, m.timestamp,
                u.first_name, u.last_name, u.domain, u.avatar_path, u.avatar_url
            FROM messages m
            LEFT JOIN users u ON m.from_id = u.user_id
            WHERE m.peer_id = ? AND m.date_str >= ? AND m.date_str <= ?
            ORDER BY m.timestamp ASC
            """
            rows = conn.execute(query, (peer_id, start_date, end_date)).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["attachments"] = json.loads(item["attachments_json"] or "[]")
                item["reply"] = json.loads(item["reply_json"]) if item["reply_json"] else None
                item["fwd"] = json.loads(item["fwd_json"] or "[]")
                item["time_str"] = datetime.fromtimestamp(item["timestamp"]).strftime("%H:%M:%S")
                item["full_name"] = f"{item.get('first_name') or 'Пользователь'} {item.get('last_name') or str(item['from_id'])}".strip()
                result.append(item)
            return result

    def get_distinct_dates_for_peer(self, peer_id: int) -> List[str]:
        """Возвращает список уникальных дат с сообщениями для беседы."""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT date_str FROM messages WHERE peer_id = ? ORDER BY date_str ASC", 
                (peer_id,)
            ).fetchall()
            return [row["date_str"] for row in rows]

    def get_distinct_peers(self) -> List[int]:
        """Возвращает список всех peer_id, по которым есть сообщения."""
        with self.get_connection() as conn:
            rows = conn.execute("SELECT DISTINCT peer_id FROM messages").fetchall()
            return [row["peer_id"] for row in rows]

    # --- Методы для сводок и отчетов ---

    def save_daily_summary(self, date_str: str, peer_id: int, summary_md: str,
                           topics: list = None, decisions: list = None,
                           participants: list = None, message_count: int = 0,
                           html_path: str = "", md_path: str = ""):
        """Сохраняет готовую дневную сводку."""
        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO daily_summaries 
            (date_str, peer_id, summary_md, topics_json, decisions_json, participants_json, message_count, html_path, md_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date_str, peer_id) DO UPDATE SET
                summary_md = excluded.summary_md,
                topics_json = excluded.topics_json,
                decisions_json = excluded.decisions_json,
                participants_json = excluded.participants_json,
                message_count = excluded.message_count,
                html_path = excluded.html_path,
                md_path = excluded.md_path,
                created_at = CURRENT_TIMESTAMP
            """, (
                date_str, peer_id, summary_md,
                json.dumps(topics or [], ensure_ascii=False),
                json.dumps(decisions or [], ensure_ascii=False),
                json.dumps(participants or [], ensure_ascii=False),
                message_count, str(html_path), str(md_path)
            ))
            conn.commit()

    def get_daily_summary(self, date_str: str, peer_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM daily_summaries WHERE date_str = ? AND peer_id = ?",
                (date_str, peer_id)
            ).fetchone()
            if not row:
                return None
            res = dict(row)
            res["topics"] = json.loads(res["topics_json"] or "[]")
            res["decisions"] = json.loads(res["decisions_json"] or "[]")
            res["participants"] = json.loads(res["participants_json"] or "[]")
            return res

    def get_daily_summaries_in_range(self, peer_id: int, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("""
            SELECT * FROM daily_summaries
            WHERE peer_id = ? AND date_str >= ? AND date_str <= ?
            ORDER BY date_str ASC
            """, (peer_id, start_date, end_date)).fetchall()
            res = []
            for row in rows:
                item = dict(row)
                item["topics"] = json.loads(item["topics_json"] or "[]")
                item["decisions"] = json.loads(item["decisions_json"] or "[]")
                item["participants"] = json.loads(item["participants_json"] or "[]")
                res.append(item)
            return res

    def save_weekly_report(self, week_key: str, peer_id: int, start_date: str, end_date: str,
                           summary_md: str, days_count: int, message_count: int,
                           html_path: str, md_path: str):
        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO weekly_reports (week_key, peer_id, start_date, end_date, summary_md, days_count, message_count, html_path, md_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(week_key, peer_id) DO UPDATE SET
                summary_md = excluded.summary_md,
                days_count = excluded.days_count,
                message_count = excluded.message_count,
                html_path = excluded.html_path,
                md_path = excluded.md_path,
                created_at = CURRENT_TIMESTAMP
            """, (week_key, peer_id, start_date, end_date, summary_md, days_count, message_count, str(html_path), str(md_path)))
            conn.commit()

    def save_monthly_report(self, month_key: str, peer_id: int, summary_md: str,
                            days_count: int, message_count: int, html_path: str, md_path: str):
        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO monthly_reports (month_key, peer_id, summary_md, days_count, message_count, html_path, md_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(month_key, peer_id) DO UPDATE SET
                summary_md = excluded.summary_md,
                days_count = excluded.days_count,
                message_count = excluded.message_count,
                html_path = excluded.html_path,
                md_path = excluded.md_path,
                created_at = CURRENT_TIMESTAMP
            """, (month_key, peer_id, summary_md, days_count, message_count, str(html_path), str(md_path)))
            conn.commit()

db = Database()
