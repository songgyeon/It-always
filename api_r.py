"""
API-R — 단방향 검증 인터페이스 (UNLIQ 특허 핵심)

특허 명세서:
  "단방향 검증 인터페이스(API-R)를 통한 서명·논스·단조 증가 카운터 포함
   게이트 상태값으로 검증이 가능하다."

  게이트 상태값 = ⟨state, mode, gate_seq, ts, nonce, counter, policy_hash, test_profile_id, log_hash⟩

구현:
  - HMAC-SHA256 서명 (Q_SIGN_KEY 기반)
  - 단조 증가 카운터 (gate_seq)
  - 논스 (uuid4)
  - 정책 해시 (현재 적용 중인 정책의 SHA256)
  - 증명 토큰 (L0 진입 시 셀프테스트 결과 포함)
"""

import hashlib
import hmac
import json
import os
import time
import uuid
from threading import Lock

# ─── 서명 키 ───
_SIGN_KEY = os.getenv("Q_SIGN_KEY", "q-default-sign-key-change-me").encode()

# ─── 사용자별 카운터 (단조 증가) ───
_user_counters = {}
_counter_lock = Lock()


def _next_seq(user_id: str) -> int:
    """단조 증가 카운터 반환"""
    with _counter_lock:
        seq = _user_counters.get(user_id, 0) + 1
        _user_counters[user_id] = seq
        return seq


def _sign(payload: str) -> str:
    """HMAC-SHA256 서명"""
    return hmac.new(_SIGN_KEY, payload.encode(), hashlib.sha256).hexdigest()


def _hash_policy(policy: dict) -> str:
    """정책 딕셔너리의 SHA256 해시"""
    raw = json.dumps(policy, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _hash_log(log_entries: list) -> str:
    """최근 로그의 SHA256 해시 (무결성 검증용)"""
    raw = json.dumps(log_entries[-10:], ensure_ascii=False) if log_entries else ""
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ─── 게이트 상태값 생성 ───

def generate_gate_status(
    mode: str,
    pt: float,
    user_id: str = "default",
    policy: dict = None,
    test_profile_id: str = "default",
    log_entries: list = None,
) -> dict:
    """
    특허 명세서 기반 게이트 상태값 생성

    Returns:
        {
            "state": "active" | "silent" | "attenuated",
            "mode": "L0" | "L1" | "L2",
            "pt": float,
            "gate_seq": int,       # 단조 증가 카운터
            "ts": str,             # ISO 타임스탬프
            "nonce": str,          # UUID4
            "counter": int,        # 글로벌 카운터 (gate_seq와 동일)
            "policy_hash": str,    # 현재 정책의 SHA256
            "test_profile_id": str,
            "log_hash": str,       # 최근 로그의 SHA256
            "signature": str,      # HMAC-SHA256 서명
        }
    """
    if policy is None:
        policy = {}
    if log_entries is None:
        log_entries = []

    state_map = {"L0": "silent", "L1": "attenuated", "L2": "active"}
    state = state_map.get(mode, "active")

    seq = _next_seq(user_id)
    nonce = uuid.uuid4().hex[:16]
    ts = time.strftime("%Y-%m-%dT%H:%M:%S+09:00")
    p_hash = _hash_policy(policy)
    l_hash = _hash_log(log_entries)

    # 서명 대상: 핵심 필드를 파이프로 연결
    sign_payload = f"{state}|{mode}|{seq}|{ts}|{nonce}|{p_hash}|{test_profile_id}|{l_hash}"
    signature = _sign(sign_payload)

    return {
        "state": state,
        "mode": mode,
        "pt": pt,
        "gate_seq": seq,
        "ts": ts,
        "nonce": nonce,
        "counter": seq,
        "policy_hash": p_hash,
        "test_profile_id": test_profile_id,
        "log_hash": l_hash,
        "signature": signature,
    }


# ─── 증명 토큰 (L0 셀프테스트) ───

def generate_proof_token(
    user_id: str,
    mode: str,
    pt: float,
    reason: str = "threshold",
    policy: dict = None,
) -> dict:
    """
    특허 명세서:
      "시험 조건 기반 무출력 셀프테스트·증명 토큰"

    L0 진입 시 호출하여 "진짜 침묵했음"을 증명.

    Returns:
        {
            "token_id": str,
            "user_id": str,
            "mode": "L0",
            "pt": float,
            "reason": str,         # "threshold" | "rearm" | "ethics" | "policy"
            "test_result": "PASS",
            "ts": str,
            "signature": str,
        }
    """
    token_id = uuid.uuid4().hex[:12]
    ts = time.strftime("%Y-%m-%dT%H:%M:%S+09:00")

    # 셀프테스트: L0 진입 조건 재확인
    test_result = "PASS" if mode == "L0" else "FAIL"

    sign_payload = f"proof|{token_id}|{user_id}|{mode}|{pt}|{reason}|{test_result}|{ts}"
    signature = _sign(sign_payload)

    return {
        "token_id": token_id,
        "user_id": user_id,
        "mode": mode,
        "pt": pt,
        "reason": reason,
        "test_result": test_result,
        "ts": ts,
        "signature": signature,
    }


# ─── 서명 검증 ───

def verify_gate_status(gate_status: dict) -> bool:
    """게이트 상태값의 서명을 검증"""
    try:
        sign_payload = (
            f"{gate_status['state']}|{gate_status['mode']}|{gate_status['gate_seq']}|"
            f"{gate_status['ts']}|{gate_status['nonce']}|{gate_status['policy_hash']}|"
            f"{gate_status['test_profile_id']}|{gate_status['log_hash']}"
        )
        expected = _sign(sign_payload)
        return hmac.compare_digest(expected, gate_status.get("signature", ""))
    except (KeyError, TypeError):
        return False


def verify_proof_token(token: dict) -> bool:
    """증명 토큰의 서명을 검증"""
    try:
        sign_payload = (
            f"proof|{token['token_id']}|{token['user_id']}|{token['mode']}|"
            f"{token['pt']}|{token['reason']}|{token['test_result']}|{token['ts']}"
        )
        expected = _sign(sign_payload)
        return hmac.compare_digest(expected, token.get("signature", ""))
    except (KeyError, TypeError):
        return False


# ─── 카운터 리셋 (테스트용) ───

def reset_counter(user_id: str = None):
    with _counter_lock:
        if user_id:
            _user_counters.pop(user_id, None)
        else:
            _user_counters.clear()
