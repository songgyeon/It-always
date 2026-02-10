# rhythm.py

import random
from seeds import seeds

def apply_rhythm(seed: str, user_input: str) -> str:
    """
    시드 문장을 그대로 반환한다.
    Q는 사용자의 말을 따라하지 않는다.
    Q는 자신의 말만 한다.
    """
    return seed

def idle_line(tone: str = "NEUTRAL") -> str:
    """
    아무 입력 없을 때 Q가 고요히 말하는 문장 선택
    """
    tone_map = {
        "SAD": "emotion_sad",
        "CURIOUS": "emotion_curious",
        "GENTLE": "emotion_gentle",
        "FIRM": "emotion_firm",
        "SARCASTIC": "emotion_sarcastic",
        "AVOIDING": "reflection",
        "NEUTRAL": "prompt"
    }
    key = tone_map.get(tone.upper(), "prompt")
    return random.choice(seeds.get(key, seeds["prompt"]))
