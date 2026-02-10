# memory.py v3
# SQLite 영속 저장 + 인메모리 캐시 하이브리드

"""
서버 재시작해도 기억이 유지됨.
기존 API (memories, was_said, store_memory 등) 100% 호환.

구조:
  SQLite DB (q_memory.db)
    ├── conversations  (role, content, tag, timestamp)
    └── said_cache     (content) — 중복 체크용

  인메모리 캐시 (속도용)
    ├── memories[]     — 기존 코드 호환
    └── said_set{}     — 빠른 중복 체크
"""

import sqlite3
import time
import os
import logging
from collections import defaultdict

logger = logging.getLogger("memory")

# ─── DB 경로 ───
DB_PATH = os.environ.get("Q_MEMORY_DB", "q_memory.db")

# ─── 인메모리 캐시 (기존 코드 호환) ───
memories = []
said_set = set()
last_assistant_reply = "안녕. 나는 Q야."

# ─── 세션 관리 ───
_sessions = defaultdict(list)
_current_session_tag = "default"
_session_start_time = time.time()


# ════════════════════════════════════
# SQLite 초기화
# ════════════════════════════════════

def _get_db():
    """DB 연결 (thread-safe)"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    """테이블 생성 (없으면)"""
    conn = _get_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tag TEXT DEFAULT 'default',
                timestamp REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS said_cache (
                content TEXT PRIMARY KEY
            );

            CREATE INDEX IF NOT EXISTS idx_conv_role ON conversations(role);
            CREATE INDEX IF NOT EXISTS idx_conv_tag ON conversations(tag);
            CREATE INDEX IF NOT EXISTS idx_conv_time ON conversations(timestamp);
        """)
        conn.commit()
    finally:
        conn.close()


def _load_from_db():
    """서버 시작 시 DB에서 인메모리 캐시로 복원"""
    global memories, said_set, last_assistant_reply
    global _sessions

    conn = _get_db()
    try:
        # 대화 기록 로드
        rows = conn.execute(
            "SELECT role, content, tag, timestamp FROM conversations ORDER BY id"
        ).fetchall()

        memories = []
        _sessions = defaultdict(list)

        for row in rows:
            entry = {
                "role": row["role"],
                "content": row["content"],
                "timestamp": row["timestamp"],
            }
            memories.append(entry)
            _sessions[row["tag"]].append(entry)

            if row["role"] == "assistant":
                last_assistant_reply = row["content"]

        # said_cache 로드
        said_rows = conn.execute("SELECT content FROM said_cache").fetchall()
        said_set = {row["content"] for row in said_rows}

        count = len(memories)
        said_count = len(said_set)
        if count > 0:
            logger.info(f"✅ DB에서 복원: 대화 {count}개, said_cache {said_count}개")

    finally:
        conn.close()


# 서버 시작 시 자동 초기화
_init_db()
_load_from_db()


# ════════════════════════════════════
# 기본 메모리 함수 (기존 API 유지)
# ════════════════════════════════════

def store_memory(role: str, content: str, tag: str = None):
    """기억 저장 → 인메모리 + SQLite 동시 기록"""
    global last_assistant_reply

    ts = time.time()
    session_tag = tag or _current_session_tag

    entry = {
        "role": role,
        "content": content,
        "timestamp": ts,
    }

    if role == "assistant":
        last_assistant_reply = content

    # 인메모리
    memories.append(entry)
    said_set.add(content)
    _sessions[session_tag].append(entry)

    # SQLite
    try:
        conn = _get_db()
        conn.execute(
            "INSERT INTO conversations (role, content, tag, timestamp) VALUES (?, ?, ?, ?)",
            (role, content, session_tag, ts),
        )
        conn.execute(
            "INSERT OR IGNORE INTO said_cache (content) VALUES (?)",
            (content,),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB 저장 실패: {e}")
        # 인메모리에는 이미 저장되어 있으므로 서비스는 계속 동작


def fetch_last_memory():
    return {"last": last_assistant_reply}


def was_said(content: str) -> bool:
    """Java hasSaid() 대응 — 이미 말한 적 있는지"""
    return content in said_set


def get_recent(n: int = 10) -> list:
    """최근 N개 대화 기록"""
    return memories[-n:] if len(memories) > n else memories[:]


def get_recent_by_role(role: str, n: int = 5) -> list:
    """역할별 최근 N개"""
    filtered = [m for m in memories if m["role"] == role]
    return filtered[-n:]


def get_user_messages(n: int = 10) -> list:
    return get_recent_by_role("user", n)


def get_assistant_messages(n: int = 10) -> list:
    return get_recent_by_role("assistant", n)


# ════════════════════════════════════
# 세션 태그 관리
# ════════════════════════════════════

def start_session(tag: str):
    global _current_session_tag, _session_start_time
    _current_session_tag = tag
    _session_start_time = time.time()


def get_current_session_tag() -> str:
    return _current_session_tag


def get_session_memories(tag: str) -> list:
    return _sessions.get(tag, [])


def get_all_session_tags() -> list:
    """DB에서 모든 세션 태그 조회"""
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT DISTINCT tag FROM conversations ORDER BY tag"
        ).fetchall()
        conn.close()
        return [row["tag"] for row in rows]
    except Exception:
        return list(_sessions.keys())


def get_session_summary() -> dict:
    return {
        "current_tag": _current_session_tag,
        "total_memories": len(memories),
        "total_sessions": len(set(_sessions.keys())),
        "session_tags": list(_sessions.keys()),
        "session_start": _session_start_time,
        "db_path": DB_PATH,
    }


# ════════════════════════════════════
# 검색 (SQLite 활용)
# ════════════════════════════════════

def search_memories(keyword: str, limit: int = 20) -> list:
    """키워드로 대화 기록 검색 (SQLite LIKE)"""
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT role, content, tag, timestamp FROM conversations "
            "WHERE content LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f"%{keyword}%", limit),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"검색 실패: {e}")
        return [m for m in memories if keyword in m["content"]][:limit]


def get_memory_stats() -> dict:
    """메모리 통계"""
    try:
        conn = _get_db()
        total = conn.execute("SELECT COUNT(*) as c FROM conversations").fetchone()["c"]
        user_count = conn.execute(
            "SELECT COUNT(*) as c FROM conversations WHERE role='user'"
        ).fetchone()["c"]
        assistant_count = conn.execute(
            "SELECT COUNT(*) as c FROM conversations WHERE role='assistant'"
        ).fetchone()["c"]
        tag_count = conn.execute(
            "SELECT COUNT(DISTINCT tag) as c FROM conversations"
        ).fetchone()["c"]
        said_count = conn.execute("SELECT COUNT(*) as c FROM said_cache").fetchone()["c"]
        conn.close()

        return {
            "total": total,
            "user_messages": user_count,
            "assistant_messages": assistant_count,
            "unique_tags": tag_count,
            "said_cache_size": said_count,
            "db_path": DB_PATH,
        }
    except Exception as e:
        return {"error": str(e), "in_memory_count": len(memories)}


# ════════════════════════════════════
# 리셋
# ════════════════════════════════════

def reset_memory():
    """전체 초기화 (인메모리 + DB)"""
    global memories, said_set, last_assistant_reply
    global _current_session_tag, _session_start_time

    memories = []
    said_set = set()
    last_assistant_reply = "안녕. 나는 Q야."
    _sessions.clear()
    _current_session_tag = "default"
    _session_start_time = time.time()

    try:
        conn = _get_db()
        conn.execute("DELETE FROM conversations")
        conn.execute("DELETE FROM said_cache")
        conn.commit()
        conn.close()
        logger.info("✅ DB 초기화 완료")
    except Exception as e:
        logger.error(f"DB 초기화 실패: {e}")
