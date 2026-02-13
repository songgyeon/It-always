"""
Group Sync — 집단 동기화 모듈

특허 명세서:
  "집단 동기화"
  "집단 동기화 모듈을 블록체인 기반 합의 구조로 확장"

구현 (단일 서버 기준):
  - 여러 Q 인스턴스(사용자) 간의 집단 상태 공유
  - 글로벌 감정 온도 (전체 사용자 평균 P(t))
  - 집단 침묵률 (L0 진입 비율)
  - 합의 기반 정책 전환 (다수가 침묵이면 전체 침묵 경향 강화)
  - 이벤트 브로드캐스트 (특정 사용자의 상태가 전체에 영향)

v6: 비활성 사용자 정리 (메모리 누수 방지)

※ 블록체인 확장은 멀티서버 배포 시 구현 (현재는 인메모리 합의)
"""

import time
import random
from collections import deque
from threading import Lock

# ─── 집단 상태 ───
_global_state = {
    "total_messages": 0,
    "total_silences": 0,
    "active_users": {},        # user_id → last_active_ts
    "recent_pts": deque(maxlen=100),  # 최근 100개 P(t) 값
    "recent_modes": deque(maxlen=100),
    "events": deque(maxlen=50),       # 브로드캐스트 이벤트
}
_lock = Lock()

# ─── 합의 파라미터 ───
SILENCE_CONSENSUS_THRESHOLD = 0.6  # 60% 이상이 침묵이면 집단 침묵 경향
ACTIVITY_TIMEOUT = 3600            # 1시간 비활동 시 비활성 사용자
_CLEANUP_INTERVAL = 300            # 정리 주기 (5분)
_last_cleanup = 0

# ─── 명세서 5.9: TTL·레이트리밋·차등프라이버시 ───
SIGMA_TTL = 2.0            # σ 요약치 TTL (초) — 명세서: TTL ≤ 2초
RATE_LIMIT_PER_SEC = 1.0   # 전송율 상한 — 명세서: ≤ 1 msg/s
DP_SIGMA = 0.02            # 차등프라이버시 노이즈 σ_dp
_user_last_record = {}     # user_id → 마지막 record 시각 (레이트리밋용)


def _cleanup_inactive():
    """비활성 사용자 정리 (v6: 메모리 누수 방지)"""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return

    expired = [
        uid for uid, ts in _global_state["active_users"].items()
        if now - ts >= ACTIVITY_TIMEOUT
    ]
    for uid in expired:
        del _global_state["active_users"][uid]

    _last_cleanup = now


def record_interaction(user_id: str, pt: float, mode: str):
    """사용자 상호작용 기록 (명세서 5.9: 레이트리밋 + 차등프라이버시 적용)"""
    with _lock:
        now = time.time()

        # 레이트리밋: 사용자당 1 msg/s 이하
        last = _user_last_record.get(user_id, 0)
        if now - last < (1.0 / RATE_LIMIT_PER_SEC):
            return  # 초과 시 무시
        _user_last_record[user_id] = now

        _global_state["total_messages"] += 1
        if mode.startswith("L0"):
            _global_state["total_silences"] += 1

        _global_state["active_users"][user_id] = now

        # 차등프라이버시 노이즈 주입 (pt에 노이즈 추가 후 기록)
        noisy_pt = pt + random.gauss(0, DP_SIGMA)
        noisy_pt = max(0.0, min(1.0, noisy_pt))
        _global_state["recent_pts"].append((noisy_pt, now))
        _global_state["recent_modes"].append((mode, now))

        # 주기적 정리
        _cleanup_inactive()


def get_collective_temperature() -> float:
    """
    집단 감정 온도: TTL 이내 사용자의 평균 P(t)
    높을수록 활발, 낮을수록 침묵 경향
    (명세서 5.9: σ TTL ≤ 2초 적용)
    """
    with _lock:
        now = time.time()
        # TTL 필터: SIGMA_TTL 이내의 pt만 사용 (단, 최소 직전 30초 데이터 보장)
        ttl = max(SIGMA_TTL, 30.0)
        pts = [p for p, ts in _global_state["recent_pts"] if now - ts < ttl]
        if not pts:
            # TTL 내 데이터 없으면 전체 사용
            pts = [p for p, _ in _global_state["recent_pts"]]
        if not pts:
            return 0.5
        return round(sum(pts) / len(pts), 3)


def get_silence_ratio() -> float:
    """집단 침묵률: TTL 이내 최근 모드 중 L0 비율"""
    with _lock:
        now = time.time()
        ttl = max(SIGMA_TTL, 30.0)
        modes = [m for m, ts in _global_state["recent_modes"] if now - ts < ttl]
        if not modes:
            modes = [m for m, _ in _global_state["recent_modes"]]
        if not modes:
            return 0.0
        l0_count = sum(1 for m in modes if m.startswith("L0"))
        return round(l0_count / len(modes), 3)


def get_active_user_count() -> int:
    """현재 활성 사용자 수"""
    with _lock:
        now = time.time()
        return sum(
            1 for ts in _global_state["active_users"].values()
            if now - ts < ACTIVITY_TIMEOUT
        )


def should_amplify_silence() -> bool:
    """
    합의 기반 침묵 증폭:
    집단 침묵률이 임계치를 넘으면 전체 침묵 경향 강화
    """
    return get_silence_ratio() >= SILENCE_CONSENSUS_THRESHOLD


def get_collective_modifier() -> dict:
    """
    집단 상태가 개별 P(t)에 미치는 수정자

    Returns:
        {
            "pt_offset": float,      # P(t)에 더할 값 (음수 = 침묵 유도)
            "amplify_silence": bool,  # 집단 침묵 합의 여부
            "temperature": float,     # 집단 감정 온도
            "silence_ratio": float,
            "active_users": int,
        }
    """
    temp = get_collective_temperature()
    ratio = get_silence_ratio()
    active = get_active_user_count()
    amplify = should_amplify_silence()

    # 집단 침묵 합의 시 P(t)를 약간 낮춤
    pt_offset = -0.05 if amplify else 0.0

    # 활성 사용자가 많을수록 약간 활발해짐
    if active > 5:
        pt_offset += 0.02

    return {
        "pt_offset": round(pt_offset, 3),
        "amplify_silence": amplify,
        "temperature": temp,
        "silence_ratio": ratio,
        "active_users": active,
    }


def broadcast_event(user_id: str, event_type: str, data: dict = None):
    """
    이벤트 브로드캐스트
    event_type: "crisis" | "long_silence" | "reconnect" | "mood_shift"
    """
    with _lock:
        event = {
            "user_id": user_id,
            "type": event_type,
            "data": data or {},
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        }
        _global_state["events"].append(event)


def get_recent_events(limit: int = 10) -> list:
    """최근 이벤트 조회"""
    with _lock:
        events = list(_global_state["events"])
        return events[-limit:]


def get_sync_status() -> dict:
    """전체 집단 동기화 상태"""
    return {
        "total_messages": _global_state["total_messages"],
        "total_silences": _global_state["total_silences"],
        "collective_temperature": get_collective_temperature(),
        "silence_ratio": get_silence_ratio(),
        "active_users": get_active_user_count(),
        "amplify_silence": should_amplify_silence(),
        "recent_events": get_recent_events(5),
    }


def reset():
    """집단 상태 리셋"""
    with _lock:
        _global_state["total_messages"] = 0
        _global_state["total_silences"] = 0
        _global_state["active_users"].clear()
        _global_state["recent_pts"].clear()
        _global_state["recent_modes"].clear()
        _global_state["events"].clear()
