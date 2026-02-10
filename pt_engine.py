"""
PtEngine — UNLIQ 출력 제어 엔진 v5
특허 기반: P(t) 판정값으로 L2(발화) / L1(저감) / L0(침묵) 자율 선택

v5 변경사항:
  - 온라인 학습 연동 (임계치/가중치 동적 조정)
  - 사용자 정책 반영 (policy_negotiation)
  - 집단 동기화 수정자 (group_sync)
  - 윤리 체크 연동 (ethics_check)
  - API-R 게이트 상태값 생성 (api_r)
"""

import time
import memory_flow
import online_learning
import policy_negotiation
import group_sync
import api_r
import ethics_check
import crypto_log

# ─── 기본 임계치 (온라인 학습이 덮어쓸 수 있음) ───
T = 0.50
T1 = 0.25
DELTA_H = 0.05
T_REARM = 5

# ─── 사용자별 상태 저장소 ───
_user_states = {}


def _get_state(user_id: str) -> dict:
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


# ─── P(t) 계산 (v5: 동적 파라미터) ───
def compute_pt(tone: str, intent: str, message: str,
               memory_count: int = 0,
               closeness: float = 0.5, doubt: float = 0.3,
               user_id: str = "default") -> float:
    now = time.time()
    state = _get_state(user_id)

    # ── 동적 파라미터 로드 (온라인 학습 → 정책 반영) ──
    params = online_learning.get_params(user_id)
    params = policy_negotiation.apply_to_params(user_id, params)

    w_E = params["w_E"]
    w_S = params["w_S"]
    w_M = params["w_M"]
    w_Env = params["w_Env"]
    w_C = params["w_C"]

    # ── E: 감정 변수 ──
    tone_weights = {
        "SAD": 0.7, "CURIOUS": 0.6, "GENTLE": 0.4,
        "FIRM": 0.3, "SARCASTIC": 0.2, "AVOIDING": 0.15, "NEUTRAL": 0.4,
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

    # ── Env: 환경 변수 (KST) ──
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

    # 정책 야간 모드
    policy = policy_negotiation.get_policy(user_id)
    if policy.get("night_mode") and (0 <= hour < 6 or 22 <= hour < 24):
        Env *= 0.5

    # ── C: 친밀도/의심 변수 ──
    avg_closeness = memory_flow.get_average_closeness(user_id)
    avg_doubt = memory_flow.get_average_doubt(user_id)
    blended_closeness = closeness * 0.7 + avg_closeness * 0.3
    blended_doubt = doubt * 0.7 + avg_doubt * 0.3

    C = blended_closeness * 0.6 - blended_doubt * 0.4
    C = max(0.0, min(1.0, C))

    # ── P(t) 가중합 ──
    pt = w_E * E + w_S * S + w_M * M + w_Env * Env + w_C * C

    if state["message_count"] == 1:
        pt += 0.3

    if intent.upper() == "QUESTION":
        pt = max(pt, params["T"] + DELTA_H)  # 히스테리시스도 넘도록

    # ── 집단 동기화 수정자 ──
    collective = group_sync.get_collective_modifier()
    pt += collective["pt_offset"]

    state["last_input_time"] = now
    state["tone_history"].append(tone.upper())

    return round(min(1.0, max(0.0, pt)), 3)


# ─── 모드 결정 (v5: 동적 임계치) ───
def decide_mode(pt: float, user_id: str = "default") -> str:
    now = time.time()
    state = _get_state(user_id)
    last = state["last_mode"]

    # 동적 임계치
    params = online_learning.get_params(user_id)
    params = policy_negotiation.apply_to_params(user_id, params)
    t = params["T"]
    t1 = params["T1"]

    # 정책 cooldown 오버라이드
    policy = policy_negotiation.get_policy(user_id)
    rearm = policy.get("cooldown_override") or T_REARM

    # 재무장
    if last == "L0" and (now - state["last_l0_time"]) < rearm:
        state["silence_count"] += 1
        return "L0"

    # 히스테리시스
    if last == "L2":
        if pt < t - DELTA_H / 2:
            mode = "L0" if pt < t1 - DELTA_H / 2 else "L1"
        else:
            mode = "L2"
    elif last == "L1":
        if pt >= t + DELTA_H / 2:
            mode = "L2"
        elif pt < t1 - DELTA_H / 2:
            mode = "L0"
        else:
            mode = "L1"
    elif last == "L0":
        if pt >= t + DELTA_H / 2:
            mode = "L2"
        elif pt >= t1 + DELTA_H / 2:
            mode = "L1"
        else:
            mode = "L0"
    else:
        if pt >= t:
            mode = "L2"
        elif pt >= t1:
            mode = "L1"
        else:
            mode = "L0"

    # 집단 침묵 합의: L1 → L0 격하
    if mode == "L1" and group_sync.should_amplify_silence():
        mode = "L0"

    if mode == "L0" and last != "L0":
        state["last_l0_time"] = now
    if mode == "L0":
        state["silence_count"] += 1
    else:
        state["silence_count"] = 0

    state["last_mode"] = mode
    return mode


# ─── 메인 함수 (v5: 풀 파이프라인) ───
def evaluate(tone: str, intent: str, message: str,
             memory_count: int = 0,
             closeness: float = 0.5, doubt: float = 0.3,
             user_id: str = "default") -> dict:

    # ── 1. 윤리 체크 (입력) ──
    input_ethics = ethics_check.check_input(message)

    if input_ethics.action == "crisis_response":
        crisis_reply = ethics_check.get_crisis_response()
        gate = api_r.generate_gate_status(
            "L2", 1.0, user_id,
            policy=policy_negotiation.get_policy(user_id),
        )
        proof = None
        group_sync.record_interaction(user_id, 1.0, "L2")
        group_sync.broadcast_event(user_id, "crisis")

        return {
            "pt": 1.0,
            "mode": "L2",
            "should_respond": True,
            "silence": False,
            "crisis": True,
            "crisis_reply": crisis_reply,
            "ethics": input_ethics.to_dict(),
            "gate_status": gate,
            "proof_token": None,
        }

    # ── 2. P(t) 계산 ──
    pt = compute_pt(tone, intent, message, memory_count,
                    closeness, doubt, user_id)

    # ── 3. 모드 결정 ──
    mode = decide_mode(pt, user_id)

    # ── 4. 맥락 수정자 (정책) ──
    ctx = policy_negotiation.get_context_modifier(user_id)
    if ctx.get("force_l1") and mode == "L2":
        mode = "L1"

    # ── 5. 집단 동기화 기록 ──
    group_sync.record_interaction(user_id, pt, mode)

    # ── 6. 암호화 로그 ──
    crypto_log.encrypt_and_store(user_id, "system",
        f"pt={pt} mode={mode} tone={tone} intent={intent}")

    # ── 7. API-R 게이트 상태값 ──
    policy = policy_negotiation.get_policy(user_id)
    gate = api_r.generate_gate_status(
        mode, pt, user_id, policy=policy,
    )

    # ── 8. 증명 토큰 (L0일 때만) ──
    proof = None
    if mode == "L0":
        proof = api_r.generate_proof_token(user_id, mode, pt)

    return {
        "pt": pt,
        "mode": mode,
        "should_respond": mode in ("L1", "L2"),
        "silence": mode == "L0",
        "ethics": input_ethics.to_dict(),
        "gate_status": gate,
        "proof_token": proof,
        "max_tokens_override": ctx.get("max_tokens_override"),
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
        "params": online_learning.get_params(user_id),
        "policy": policy_negotiation.get_policy(user_id),
        "collective": group_sync.get_collective_modifier(),
    }


# ─── 리셋 ───
def reset(user_id: str = None):
    if user_id:
        if user_id in _user_states:
            del _user_states[user_id]
        memory_flow.reset(user_id)
        online_learning.reset(user_id)
        policy_negotiation.reset(user_id)
        api_r.reset_counter(user_id)
        crypto_log.reset(user_id)
    else:
        _user_states.clear()
        memory_flow.reset_all()
        online_learning.reset()
        policy_negotiation.reset()
        api_r.reset_counter()
        group_sync.reset()
        crypto_log.reset()
