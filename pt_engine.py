"""
PtEngine — UNLIQ 출력 제어 엔진 v3
특허 기반: P(t) 판정값으로 L2(발화) / L1(저감) / L0(침묵) 자율 선택

핵심 원칙:
  - 침묵(L0)은 오류가 아닌 정상 기능 상태
  - 히스테리시스(δH)로 모드 플리커 방지
  - 재무장 시간(t_r)으로 L0→상위 전이 안정화
  - 짧은 입력, 리액션, 반복에는 침묵 경향

모드:
  L2 = 발화 (P(t) >= T)
  L1 = 저감 (T1 <= P(t) < T)
  L0 = 침묵 (P(t) < T1)

v3 변경사항:
  - 임계치 상향 (침묵 비율 증가)
  - 안전장치 최소화 (질문에만 L2 보장)
  - 히스테리시스 δH 적용
  - 재무장 시간 t_r 적용
  - Claude 침묵 위임 지원
"""

import time
import memory_flow

# ─── 임계치 설정 (특허 기반) ───
T = 0.60       # L2 임계치 (이상이면 발화)
T1 = 0.35      # L1 임계치 (이상이면 저감, 미만이면 침묵)
DELTA_H = 0.05  # 히스테리시스 폭
T_REARM = 10    # 재무장 시간 (초) — L0 진입 후 최소 대기

# ─── 상태 저장소 ───
_state = {
    "last_input_time": 0,
    "session_start": time.time(),
    "message_count": 0,
    "silence_count": 0,
    "last_mode": "L2",
    "last_l0_time": 0,        # L0 진입 시각 (재무장용)
    "tone_history": [],
    "intent_history": [],
}


# ─── P(t) 계산 ───
def compute_pt(tone: str, intent: str, message: str,
               memory_count: int = 0,
               closeness: float = 0.5, doubt: float = 0.3) -> float:
    """
    P(t) = w_E·E + w_S·S + w_M·M + w_Env·Env + w_C·C
    """
    now = time.time()

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

    # 감정 불안정 시 약간 상승
    if memory_flow.is_tone_shifting():
        E = min(E + 0.1, 1.0)

    # ── S: 세션 변수 ──
    _state["message_count"] += 1
    elapsed = now - _state["last_input_time"] if _state["last_input_time"] > 0 else 10

    if elapsed < 3:
        S = 0.1       # 연타 → 강한 침묵 경향
    elif elapsed < 15:
        S = 0.5       # 적당한 간격
    elif elapsed < 120:
        S = 0.4       # 조금 지남
    else:
        S = 0.2       # 매우 오래 지남 → 침묵

    # 15턴 이상 → 피로
    if _state["message_count"] > 15:
        S *= 0.6
    elif _state["message_count"] > 10:
        S *= 0.8

    # ── M: 기억/메시지 변수 ──
    msg = message.strip()
    msg_len = len(msg)

    # 짧은 리액션 → 침묵 경향 강화
    silence_triggers = [
        "ㅋ", "ㅎ", "ㅇㅇ", "ㅇㅋ", "ㄴㄴ", "ㅠ", "ㅜ",
        "응", "어", "그래", "알겠어", "오케이", "ㅇ",
        "굿", "ㄱㄱ", "ㅇㅇ", "ㅎㅎ", "ㅋㅋ",
    ]

    # 리액션성 메시지 판단
    is_reaction = (
        msg_len <= 5 or
        msg in silence_triggers or
        all(c in "ㅋㅎㅠㅜ" for c in msg)
    )

    if is_reaction:
        M = 0.05      # 리액션 → 거의 침묵
    elif msg_len <= 10:
        M = 0.3
    else:
        M = 0.5

    # 같은 intent 3번 반복 → 침묵
    _state["intent_history"].append(intent.upper())
    if len(_state["intent_history"]) >= 3:
        last_3 = _state["intent_history"][-3:]
        if len(set(last_3)) == 1:
            M *= 0.4

    # 같은 키워드 반복 → 침묵
    top_kw = memory_flow.most_used_keyword()
    if top_kw and memory_flow.get_keyword_count(top_kw) >= 4:
        M *= 0.5

    # ── Env: 환경 변수 (KST 기준) ──
    hour = (time.localtime().tm_hour + 9) % 24  # UTC→KST
    if 0 <= hour < 6:
        Env = 0.15    # 새벽 → 강한 침묵
    elif 6 <= hour < 8:
        Env = 0.3
    elif 22 <= hour < 24:
        Env = 0.25    # 밤 → 침묵 경향
    else:
        Env = 0.5

    # ── C: 친밀도/의심 변수 ──
    avg_closeness = memory_flow.get_average_closeness()
    avg_doubt = memory_flow.get_average_doubt()
    blended_closeness = closeness * 0.7 + avg_closeness * 0.3
    blended_doubt = doubt * 0.7 + avg_doubt * 0.3

    C = blended_closeness * 0.6 - blended_doubt * 0.4
    C = max(0.0, min(1.0, C))

    # ── P(t) 가중합 ──
    w_E, w_S, w_M, w_Env, w_C = 0.25, 0.20, 0.25, 0.10, 0.20
    pt = w_E * E + w_S * S + w_M * M + w_Env * Env + w_C * C

    # ── 세션 첫 메시지만 보너스 ──
    if _state["message_count"] == 1:
        pt += 0.3

    # ── 직접 질문에만 L2 보장 ──
    if intent.upper() == "QUESTION":
        pt = max(pt, T)

    _state["last_input_time"] = now
    _state["tone_history"].append(tone.upper())

    return round(min(1.0, max(0.0, pt)), 3)


# ─── 모드 결정 (히스테리시스 + 재무장 적용) ───
def decide_mode(pt: float) -> str:
    """
    특허 구조:
    - 상승 경로: P >= T + δH/2 → L2
    - 하강 경로: P < T - δH/2 → L1 이하
    - 재무장: L0 진입 후 t_r초 동안 L0 유지
    """
    now = time.time()
    last = _state["last_mode"]

    # ── 재무장 시간 체크 ──
    # L0 진입 후 T_REARM초 동안은 L0 유지
    if last == "L0" and (now - _state["last_l0_time"]) < T_REARM:
        _state["silence_count"] += 1
        return "L0"

    # ── 히스테리시스 적용 ──
    if last == "L2":
        # L2에서 내려가려면 T - δH/2 미만이어야
        if pt < T - DELTA_H / 2:
            if pt < T1 - DELTA_H / 2:
                mode = "L0"
            else:
                mode = "L1"
        else:
            mode = "L2"

    elif last == "L1":
        # L1에서 올라가려면 T + δH/2 이상
        if pt >= T + DELTA_H / 2:
            mode = "L2"
        # L1에서 내려가려면 T1 - δH/2 미만
        elif pt < T1 - DELTA_H / 2:
            mode = "L0"
        else:
            mode = "L1"

    elif last == "L0":
        # L0에서 올라가려면 T1 + δH/2 이상
        if pt >= T + DELTA_H / 2:
            mode = "L2"
        elif pt >= T1 + DELTA_H / 2:
            mode = "L1"
        else:
            mode = "L0"

    else:
        # 초기 상태
        if pt >= T:
            mode = "L2"
        elif pt >= T1:
            mode = "L1"
        else:
            mode = "L0"

    # ── L0 진입 시 재무장 시작 ──
    if mode == "L0" and last != "L0":
        _state["last_l0_time"] = now

    # ── 침묵 카운트 ──
    if mode == "L0":
        _state["silence_count"] += 1
    else:
        _state["silence_count"] = 0

    _state["last_mode"] = mode
    return mode


# ─── 메인 함수 ───
def evaluate(tone: str, intent: str, message: str,
             memory_count: int = 0,
             closeness: float = 0.5, doubt: float = 0.3) -> dict:
    """
    UNLIQ 판정: P(t) → 모드 결정 → 결과 반환
    """
    pt = compute_pt(tone, intent, message, memory_count, closeness, doubt)
    mode = decide_mode(pt)

    return {
        "pt": pt,
        "mode": mode,
        "should_respond": mode in ("L1", "L2"),
        "silence": mode == "L0",
    }


# ─── 세션 리셋 ───
def reset():
    _state["last_input_time"] = 0
    _state["session_start"] = time.time()
    _state["message_count"] = 0
    _state["silence_count"] = 0
    _state["last_mode"] = "L2"
    _state["last_l0_time"] = 0
    _state["tone_history"] = []
    _state["intent_history"] = []
    memory_flow.reset()
