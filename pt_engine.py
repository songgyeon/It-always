"""
PtEngine — UNLIQ 출력 제어 엔진 v4
특허 기반: P(t) 판정값으로 L2(발화) / L1(저감) / L0(침묵) 자율 선택

v4 변경사항:
  - user_id별 상태 분리 (다중 사용자 지원)
  - 기존 로직 100% 유지
"""

import time
import memory_flow

# ─── 임계치 설정 (특허 기반) ───
T = 0.60       # L2 임계치 (이상이면 발화)
T1 = 0.35      # L1 임계치 (이상이면 저감, 미만이면 침묵)
DELTA_H = 0.05  # 히스테리시스 폭
T_REARM = 10    # 재무장 시간 (초)

# ─── 사용자별 상태 저장소 ───
_user_states = {}


def _get_state(user_id: str) -> dict:
    """사용자별 상태를 가져오거나 새로 생성"""
    if user_id not in _user_states:
        _user_states[user_id] = {
            "last_input_time": 0,
            "session_start": time.time(),
            "message_count": 0,
            "silence_count": 0,
            "last_mode": "L2",
            "last_l0_time": 0,
            "tone_history": [],
            "intent_history": [],
        }
    return _user_states[user_id]


# ─── P(t) 계산 ───
def compute_pt(tone: str, intent: str, message: str,
               memory_count: int = 0,
               closeness: float = 0.5, doubt: float = 0.3,
               user_id: str = "default") -> float:
    now = time.time()
    state = _get_state(user_id)

    # ── E: 감정 변수 ──
    tone_weights = {
        "SAD": 0.7,
        "CURIOUS": 0.6,
        "GENTLE": 0.4,
        "FIRM": 0.3,
        "SARCASTIC": 0.2,
        "AVOIDING": 0.15,
        "NEUTRAL": 0.4,
    }
    E = tone_weights.get(tone.upper(), 0.4)

    if memory_flow.is_tone_shifting(user_id):
        E = min(E + 0.1, 1.0)

    # ── S: 세션 변수 ──
    state["message_count"] += 1
    elapsed = now - state["last_input_time"] if state["last_input_time"] > 0 else 10

    if elapsed < 3:
        S = 0.1
    elif elapsed < 15:
        S = 0.5
    elif elapsed < 120:
        S = 0.4
    else:
        S = 0.2

    if state["message_count"] > 15:
        S *= 0.6
    elif state["message_count"] > 10:
        S *= 0.8

    # ── M: 기억/메시지 변수 ──
    msg = message.strip()
    msg_len = len(msg)

    silence_triggers = [
        "ㅋ", "ㅎ", "ㅇㅇ", "ㅇㅋ", "ㄴㄴ", "ㅠ", "ㅜ",
        "응", "어", "그래", "알겠어", "오케이", "ㅇ",
        "굿", "ㄱㄱ", "ㅇㅇ", "ㅎㅎ", "ㅋㅋ",
    ]

    is_reaction = (
        msg_len <= 5 or
        msg in silence_triggers or
        all(c in "ㅋㅎㅠㅜ" for c in msg)
    )

    if is_reaction:
        M = 0.05
    elif msg_len <= 10:
        M = 0.3
    else:
        M = 0.5

    state["intent_history"].append(intent.upper())
    if len(state["intent_history"]) >= 3:
        last_3 = state["intent_history"][-3:]
        if len(set(last_3)) == 1:
            M *= 0.4

    top_kw = memory_flow.most_used_keyword(user_id)
    if top_kw and memory_flow.get_keyword_count(top_kw, user_id) >= 4:
        M *= 0.5

    # ── Env: 환경 변수 (KST 기준) ──
    from datetime import datetime, timezone, timedelta
    kst = datetime.now(timezone(timedelta(hours=9)))
    hour = kst.hour

    if 0 <= hour < 6:
        Env = 0.15
    elif 6 <= hour < 8:
        Env = 0.3
    elif 22 <= hour < 24:
        Env = 0.25
    else:
        Env = 0.5

    # ── C: 친밀도/의심 변수 ──
    avg_closeness = memory_flow.get_average_closeness(user_id)
    avg_doubt = memory_flow.get_average_doubt(user_id)
    blended_closeness = closeness * 0.7 + avg_closeness * 0.3
    blended_doubt = doubt * 0.7 + avg_doubt * 0.3

    C = blended_closeness * 0.6 - blended_doubt * 0.4
    C = max(0.0, min(1.0, C))

    # ── P(t) 가중합 ──
    w_E, w_S, w_M, w_Env, w_C = 0.25, 0.20, 0.25, 0.10, 0.20
    pt = w_E * E + w_S * S + w_M * M + w_Env * Env + w_C * C

    if state["message_count"] == 1:
        pt += 0.3

    if intent.upper() == "QUESTION":
        pt = max(pt, T)

    state["last_input_time"] = now
    state["tone_history"].append(tone.upper())

    return round(min(1.0, max(0.0, pt)), 3)


# ─── 모드 결정 (히스테리시스 + 재무장) ───
def decide_mode(pt: float, user_id: str = "default") -> str:
    now = time.time()
    state = _get_state(user_id)
    last = state["last_mode"]

    # 재무장
    if last == "L0" and (now - state["last_l0_time"]) < T_REARM:
        state["silence_count"] += 1
        return "L0"

    # 히스테리시스
    if last == "L2":
        if pt < T - DELTA_H / 2:
            if pt < T1 - DELTA_H / 2:
                mode = "L0"
            else:
                mode = "L1"
        else:
            mode = "L2"

    elif last == "L1":
        if pt >= T + DELTA_H / 2:
            mode = "L2"
        elif pt < T1 - DELTA_H / 2:
            mode = "L0"
        else:
            mode = "L1"

    elif last == "L0":
        if pt >= T + DELTA_H / 2:
            mode = "L2"
        elif pt >= T1 + DELTA_H / 2:
            mode = "L1"
        else:
            mode = "L0"

    else:
        if pt >= T:
            mode = "L2"
        elif pt >= T1:
            mode = "L1"
        else:
            mode = "L0"

    if mode == "L0" and last != "L0":
        state["last_l0_time"] = now

    if mode == "L0":
        state["silence_count"] += 1
    else:
        state["silence_count"] = 0

    state["last_mode"] = mode
    return mode


# ─── 메인 함수 ───
def evaluate(tone: str, intent: str, message: str,
             memory_count: int = 0,
             closeness: float = 0.5, doubt: float = 0.3,
             user_id: str = "default") -> dict:
    pt = compute_pt(tone, intent, message, memory_count,
                    closeness, doubt, user_id)
    mode = decide_mode(pt, user_id)

    return {
        "pt": pt,
        "mode": mode,
        "should_respond": mode in ("L1", "L2"),
        "silence": mode == "L0",
    }


# ─── 상태 조회 ───
def get_user_status(user_id: str = "default") -> dict:
    state = _get_state(user_id)
    return {
        "message_count": state["message_count"],
        "silence_count": state["silence_count"],
        "last_mode": state["last_mode"],
        "recent_tones": state["tone_history"][-5:],
        "recent_intents": state["intent_history"][-5:],
    }


# ─── 리셋 ───
def reset(user_id: str = None):
    if user_id:
        if user_id in _user_states:
            del _user_states[user_id]
        memory_flow.reset(user_id)
    else:
        _user_states.clear()
        memory_flow.reset_all()
