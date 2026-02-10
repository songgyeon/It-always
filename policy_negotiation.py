"""
Policy Negotiation — 사용자 협상형 정책

특허 명세서:
  "사용자 협상형 정책을 지원"
  "맥락·자원 기반 정책"

구현:
  - 사용자별 정책 프로파일 (침묵 민감도, 시간대 선호, 응답 스타일)
  - 정책 협상 API (사용자가 "침묵 줄여줘" 같은 요청)
  - 맥락 기반 자동 정책 전환 (야간/주간, 대화 깊이)
  - 정책 → pt_engine 파라미터 매핑
"""

import copy
import hashlib
import json
import time
from threading import Lock

# ─── 기본 정책 ───
DEFAULT_POLICY = {
    "silence_sensitivity": 0.5,   # 0.0(침묵 많이) ~ 1.0(침묵 적게)
    "response_length": "normal",  # "minimal" | "short" | "normal"
    "night_mode": True,           # 야간(0~6시) 자동 L1 우선
    "emotional_priority": True,   # 감정 변수 우선 적용
    "cooldown_override": None,    # 사용자가 원하는 재무장 시간 (초, None이면 기본)
    "context_tags": [],           # 맥락 태그 ("work", "sleep", "conversation")
    "created_at": "",
    "updated_at": "",
}

# ─── 프리셋 정책 ───
PRESETS = {
    "quiet": {
        "silence_sensitivity": 0.2,
        "response_length": "minimal",
        "night_mode": True,
        "emotional_priority": True,
    },
    "talkative": {
        "silence_sensitivity": 0.8,
        "response_length": "normal",
        "night_mode": False,
        "emotional_priority": False,
    },
    "night": {
        "silence_sensitivity": 0.3,
        "response_length": "short",
        "night_mode": True,
        "emotional_priority": True,
    },
    "default": {},
}

# ─── 사용자별 정책 저장소 ───
_user_policies = {}
_lock = Lock()


def _get_policy(user_id: str) -> dict:
    if user_id not in _user_policies:
        p = copy.deepcopy(DEFAULT_POLICY)
        p["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+09:00")
        p["updated_at"] = p["created_at"]
        _user_policies[user_id] = p
    return _user_policies[user_id]


def get_policy(user_id: str = "default") -> dict:
    """현재 정책 조회"""
    with _lock:
        return copy.deepcopy(_get_policy(user_id))


def get_policy_hash(user_id: str = "default") -> str:
    """정책의 SHA256 해시 (API-R용)"""
    policy = get_policy(user_id)
    raw = json.dumps(policy, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def negotiate(user_id: str, request: dict) -> dict:
    """
    사용자 협상형 정책 업데이트

    request 구조:
    {
        "preset": "quiet" | "talkative" | "night" | "default",
        # 또는 개별 조정:
        "silence_sensitivity": 0.3,
        "response_length": "short",
        "night_mode": True,
        "context_tags": ["sleep"],
    }

    Returns: 업데이트된 정책
    """
    with _lock:
        policy = _get_policy(user_id)

        # 프리셋 적용
        preset_name = request.get("preset")
        if preset_name and preset_name in PRESETS:
            for k, v in PRESETS[preset_name].items():
                policy[k] = v

        # 개별 필드 업데이트
        for key in ["silence_sensitivity", "response_length", "night_mode",
                     "emotional_priority", "cooldown_override", "context_tags"]:
            if key in request:
                val = request[key]
                # 범위 검증
                if key == "silence_sensitivity":
                    val = max(0.0, min(1.0, float(val)))
                elif key == "response_length" and val not in ("minimal", "short", "normal"):
                    continue
                elif key == "cooldown_override" and val is not None:
                    val = max(5, min(300, int(val)))
                policy[key] = val

        policy["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+09:00")

        return {
            "status": "negotiated",
            "policy": copy.deepcopy(policy),
        }


def apply_to_params(user_id: str, base_params: dict) -> dict:
    """
    정책을 pt_engine 파라미터에 반영

    silence_sensitivity → T, T1 조정
    emotional_priority → w_E 가중
    night_mode → Env 패널티 (pt_engine에서 사용)
    """
    policy = get_policy(user_id)
    params = copy.deepcopy(base_params)

    # silence_sensitivity: 높을수록 침묵 줄어듦 (T 낮아짐)
    ss = policy["silence_sensitivity"]
    # 0.5가 기본, 0.0이면 T += 0.1, 1.0이면 T -= 0.1
    t_adjust = (0.5 - ss) * 0.20
    params["T"] = max(0.30, min(0.85, params["T"] + t_adjust))
    params["T1"] = max(0.15, min(0.55, params["T1"] + t_adjust * 0.5))

    # emotional_priority: True이면 w_E 약간 높임
    if policy["emotional_priority"]:
        params["w_E"] = min(0.40, params["w_E"] + 0.03)
        # 가중치 재정규화
        w_keys = ["w_E", "w_S", "w_M", "w_Env", "w_C"]
        total = sum(params[k] for k in w_keys)
        if total > 0:
            for k in w_keys:
                params[k] = round(params[k] / total, 4)

    return params


def get_context_modifier(user_id: str) -> dict:
    """현재 맥락 태그 기반 추가 수정자 반환"""
    policy = get_policy(user_id)
    tags = policy.get("context_tags", [])

    modifier = {"max_tokens_override": None, "force_l1": False}

    if "sleep" in tags:
        modifier["force_l1"] = True
        modifier["max_tokens_override"] = 40

    if "work" in tags:
        modifier["max_tokens_override"] = 100

    return modifier


def reset(user_id: str = None):
    """정책 리셋"""
    with _lock:
        if user_id:
            _user_policies.pop(user_id, None)
        else:
            _user_policies.clear()
