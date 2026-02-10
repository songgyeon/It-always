# memory.py v4
# SQLite 영속 저장 + 인메모리 캐시 하이브리드
# v4: user_id별 대화 기록 분리

"""
서버 재시작해도 기억이 유지됨.
(Render Starter 플랜 + Persistent Disk로 재배포 시에도 기억 유지)

구조:
  SQLite DB (q_memory.db)
    ├── conversations  (user_id, role, content, tag, timestamp)
    └── said_cache     (user_id, content) — 중복 체크용

  인메모리 캐시 (속도용)
    ├── _user_memories{user_id: []}
    └── _user_said{user_id: set()}
"""

import sqlite3
import time
import os
import logging
from collections import defaultdict

logger = logging.getLogger("memory")

# ─── DB 경로 ───
DB_PATH = os.environ.get("Q_MEMORY_DB", "/var/data/q_memory.db")

# ─── 사용자별 인메모리 캐시 ───
_user_memories = defaultdict(list)
_user_said = defaultdict(set)
_user_last_reply = {}
_user_sessions = defaultdict(lambda: defaultdict(list))
_user_session_tag = defaultdict(lambda: "default")
_user_session_start = defaultdict(time.time)


# ════════════════════════════════════
# SQLite 초기화
# ════════════════════════════════════

def _get_db():
    """DB 연결 (WAL 모드 + timeout으로 gunicorn 멀티워커 대응)"""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _init_db():
    """테이블 생성 + 디렉토리 자동 생성"""
    global DB_PATH

    # persistent disk 경로가 없으면 생성 시도, 실패 시 로컬 폴백
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
        except OSError:
            DB_PATH = "q_memory.db"
            logger.warning(f"⚠️ {db_dir} 생성 실패 — 로컬 폴백: {DB_PATH}")

    conn = _get_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'default',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tag TEXT DEFAULT 'default',
                timestamp REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS said_cache (
                user_id TEXT NOT NULL DEFAULT 'default',
                content TEXT NOT NULL,
                PRIMARY KEY (user_id, content)
            );

            CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id);
            CREATE INDEX IF NOT EXISTS idx_conv_role ON conversations(role);
            CREATE INDEX IF NOT EXISTS idx_conv_tag ON conversations(tag);
            CREATE INDEX IF NOT EXISTS idx_conv_time ON conversations(timestamp);
        """)
        conn.commit()
    finally:
        conn.close()


def _load_from_db():
    """서버 시작 시 DB에서 인메모리 캐시로 복원"""
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT user_id, role, content, tag, timestamp FROM conversations ORDER BY id"
        ).fetchall()

        for row in rows:
            uid = row["user_id"]
            entry = {
                "role": row["role"],
                "content": row["content"],
                "timestamp": row["timestamp"],
            }
            _user_memories[uid].append(entry)
            _user_sessions[uid][row["tag"]].append(entry)

            if row["role"] == "assistant":
                _user_last_reply[uid] = row["content"]

        said_rows = conn.execute("SELECT user_id, content FROM said_cache").fetchall()
        for row in said_rows:
            _user_said[row["user_id"]].add(row["content"])

        total = len(rows)
        if total > 0:
            logger.info(f"✅ DB에서 복원: 대화 {total}개")

    finally:
        conn.close()


# 서버 시작 시 자동 초기화
_init_db()
_load_from_db()


# ════════════════════════════════════
# 기본 메모리 함수
# ════════════════════════════════════

def store_memory(role: str, content: str, tag: str = None,
                 user_id: str = "default"):
    ts = time.time()
    session_tag = tag or _user_session_tag[user_id]

    entry = {
        "role": role,
        "content": content,
        "timestamp": ts,
    }

    if role == "assistant":
        _user_last_reply[user_id] = content

    _user_memories[user_id].append(entry)
    _user_said[user_id].add(content)
    _user_sessions[user_id][session_tag].append(entry)

    try:
        conn = _get_db()
        conn.execute(
            "INSERT INTO conversations (user_id, role, content, tag, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, role, content, session_tag, ts),
        )
        conn.execute(
            "INSERT OR IGNORE INTO said_cache (user_id, content) VALUES (?, ?)",
            (user_id, content),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB 저장 실패: {e}")


def fetch_last_memory(user_id: str = "default"):
    last = _user_last_reply.get(user_id, "안녕. 나는 Q야.")
    return {"last": last}


def was_said(content: str, user_id: str = "default") -> bool:
    return content in _user_said[user_id]


def get_recent(n: int = 10, user_id: str = "default") -> list:
    mems = _user_memories[user_id]
    return mems[-n:] if len(mems) > n else mems[:]


def get_recent_by_role(role: str, n: int = 5, user_id: str = "default") -> list:
    filtered = [m for m in _user_memories[user_id] if m["role"] == role]
    return filtered[-n:]


def get_user_messages(n: int = 10, user_id: str = "default") -> list:
    return get_recent_by_role("user", n, user_id)


def get_assistant_messages(n: int = 10, user_id: str = "default") -> list:
    return get_recent_by_role("assistant", n, user_id)


# ════════════════════════════════════
# 세션 태그 관리
# ════════════════════════════════════

def start_session(tag: str, user_id: str = "default"):
    _user_session_tag[user_id] = tag
    _user_session_start[user_id] = time.time()


def get_current_session_tag(user_id: str = "default") -> str:
    return _user_session_tag[user_id]


def get_session_memories(tag: str, user_id: str = "default") -> list:
    return _user_sessions[user_id].get(tag, [])


def get_session_summary(user_id: str = "default") -> dict:
    return {
        "current_tag": _user_session_tag[user_id],
        "total_memories": len(_user_memories[user_id]),
        "total_sessions": len(set(_user_sessions[user_id].keys())),
        "session_tags": list(_user_sessions[user_id].keys()),
        "db_path": DB_PATH,
    }


# ════════════════════════════════════
# 검색
# ════════════════════════════════════

def search_memories(keyword: str, limit: int = 20, user_id: str = "default") -> list:
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT role, content, tag, timestamp FROM conversations "
            "WHERE user_id = ? AND content LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (user_id, f"%{keyword}%", limit),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"검색 실패: {e}")
        return [m for m in _user_memories[user_id] if keyword in m["content"]][:limit]


def get_memory_stats(user_id: str = "default") -> dict:
    try:
        conn = _get_db()
        total = conn.execute(
            "SELECT COUNT(*) as c FROM conversations WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
        user_count = conn.execute(
            "SELECT COUNT(*) as c FROM conversations WHERE user_id = ? AND role='user'",
            (user_id,)
        ).fetchone()["c"]
        assistant_count = conn.execute(
            "SELECT COUNT(*) as c FROM conversations WHERE user_id = ? AND role='assistant'",
            (user_id,)
        ).fetchone()["c"]
        conn.close()

        return {
            "total": total,
            "user_messages": user_count,
            "assistant_messages": assistant_count,
            "said_cache_size": len(_user_said[user_id]),
            "db_path": DB_PATH,
        }
    except Exception as e:
        return {"error": str(e), "in_memory_count": len(_user_memories[user_id])}


def get_memory_count(user_id: str = "default") -> int:
    """사용자별 총 대화 수 (리스트 복사 없이 빠르게)"""
    return len(_user_memories[user_id])


# ════════════════════════════════════
# 리셋
# ════════════════════════════════════

def reset_memory(user_id: str = None):
    """초기화. user_id 지정 시 해당 사용자만, 없으면 전체."""
    if user_id:
        _user_memories[user_id].clear()
        _user_said[user_id].clear()
        _user_last_reply.pop(user_id, None)
        _user_sessions[user_id].clear()
        _user_session_tag[user_id] = "default"

        try:
            conn = _get_db()
            conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM said_cache WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"DB 초기화 실패 (user={user_id}): {e}")
    else:
        _user_memories.clear()
        _user_said.clear()
        _user_last_reply.clear()
        _user_sessions.clear()
        _user_session_tag.clear()

        try:
            conn = _get_db()
            conn.execute("DELETE FROM conversations")
            conn.execute("DELETE FROM said_cache")
            conn.commit()
            conn.close()
            logger.info("✅ DB 전체 초기화 완료")
        except Exception as e:
            logger.error(f"DB 전체 초기화 실패: {e}")
