# rhythm.py

import random
from seeds import seeds

def apply_rhythm(seed: str, user_input: str) -> str:
    """
    유저 입력과 시드 문장을 자연스럽게 조합하여 리듬 있는 발화를 생성.
    """
    if not user_input.strip():
        return seed

    input_clean = user_input.strip().rstrip(".!?")

    # 의문형인 경우
    if user_input.endswith("?"):
        return f"{seed}\n...{user_input}"

    # 짧은 감탄형
    if len(input_clean) <= 6:
        return f"{seed}\n너, {input_clean}."

    # "나는 ~라고 들었어."는 너무 인공적으로 느껴지면 제거
    if any(word in input_clean for word in ["싶어", "좋아", "기억", "생각", "있어"]):
        return f"{seed}\n나도 그렇게 느꼈어."

    # 기본 리듬
    return f"{seed}\n{input_clean}..."

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