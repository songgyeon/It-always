"""
PtEngine — UNLIQ 출력 확률 제어 엔진
특허 기반: AI 출력 확률 함수 P(t)로 응답/축약/침묵을 자율 판단

모드:
  L2 = 정상 응답 (P(t) >= 0.6)
  L1 = 축약 응답 (0.3 <= P(t) < 0.6)
  L0 = 침묵     (P(t) < 0.3)

v2 업그레이드:
  - closeness/doubt 반영
  - memory_flow 톤 흐름 통합
  - 감정 불안정 시 응답 확률 보정
"""

import time
import random
import memory_flow

# ─── 상태 저장소 ───
_state = {
    "last_input_time": 0,
    "session_start": time.time(),
    "message_count": 0,
    "silence_count": 0,
    "last_mode": "L2",
    "tone_history": [],
    "intent_history": [],
    "rearm_until": 0,
}

# ─── P(t) 계산 ───
def compute_pt(tone: str, intent: str, message: str,
               memory_count: int = 0,
               closeness: float = 0.5, doubt: float = 0.3) -> float:
    """
    P(t) = w_E * E + w_S * S + w_M * M + w_Env * Env + w_C * C

    E (감정 가중치): tone에 따라 결정
    S (세션 가중치): 대화 밀도, 반복성
    M (기억 가중치): 새로운 정보 여부
    Env (환경 가중치): 시간대 등
    C (친밀도/의심 가중치): closeness와 doubt에 따라 결정 ← NEW
    """
    now = time.time()

    # ── E: 감정 변수 ──
    tone_weights = {
        "SAD": 0.8,
        "CURIOUS": 0.7,
        "GENTLE": 0.5,
        "FIRM": 0.4,
        "SARCASTIC": 0.3,
        "AVOIDING": 0.2,
        "NEUTRAL": 0.5,
    }
    E = tone_weights.get(tone.upper(), 0.5)

    # ── memory_flow 보정: 감정 불안정 시 응답 확률 상승 ──
    if memory_flow.is_tone_shifting():
        E = min(E + 0.15, 1.0)  # 감정 변동이 크면 Q가 더 주의를 기울임

    # 최근에 SAD가 있었으면 지속적 관심
    if memory_flow.has_recent_tone("SAD") and tone.upper() != "SAD":
        E = min(E + 0.1, 1.0)

    # ── S: 세션 변수 ──
    _state["message_count"] += 1
    elapsed = now - _state["last_input_time"] if _state["last_input_time"] > 0 else 10

    if elapsed < 3:
        S = 0.2       # 연타 → 침묵 경향
    elif elapsed < 30:
        S = 0.6       # 적당한 간격
    elif elapsed < 300:
        S = 0.7       # 오래 지남 → 먼저 말할 수도
    else:
        S = 0.3       # 매우 오래 지남 → 침묵

    # 20턴 이상 → 피로
    if _state["message_count"] > 20:
        S *= 0.7

    # ── M: 기억 변수 ──
    msg_len = len(message.strip())
    if msg_len <= 2:
        M = 0.2
    elif msg_len <= 6:
        M = 0.4
    else:
        M = 0.6

    if intent.upper() in ("QUESTION", "DECLARE"):
        M = min(1.0, M + 0.2)

    # 같은 intent 3번 반복 → 침묵 경향
    _state["intent_history"].append(intent.upper())
    if len(_state["intent_history"]) >= 3:
        last_3 = _state["intent_history"][-3:]
        if len(set(last_3)) == 1:
            M *= 0.5

    # memory_flow: 같은 키워드 반복 사용 → M 하락 (반복 대화 감지)
    top_kw = memory_flow.most_used_keyword()
    if top_kw and memory_flow.get_keyword_count(top_kw) >= 5:
        M *= 0.7

    # ── Env: 환경 변수 ──
    hour = time.localtime().tm_hour
    if 0 <= hour < 6:
        Env = 0.3
    elif 6 <= hour < 9:
        Env = 0.5
    elif 22 <= hour < 24:
        Env = 0.4
    else:
        Env = 0.6

    # ── C: 친밀도/의심 변수 (NEW) ──
    # closeness가 높으면 → 적극 응답
    # doubt가 높으면 → 축약/침묵 경향
    # memory_flow 평균과 혼합하여 세션 전체 흐름 반영
    avg_closeness = memory_flow.get_average_closeness()
    avg_doubt = memory_flow.get_average_doubt()

    # 현재 값과 평균의 가중 평균 (현재 0.7, 평균 0.3)
    blended_closeness = closeness * 0.7 + avg_closeness * 0.3
    blended_doubt = doubt * 0.7 + avg_doubt * 0.3

    C = blended_closeness * 0.7 - blended_doubt * 0.3
    C = max(0.0, min(1.0, C))

    # ── P(t) 가중합 ──
    w_E, w_S, w_M, w_Env, w_C = 0.25, 0.20, 0.20, 0.10, 0.25
    pt = w_E * E + w_S * S + w_M * M + w_Env * Env + w_C * C

    # ── 세션 초반 보너스 ──
    if _state["message_count"] <= 5:
        pt += 0.2

    # ── 질문에는 반드시 답해야 함 ──
    if intent.upper() == "QUESTION":
        pt = max(pt, 0.6)

    # ── 슬픔/위로 필요 시 반드시 응답 ──
    if tone.upper() == "SAD":
        pt = max(pt, 0.7)

    # ── 높은 친밀도면 응답 경향 ──
    if blended_closeness >= 0.8:
        pt = max(pt, 0.5)

    # ── 재무장 체크 ──
    if now < _state["rearm_until"]:
        pt = max(pt, 0.7)

    # ── 연속 침묵 방지 ──
    if _state["silence_count"] >= 3:
        pt = max(pt, 0.8)

    # ── 감정 불안정 + 높은 doubt → L1 이상 보장 ──
    if memory_flow.is_tone_shifting() and blended_doubt >= 0.5:
        pt = max(pt, 0.4)

    _state["last_input_time"] = now
    _state["tone_history"].append(tone.upper())

    return round(min(1.0, max(0.0, pt)), 3)


# ─── 모드 결정 ───
def decide_mode(pt: float) -> str:
    if pt < 0.3:
        mode = "L0"
    elif pt < 0.6:
        mode = "L1"
    else:
        mode = "L2"

    if mode == "L0":
        _state["silence_count"] += 1
        _state["rearm_until"] = time.time() + 15
    else:
        _state["silence_count"] = 0

    _state["last_mode"] = mode
    return mode


# ─── 메인 함수 ───
def evaluate(tone: str, intent: str, message: str,
             memory_count: int = 0,
             closeness: float = 0.5, doubt: float = 0.3) -> dict:
    """
    입력을 받아 침묵 여부를 판단하고 모드를 반환.
    v2: closeness/doubt 파라미터 추가.
    """
    pt = compute_pt(tone, intent, message, memory_count, closeness, doubt)
    mode = decide_mode(pt)

    return {
        "pt": pt,
        "mode": mode,
        "should_respond": mode in ("L1", "L2"),
        "silence": mode == "L0",
    }


# ─── 침묵 시 응답 생성 ───
SILENCE_RESPONSES = [
    "",
    "...",
    None,
]

def get_silence_response() -> str:
    return random.choice(SILENCE_RESPONSES)


# ─── 세션 리셋 ───
def reset():
    _state["last_input_time"] = 0
    _state["session_start"] = time.time()
    _state["message_count"] = 0
    _state["silence_count"] = 0
    _state["last_mode"] = "L2"
    _state["tone_history"] = []
    _state["intent_history"] = []
    _state["rearm_until"] = 0
    memory_flow.reset()
