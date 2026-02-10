"""
Crypto Log — AES-GCM 암호화 로그 + 암호학적 소거

특허 명세서:
  "AES-GCM 기반 로그·암호학적 소거(키 폐기) 기반 불가역 삭제"

구현:
  - 대화 로그를 AES-256-GCM으로 암호화하여 저장
  - 사용자별 암호화 키 관리
  - 키 폐기 = 불가역 삭제 (데이터는 남지만 복호화 불가)
  - 로그 무결성 해시 체인

의존성: cryptography (requirements.txt에 추가)
"""

import hashlib
import json
import os
import time
from threading import Lock

# cryptography 패키지 사용 (없으면 폴백)
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

# ─── 사용자별 키/로그 저장소 ───
_user_keys = {}        # user_id → bytes (AES-256 키)
_user_logs = {}        # user_id → [encrypted_entry, ...]
_user_hash_chain = {}  # user_id → 마지막 해시
_destroyed_users = set()  # 키 폐기된 사용자
_lock = Lock()


def _get_or_create_key(user_id: str) -> bytes:
    """사용자 암호화 키 가져오기 (없으면 생성)"""
    if user_id not in _user_keys:
        _user_keys[user_id] = os.urandom(32)  # AES-256
    return _user_keys[user_id]


def _chain_hash(prev_hash: str, data: str) -> str:
    """해시 체인: 이전 해시 + 현재 데이터 → 새 해시"""
    payload = f"{prev_hash}|{data}"
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def encrypt_and_store(user_id: str, role: str, content: str) -> dict:
    """
    대화 로그를 암호화하여 저장

    Returns:
        {
            "status": "stored" | "destroyed" | "plaintext_fallback",
            "log_hash": str,
            "entry_count": int,
        }
    """
    with _lock:
        # 키 폐기된 사용자는 저장 불가
        if user_id in _destroyed_users:
            return {"status": "destroyed", "log_hash": "", "entry_count": 0}

        # 로그 데이터 구성
        log_entry = {
            "role": role,
            "content": content,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        }
        plaintext = json.dumps(log_entry, ensure_ascii=False).encode()

        if HAS_CRYPTO:
            key = _get_or_create_key(user_id)
            nonce = os.urandom(12)  # GCM 논스
            aesgcm = AESGCM(key)
            ciphertext = aesgcm.encrypt(nonce, plaintext, None)

            encrypted_entry = {
                "nonce": nonce.hex(),
                "ciphertext": ciphertext.hex(),
            }
            status = "stored"
        else:
            # cryptography 없으면 평문 저장 (폴백)
            encrypted_entry = {
                "plaintext": plaintext.decode(),
            }
            status = "plaintext_fallback"

        # 저장
        if user_id not in _user_logs:
            _user_logs[user_id] = []
        _user_logs[user_id].append(encrypted_entry)

        # 해시 체인 갱신
        prev = _user_hash_chain.get(user_id, "0" * 32)
        new_hash = _chain_hash(prev, content)
        _user_hash_chain[user_id] = new_hash

        return {
            "status": status,
            "log_hash": new_hash,
            "entry_count": len(_user_logs[user_id]),
        }


def decrypt_logs(user_id: str) -> list:
    """사용자 로그 복호화 (키가 있는 경우에만)"""
    with _lock:
        if user_id in _destroyed_users:
            return [{"error": "keys_destroyed", "message": "불가역 삭제됨"}]

        logs = _user_logs.get(user_id, [])
        if not logs:
            return []

        result = []
        if HAS_CRYPTO:
            key = _user_keys.get(user_id)
            if not key:
                return [{"error": "no_key"}]

            aesgcm = AESGCM(key)
            for entry in logs:
                try:
                    nonce = bytes.fromhex(entry["nonce"])
                    ciphertext = bytes.fromhex(entry["ciphertext"])
                    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
                    result.append(json.loads(plaintext))
                except Exception:
                    result.append({"error": "decrypt_failed"})
        else:
            for entry in logs:
                if "plaintext" in entry:
                    result.append(json.loads(entry["plaintext"]))

        return result


def destroy_keys(user_id: str) -> dict:
    """
    암호학적 소거: 키 폐기로 불가역 삭제

    특허 명세서:
      "암호학적 소거(키 폐기) 기반 불가역 삭제"

    키를 제로로 덮어쓰고 삭제.
    데이터(암호문)는 남지만 복호화 불가.
    """
    with _lock:
        if user_id in _user_keys:
            # 키를 제로로 덮어쓰기 (메모리 잔류 최소화)
            key_ref = _user_keys[user_id]
            _user_keys[user_id] = b'\x00' * len(key_ref)
            del _user_keys[user_id]

        _destroyed_users.add(user_id)

        log_count = len(_user_logs.get(user_id, []))

        return {
            "status": "destroyed",
            "user_id": user_id,
            "encrypted_entries_remaining": log_count,
            "recoverable": False,
        }


def get_log_hash(user_id: str) -> str:
    """현재 로그 해시 체인의 마지막 값"""
    return _user_hash_chain.get(user_id, "0" * 32)


def get_log_count(user_id: str) -> int:
    """암호화된 로그 수"""
    return len(_user_logs.get(user_id, []))


def is_destroyed(user_id: str) -> bool:
    """키 폐기 여부 확인"""
    return user_id in _destroyed_users


def reset(user_id: str = None):
    """테스트용 리셋"""
    with _lock:
        if user_id:
            _user_keys.pop(user_id, None)
            _user_logs.pop(user_id, None)
            _user_hash_chain.pop(user_id, None)
            _destroyed_users.discard(user_id)
        else:
            _user_keys.clear()
            _user_logs.clear()
            _user_hash_chain.clear()
            _destroyed_users.clear()
