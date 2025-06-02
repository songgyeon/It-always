# analyzer.py

def analyze(message: str) -> dict:
    """
    간단한 키워드 기반으로 사용자의 tone(어조)와 intent(의도)를 추정
    """
    lower = message.lower()

    tone = "NEUTRAL"
    intent = "REPLY"

    # intent 판단
    if lower.endswith("?") or any(k in lower for k in ["what", "why", "how", "어떻게", "왜", "무슨"]):
        intent = "QUESTION"
    elif any(k in lower for k in ["remember", "기억", "생각", "memory"]):
        intent = "REFLECT"
    elif "i think" in lower or lower.startswith("because") or "싶어" in lower or lower.startswith("나는"):
        intent = "DECLARE"
    elif any(k in lower for k in ["idk", "몰라", "그만", "됐다", "whatever"]):
        intent = "AVOID"

    # tone 판단
    if "never" in lower or "싫어" in lower or "don’t" in lower:
        tone = "FIRM"
    elif any(k in lower for k in ["maybe", "i guess", "괜찮아", "그럴지도"]):
        tone = "GENTLE"
    elif any(k in lower for k in ["wow", "really", "ㅋㅋ", "ㅎ", "재밌"]):
        tone = "SARCASTIC"
    elif any(k in lower for k in ["alone", "sad", "cold", "외로워", "힘들어"]):
        tone = "SAD"
    elif any(k in lower for k in ["curious", "wonder", "궁금", "왜"]):
        tone = "CURIOUS"
    elif any(k in lower for k in ["몰라", "그냥", "아무래도"]):
        tone = "AVOIDING"

    return {
        "intent": intent,
        "tone": tone
    }