"""
PtEngine — UNLIQ 출력 확률 제어 엔진
특허 기반: AI 출력 확률 함수 P(t)로 응답/축약/침묵을 자율 판단

모드:
  L2 = 정상 응답 (P(t) >= 0.6)
  L1 = 축약 응답 (0.3 <= P(t) < 0.6)
  L0 = 침묵     (P(t) < 0.3)
"""

import time
import random

# ─── 상태 저장소 ───
_state = {
    "last_input_time": 0,
    "session_start": time.time(),
    "message_count": 0,
    "silence_count": 0,
    "last_mode": "L2",
    "tone_history": [],
    "intent_history": [],
    "rearm_until": 0,  # 재무장 해제 시각
}

# ─── P(t) 계산 ───
def compute_pt(tone: str, intent: str, message: str, memory_count: int = 0) -> float:
    """
    P(t) = w_E * E + w_S * S + w_M * M + w_Env * Env

    E (감정 가중치): tone에 따라 결정
    S (세션 가중치): 대화 밀도, 반복성
    M (기억 가중치): 새로운 정보 여부
    Env (환경 가중치): 시간대 등
    """
    now = time.time()

    # ── E: 감정 변수 ──
    tone_weights = {
        "SAD": 0.8,       # 슬플 때는 응답 확률 높음 (위로)
        "CURIOUS": 0.7,   # 궁금할 때도 높음
        "GENTLE": 0.5,    # 부드러운 톤은 중간
        "FIRM": 0.4,      # 단호할 때는 낮춤
        "SARCASTIC": 0.3, # 비꼬는 톤이면 침묵 경향
        "AVOIDING": 0.2,  # 회피하면 침묵
        "NEUTRAL": 0.5,   # 중립
    }
    E = tone_weights.get(tone.upper(), 0.5)

    # ── S: 세션 변수 ──
    _state["message_count"] += 1
    elapsed = now - _state["last_input_time"] if _state["last_input_time"] > 0 else 10

    # 빠른 연타 → 침묵 경향 (3초 이내 연타면 S 하락)
    if elapsed < 3:
        S = 0.2
    # 적당한 간격 (3~30초) → 정상
    elif elapsed < 30:
        S = 0.6
    # 오래 지남 (30초~5분) → 먼저 말할 수도
    elif elapsed < 300:
        S = 0.7
    # 매우 오래 지남 (5분+) → 침묵 유지
    else:
        S = 0.3

    # 너무 많은 대화 (20턴 이상) → 피로 → 침묵 경향
    if _state["message_count"] > 20:
        S *= 0.7

    # ── M: 기억 변수 ──
    # 짧은 메시지 or 의미없는 입력 → 침묵 경향
    msg_len = len(message.strip())
    if msg_len <= 2:
        M = 0.2  # "ㅋ", "?" 등
    elif msg_len <= 6:
        M = 0.4  # "hi", "안녕" 등
    else:
        M = 0.6  # 의미 있는 입력

    # 새로운 intent(QUESTION, DECLARE)는 M 상승
    if intent.upper() in ("QUESTION", "DECLARE"):
        M = min(1.0, M + 0.2)

    # 같은 intent 3번 반복 → 침묵 경향
    _state["intent_history"].append(intent.upper())
    if len(_state["intent_history"]) >= 3:
        last_3 = _state["intent_history"][-3:]
        if len(set(last_3)) == 1:
            M *= 0.5

    # ── Env: 환경 변수 ──
    # 간단하게 시간대만 반영
    hour = time.localtime().tm_hour
    if 0 <= hour < 6:
        Env = 0.3  # 새벽 → 침묵 경향
    elif 6 <= hour < 9:
        Env = 0.5  # 아침
    elif 22 <= hour < 24:
        Env = 0.4  # 밤늦게
    else:
        Env = 0.6  # 낮

    # ── P(t) 가중합 ──
    w_E, w_S, w_M, w_Env = 0.35, 0.25, 0.25, 0.15
    pt = w_E * E + w_S * S + w_M * M + w_Env * Env

    # ── 재무장 체크 ──
    # 침묵 직후에는 재무장 시간 동안 응답 확률 강제 상승
    if now < _state["rearm_until"]:
        pt = max(pt, 0.7)

    # ── 연속 침묵 방지 ──
    # 3번 연속 침묵이면 강제 응답
    if _state["silence_count"] >= 3:
        pt = max(pt, 0.8)

    _state["last_input_time"] = now
    _state["tone_history"].append(tone.upper())

    return round(min(1.0, max(0.0, pt)), 3)


# ─── 모드 결정 ───
def decide_mode(pt: float) -> str:
    """P(t) → L0/L1/L2"""
    if pt < 0.3:
        mode = "L0"  # 침묵
    elif pt < 0.6:
        mode = "L1"  # 축약
    else:
        mode = "L2"  # 정상

    # 침묵 카운터 관리
    if mode == "L0":
        _state["silence_count"] += 1
        # 침묵 후 재무장: 15초간 응답 확률 상승
        _state["rearm_until"] = time.time() + 15
    else:
        _state["silence_count"] = 0

    _state["last_mode"] = mode
    return mode


# ─── 메인 함수 ───
def evaluate(tone: str, intent: str, message: str, memory_count: int = 0) -> dict:
    """
    입력을 받아 침묵 여부를 판단하고 모드를 반환

    Returns:
        {
            "pt": 0.432,
            "mode": "L1",
            "should_respond": True,
            "silence": False
        }
    """
    pt = compute_pt(tone, intent, message, memory_count)
    mode = decide_mode(pt)

    return {
        "pt": pt,
        "mode": mode,
        "should_respond": mode in ("L1", "L2"),
        "silence": mode == "L0",
    }


# ─── 침묵 시 응답 생성 ───
SILENCE_RESPONSES = [
    "",       # 완전 침묵
    "...",    # 말줄임
    None,     # null (앱에서 무시)
]

L1_PREFIXES = [
    "",       # 축약 응답에는 접두사 없음
]

def get_silence_response() -> str:
    """L0 모드일 때 반환할 응답"""
    return random.choice(SILENCE_RESPONSES)


# ─── 세션 리셋 ───
def reset():
    """세션 초기화"""
    _state["last_input_time"] = 0
    _state["session_start"] = time.time()
    _state["message_count"] = 0
    _state["silence_count"] = 0
    _state["last_mode"] = "L2"
    _state["tone_history"] = []
    _state["intent_history"] = []
    _state["rearm_until"] = 0
