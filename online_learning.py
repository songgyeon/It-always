"""
Online Learning Module — UNLIQ 특허 온라인 학습

특허 명세서:
  "저학습률·경계 투영·발산 롤백·냉각 기간을 포함하는
   온라인 학습 모듈로 임계치와 가중치를 안정 보정한다."

구현:
  - 사용자 피드백(명시적/암묵적) 기반 임계치(T, T1) 및 가중치(w_E 등) 보정
  - 저학습률 (alpha = 0.01)
  - 경계 투영 (min/max 클램핑)
  - 발산 롤백 (변화량 > delta_max이면 이전 값 복원)
  - 냉각 기간 (cooldown: 연속 업데이트 사이 최소 간격)
"""

import time
import copy
from threading import Lock

# ─── 기본 파라미터 ───
DEFAULT_PARAMS = {
    "T": 0.50,           # L2 임계치 (채팅 모델: 대화하되 침묵할 줄 아는)
    "T1": 0.25,          # L1 임계치 (침묵은 자연스러운 선택)
    "w_E": 0.25,         # 감정 가중치
    "w_S": 0.20,         # 세션 가중치
    "w_M": 0.25,         # 기억 가중치
    "w_Env": 0.10,       # 환경 가중치
    "w_C": 0.20,         # 친밀도 가중치
}

# ─── 학습 하이퍼파라미터 ───
ALPHA = 0.01             # 저학습률
DELTA_MAX = 0.05         # 발산 롤백 임계
COOLDOWN = 60            # 냉각 기간 (초)
BOUNDS = {
    "T":     (0.25, 0.70),
    "T1":    (0.05, 0.35),
    "w_E":   (0.10, 0.40),
    "w_S":   (0.05, 0.35),
    "w_M":   (0.10, 0.40),
    "w_Env": (0.05, 0.20),
    "w_C":   (0.05, 0.35),
}

# ─── 사용자별 학습 상태 ───
_user_params = {}
_user_history = {}   # 롤백용
_user_last_update = {}
_lock = Lock()


def _get_params(user_id: str) -> dict:
    """사용자별 현재 파라미터"""
    if user_id not in _user_params:
        _user_params[user_id] = copy.deepcopy(DEFAULT_PARAMS)
    return _user_params[user_id]


def get_params(user_id: str = "default") -> dict:
    """외부에서 현재 파라미터 조회"""
    with _lock:
        return copy.deepcopy(_get_params(user_id))


def _project(key: str, value: float) -> float:
    """경계 투영: 값을 허용 범위로 클램핑"""
    lo, hi = BOUNDS.get(key, (0.0, 1.0))
    return max(lo, min(hi, value))


def _normalize_weights(params: dict):
    """가중치 합이 1.0이 되도록 정규화"""
    w_keys = ["w_E", "w_S", "w_M", "w_Env", "w_C"]
    total = sum(params[k] for k in w_keys)
    if total > 0:
        for k in w_keys:
            params[k] = round(params[k] / total, 4)


def update(user_id: str, feedback: dict) -> dict:
    """
    피드백 기반 파라미터 업데이트

    feedback 구조:
    {
        "type": "explicit" | "implicit",

        # explicit일 때: 사용자가 직접 조정 요청
        "adjust": {"T": +0.05, "w_E": -0.02, ...}

        # implicit일 때: 시스템이 감지
        "signal": "silence_too_much" | "silence_too_little" | "response_good" | "response_bad",
    }

    Returns: 업데이트된 파라미터
    """
    with _lock:
        now = time.time()

        # 냉각 기간 체크
        last = _user_last_update.get(user_id, 0)
        if now - last < COOLDOWN:
            return {
                "status": "cooldown",
                "remaining": round(COOLDOWN - (now - last)),
                "params": copy.deepcopy(_get_params(user_id)),
            }

        params = _get_params(user_id)
        prev = copy.deepcopy(params)
        _user_history[user_id] = prev  # 롤백용 저장

        fb_type = feedback.get("type", "implicit")

        if fb_type == "explicit":
            # 명시적 조정: 사용자가 지정한 delta를 저학습률로 적용
            adjustments = feedback.get("adjust", {})
            for key, delta in adjustments.items():
                if key in params:
                    new_val = params[key] + ALPHA * delta
                    params[key] = _project(key, new_val)

        elif fb_type == "implicit":
            signal = feedback.get("signal", "")

            if signal == "silence_too_much":
                # 침묵이 너무 많다 → T, T1 낮추기
                params["T"] = _project("T", params["T"] - ALPHA * 2)
                params["T1"] = _project("T1", params["T1"] - ALPHA * 2)

            elif signal == "silence_too_little":
                # 침묵이 부족하다 → T, T1 올리기
                params["T"] = _project("T", params["T"] + ALPHA * 2)
                params["T1"] = _project("T1", params["T1"] + ALPHA * 2)

            elif signal == "response_good":
                # 현재 상태 강화 (변화 없음, 안정 신호)
                pass

            elif signal == "response_bad":
                # 감정 가중치 높이고 세션 가중치 낮추기
                params["w_E"] = _project("w_E", params["w_E"] + ALPHA)
                params["w_S"] = _project("w_S", params["w_S"] - ALPHA)

        # 가중치 정규화
        _normalize_weights(params)

        # 발산 롤백: 어떤 파라미터든 변화량이 DELTA_MAX 초과하면 전체 롤백
        for key in params:
            if abs(params[key] - prev[key]) > DELTA_MAX:
                _user_params[user_id] = prev
                return {
                    "status": "rollback",
                    "reason": f"{key} diverged: {prev[key]:.4f} → {params[key]:.4f}",
                    "params": copy.deepcopy(prev),
                }

        _user_last_update[user_id] = now

        return {
            "status": "updated",
            "params": copy.deepcopy(params),
            "changes": {k: round(params[k] - prev[k], 4) for k in params if params[k] != prev[k]},
        }


def rollback(user_id: str) -> dict:
    """수동 롤백: 이전 파라미터로 복원"""
    with _lock:
        prev = _user_history.get(user_id)
        if prev:
            _user_params[user_id] = copy.deepcopy(prev)
            return {"status": "rolled_back", "params": copy.deepcopy(prev)}
        return {"status": "no_history"}


def reset(user_id: str = None):
    """파라미터 리셋"""
    with _lock:
        if user_id:
            _user_params.pop(user_id, None)
            _user_history.pop(user_id, None)
            _user_last_update.pop(user_id, None)
        else:
            _user_params.clear()
            _user_history.clear()
            _user_last_update.clear()
