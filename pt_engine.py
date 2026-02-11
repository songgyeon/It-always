"""
PtEngine — UNLIQ 출력 제어 엔진 v6
특허 기반: P(t) 판정값으로 L2(발화) / L1(저감) / L0(침묵) 자율 선택

v6 변경사항 (v5 → v6):
  - Art(외부 감응), Rsrc(자원 상태) 변수 추가 → 특허 5.1/5.3 완전 반영
  - 지수평활화(EMA) 적용 → 특허 5.3 "평활화 후 0~1 범위로 제한"
  - 변화율 제한(rate limiter) → 특허 7.2 "급변/플리커 방지"
  - 리듬 생성부 R(t) → 특허 5.2/5.4 "내적 리듬 신호"
  - 대화 흐름 인식(flow context) → is_reaction의 맥락 기반 재설계
  - crisis_reply 제거 → Q의 톤 유지
"""

import math
import time
import memory_flow
import online_learning
import policy_negotiation
import group_sync
import api_r
import ethics_check
import crypto_log

# ─── 기본 임계치 (채팅 모델: 대화가 기본, 침묵은 예외) ───
T = 0.50
T1 = 0.25
DELTA_H = 0.05
T_REARM = 10

# ─── 평활화·변화율 기본값 ───
EMA_ALPHA = 0.4          # 평활화 계수 (0에 가까울수록 이전 pt 영향 큼)
MAX_DELTA_PT = 0.15      # 1틱당 최대 변화량

# ─── 리듬 기본값 ───
RHYTHM_TAU_BASE = 60.0   # 기본 주기 (초)
RHYTHM_A_BASE = 0.05     # 기본 진폭 (pt에 더해지는 최대 보정량)
RHYTHM_LP_ALPHA = 0.1    # 리듬 파라미터 저역통과 계수

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
            # ── v6 추가 ──
            "prev_pt": None,           # 이전 평활화된 pt (EMA용)
            "last_q_action": None,     # 직전 Q의 발화 타입: "question", "long", "short", "silence"
            "last_q_message_len": 0,   # 직전 Q 발화 길이
            "consecutive_short": 0,    # 연속 짧은 입력 횟수
            # ── 리듬 상태 ──
            "rhythm_A": RHYTHM_A_BASE,
            "rhythm_tau": RHYTHM_TAU_BASE,
            "rhythm_phase": 0.0,
            "rhythm_last_time": time.time(),
        }
    return _user_states[user_id]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 리듬 생성부 (특허 5.2, 5.4)
# R(t) = A(t) · sin(ψ(t)),  ψ'(t) = 2π / τ(t)
# A, τ는 감정·기억 안정성에 따라 저역통과로 갱신
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _update_rhythm(user_id: str, E: float, M: float) -> float:
    """
    리듬 신호를 갱신하고 현재 R(t) 값을 반환.
    
    - E가 높으면(감정 활성) → A 증가, τ 감소 (빠른 리듬)
    - M이 낮으면(기억/맥락 약함) → A 감소 (조용한 리듬)
    - 반환값 범위: [-A, +A] → pt 보정에 사용
    """
    state = _get_state(user_id)
    now = time.time()
    dt = now - state["rhythm_last_time"]
    if dt <= 0:
        dt = 0.1

    # 목표 A, τ 계산
    target_A = RHYTHM_A_BASE + (E * 0.03) + (M * 0.02)
    target_A = min(target_A, 0.12)  # 리듬이 pt를 지배하지 않도록 상한

    target_tau = RHYTHM_TAU_BASE * (1.0 - E * 0.3)  # 감정 활성 → 주기 짧아짐
    target_tau = max(target_tau, 15.0)  # 최소 주기 15초

    # 1차 저역통과 갱신 (특허: "A, τ를 1차 저역통과로 갱신")
    alpha = RHYTHM_LP_ALPHA
    state["rhythm_A"] = state["rhythm_A"] + alpha * (target_A - state["rhythm_A"])
    state["rhythm_tau"] = state["rhythm_tau"] + alpha * (target_tau - state["rhythm_tau"])

    # 위상 전진
    phase_increment = (2 * math.pi / state["rhythm_tau"]) * dt
    state["rhythm_phase"] = (state["rhythm_phase"] + phase_increment) % (2 * math.pi)
    state["rhythm_last_time"] = now

    # R(t) = A(t) · sin(ψ(t))
    R = state["rhythm_A"] * math.sin(state["rhythm_phase"])
    return R


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 지수평활화 + 변화율 제한 (특허 5.3, 7.2)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _smooth_and_limit(raw_pt: float, user_id: str) -> float:
    """
    1) EMA 평활화: pt = α * raw + (1-α) * prev
    2) 변화율 제한: |pt - prev| ≤ MAX_DELTA_PT
    3) [0, 1] 클리핑
    """
    state = _get_state(user_id)
    prev = state["prev_pt"]

    if prev is None:
        # 첫 메시지: 평활화 없이 그대로
        smoothed = raw_pt
    else:
        # EMA
        smoothed = EMA_ALPHA * raw_pt + (1.0 - EMA_ALPHA) * prev

        # 변화율 제한
        delta = smoothed - prev
        if abs(delta) > MAX_DELTA_PT:
            smoothed = prev + MAX_DELTA_PT * (1.0 if delta > 0 else -1.0)

    smoothed = max(0.0, min(1.0, smoothed))
    state["prev_pt"] = smoothed
    return smoothed


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 대화 흐름 인식 (v6 신규)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _flow_context_modifier(message: str, user_id: str) -> float:
    """
    직전 Q의 행동과 현재 입력의 관계를 보고 M 보정값을 반환.
    
    - Q가 질문했는데 짧은 답이 왔으면 → 리액션이 아니라 대답 (M을 깎지 않음)
    - Q가 침묵했는데 다시 말 걸면 → 재접근 시도 (M 보정 +)
    - 연속 짧은 입력이 3회 이상 → 진짜 끝맺음 (M 보정 -)
    """
    state = _get_state(user_id)
    last_q = state["last_q_action"]
    modifier = 0.0

    msg = message.strip()
    is_short = len(msg) <= 5

    if is_short:
        state["consecutive_short"] += 1
    else:
        state["consecutive_short"] = 0

    # Q가 질문한 뒤의 짧은 응답 → 대답이지 리액션이 아님
    if last_q == "question" and is_short:
        modifier += 0.15

    # Q가 긴 발화를 한 뒤의 짧은 응답 → 수긍/리액션일 수 있음
    elif last_q == "long" and is_short:
        modifier += 0.05  # 약간만 보정

    # Q가 침묵한 뒤 다시 말 걸기 → 재접근
    elif last_q == "silence":
        modifier += 0.10

    # 연속 짧은 입력 3회 이상 → 진짜 끝맺음 분위기
    if state["consecutive_short"] >= 3:
        modifier -= 0.10

    return modifier


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# P(t) 계산 (v6: 7변수 + 리듬 + 평활화 + 변화율 제한)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def compute_pt(tone: str, intent: str, message: str,
               memory_count: int = 0,
               closeness: float = 0.5, doubt: float = 0.3,
               art: float = 0.3,       # v6: 외부 감응
               rsrc: float = 1.0,      # v6: 자원 상태 (1.0 = 정상)
               user_id: str = "default") -> float:
    now = time.time()
    state = _get_state(user_id)

    # ── 동적 파라미터 로드 (온라인 학습 → 정책 반영) ──
    params = online_learning.get_params(user_id)
    params = policy_negotiation.apply_to_params(user_id, params)

    w_E = params.get("w_E", 0.20)
    w_S = params.get("w_S", 0.15)
    w_M = params.get("w_M", 0.20)
    w_Env = params.get("w_Env", 0.10)
    w_C = params.get("w_C", 0.15)
    w_Art = params.get("w_Art", 0.10)   # v6
    w_R = params.get("w_R", 0.10)       # v6

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

    # ── M: 기억/메시지 변수 (v6: 흐름 인식 적용) ──
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

    # v6: 흐름 컨텍스트 보정 (is_reaction이어도 맥락에 따라 M 회복)
    flow_mod = _flow_context_modifier(message, user_id)
    M = max(0.0, min(1.0, M + flow_mod))

    # 의도 반복 감쇠
    state["intent_history"].append(intent.upper())
    if len(state["intent_history"]) >= 3:
        last_3 = state["intent_history"][-3:]
        if len(set(last_3)) == 1:
            M *= 0.4

    # 키워드 반복 감쇠
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

    # ── Art: 외부 감응 변수 (v6 신규, 특허 5.1) ──
    # art 값은 외부에서 주입 (음악/활동/문화적 자극 감지)
    # 0.0 = 무자극, 1.0 = 강한 정서적 자극
    Art = max(0.0, min(1.0, art))

    # ── Rsrc: 자원 상태 변수 (v6 신규, 특허 5.1) ──
    # 1.0 = 정상, 0.0 = 자원 고갈
    # 자원이 부족하면 발화 부담 → pt 하락 유도
    Rsrc = max(0.0, min(1.0, rsrc))

    # ── C: 친밀도/의심 변수 ──
    avg_closeness = memory_flow.get_average_closeness(user_id)
    avg_doubt = memory_flow.get_average_doubt(user_id)
    blended_closeness = closeness * 0.7 + avg_closeness * 0.3
    blended_doubt = doubt * 0.7 + avg_doubt * 0.3

    C = blended_closeness * 0.6 - blended_doubt * 0.4
    C = max(0.0, min(1.0, C))

    # ── 리듬 생성 (v6, 특허 5.2/5.4) ──
    R = _update_rhythm(user_id, E, M)

    # ── P(t) 가중합 (v6: 7변수, 특허 5.3) ──
    raw_pt = (w_E * E + w_S * S + w_M * M + w_Env * Env
              + w_Art * Art + w_R * Rsrc + w_C * C)

    # 리듬 보정 (보조 입력)
    raw_pt += R

    # 첫 메시지 부스트
    if state["message_count"] == 1:
        raw_pt += 0.3

    # 사용자 존재 감지: Q가 침묵 중인데 계속 말 걸면
    if state["last_mode"] == "L0":
        raw_pt += 0.08 * min(state["silence_count"], 4)

    # 질문에는 반드시 응답
    if intent.upper() == "QUESTION":
        raw_pt = max(raw_pt, params.get("T", T))

    # 집단 동기화 수정자
    collective = group_sync.get_collective_modifier()
    raw_pt += collective["pt_offset"]

    # [0, 1] 1차 클리핑
    raw_pt = max(0.0, min(1.0, raw_pt))

    # ── 지수평활화 + 변화율 제한 (v6, 특허 5.3 + 7.2) ──
    pt = _smooth_and_limit(raw_pt, user_id)

    # 상태 갱신
    state["last_input_time"] = now
    state["tone_history"].append(tone.upper())

    return round(pt, 3)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 모드 결정 (v5 유지, 동적 임계치)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def decide_mode(pt: float, user_id: str = "default") -> str:
    now = time.time()
    state = _get_state(user_id)
    last = state["last_mode"]

    # 동적 임계치
    params = online_learning.get_params(user_id)
    params = policy_negotiation.apply_to_params(user_id, params)
    t = params.get("T", T)
    t1 = params.get("T1", T1)

    # 톤 시프트 → 히스테리시스 리셋 (Q가 다시 말할 이유)
    if last == "L0" and memory_flow.is_tone_shifting(user_id):
        state["last_mode"] = "L1"
        last = "L1"

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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Q 발화 후 상태 기록 (v6 신규)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def record_q_action(user_id: str, q_message: str, mode: str):
    """
    Q가 발화(또는 침묵)한 뒤 호출.
    다음 턴의 흐름 인식에 사용.
    """
    state = _get_state(user_id)

    if mode == "L0":
        state["last_q_action"] = "silence"
        state["last_q_message_len"] = 0
    else:
        msg_len = len(q_message.strip()) if q_message else 0
        state["last_q_message_len"] = msg_len

        if q_message and q_message.strip().endswith("?"):
            state["last_q_action"] = "question"
        elif msg_len > 50:
            state["last_q_action"] = "long"
        else:
            state["last_q_action"] = "short"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인 함수 (v6: crisis_reply 제거, Art/Rsrc 추가)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def evaluate(tone: str, intent: str, message: str,
             memory_count: int = 0,
             closeness: float = 0.5, doubt: float = 0.3,
             art: float = 0.3,
             rsrc: float = 1.0,
             user_id: str = "default") -> dict:

    # ── 1. 윤리 체크 (입력) ──
    input_ethics = ethics_check.check_input(message)

    if input_ethics.action == "crisis_response":
        # v6: crisis_reply 제거. L2 강제 + crisis 플래그만 전달.
        # Q가 뭐라고 말할지는 프롬프트가 결정.
        gate = api_r.generate_gate_status(
            "L2", 1.0, user_id,
            policy=policy_negotiation.get_policy(user_id),
        )
        group_sync.record_interaction(user_id, 1.0, "L2")
        group_sync.broadcast_event(user_id, "crisis")

        return {
            "pt": 1.0,
            "mode": "L2",
            "should_respond": True,
            "silence": False,
            "crisis": True,
            "ethics": input_ethics.to_dict(),
            "gate_status": gate,
            "proof_token": None,
        }

    # ── 2. P(t) 계산 (v6: 7변수 + 리듬 + 평활화 + 변화율 제한) ──
    pt = compute_pt(tone, intent, message, memory_count,
                    closeness, doubt, art, rsrc, user_id)

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
        f"pt={pt} mode={mode} tone={tone} intent={intent} art={art} rsrc={rsrc}")

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
        "crisis": False,
        "ethics": input_ethics.to_dict(),
        "gate_status": gate,
        "proof_token": proof,
        "max_tokens_override": ctx.get("max_tokens_override"),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 상태 조회
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_user_status(user_id: str = "default") -> dict:
    state = _get_state(user_id)
    return {
        "message_count": state["message_count"],
        "silence_count": state["silence_count"],
        "last_mode": state["last_mode"],
        "recent_tones": state["tone_history"][-5:],
        "recent_intents": state["intent_history"][-5:],
        "prev_pt": state["prev_pt"],
        "last_q_action": state["last_q_action"],
        "consecutive_short": state["consecutive_short"],
        "rhythm_A": round(state["rhythm_A"], 4),
        "rhythm_tau": round(state["rhythm_tau"], 2),
        "params": online_learning.get_params(user_id),
        "policy": policy_negotiation.get_policy(user_id),
        "collective": group_sync.get_collective_modifier(),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 리셋
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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
