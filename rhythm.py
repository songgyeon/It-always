# rhythm.py
# Java applyRhythmPattern 대응

"""
Q는 사용자의 말을 따라하지 않는다.
Q는 자신의 말만 한다.

Java 버그(입력을 시드에 붙이기)는 서버에서 이미 수정됨.
시드를 그대로 반환하는 것이 올바른 동작.
"""

import random
from seeds import seeds, get_fallback


def apply_rhythm(seed: str, user_input: str) -> str:
    """
    시드 문장을 그대로 반환한다.
    Q는 사용자의 말을 따라하지 않는다.
    """
    return seed


def idle_line(tone: str = "NEUTRAL") -> str:
    """
    중복 발생 시 or 아무 입력 없을 때 Q가 고요히 말하는 문장 선택.
    tone에 맞는 시드를 우선 시도, 없으면 fallback.
    """
    tone_map = {
        "SAD": "emotion_sad",
        "CURIOUS": "emotion_curious",
        "GENTLE": "emotion_gentle",
        "FIRM": "emotion_firm",
        "SARCASTIC": "emotion_sarcastic",
        "AVOIDING": "emotion_avoiding",
        "NEUTRAL": "prompt",
    }
    key = tone_map.get(tone.upper(), "prompt")
    pool = seeds.get(key, seeds["prompt"])

    # 70% 확률로 tone 시드, 30% 확률로 fallback
    if random.random() < 0.3:
        return get_fallback()
    return random.choice(pool)
