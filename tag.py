import re

# 내부 태그 저장소
tags = {}  # key: tag, value: original content


def extract_nouns(text: str) -> list:
    """
    한글 텍스트에서 2글자 이상의 명사 후보를 추출 (정규식 기반)
    """
    if not text or not isinstance(text, str):
        return []
    return re.findall(r"[\uAC00-\uD7A3]{2,}", text)


def detect_emotion_tag(text: str) -> str:
    """
    감정 기반 태그 추출
    """
    lower = text.lower()

    if any(word in lower for word in ["sad", "슬퍼", "외로", "힘들", "아파", "울"]):
        return "SAD"
    elif any(word in lower for word in ["happy", "기뻐", "좋아", "웃어", "행복"]):
        return "HAPPY"
    elif any(word in lower for word in ["angry", "화나", "짜증", "열받", "분노"]):
        return "ANGRY"
    elif any(word in lower for word in ["curious", "궁금", "왜", "어떻게", "?"]):
        return "CURIOUS"
    elif any(word in lower for word in ["그냥", "몰라", "아무래도", "대충"]):
        return "AVOIDING"
    elif any(word in lower for word in ["그리워", "보고 싶", "기억", "추억"]):
        return "LONGING"
    elif any(word in lower for word in ["사랑", "like you", "love", "좋아해"]):
        return "LOVE"

    return ""


def tag_store(content: str) -> str:
    """
    콘텐츠에서 감정 또는 명사 기반 태그 추출 및 저장
    감정 태그가 있으면 우선 사용, 아니면 새로운 명사 중 하나를 태그로 사용
    중복되면 fallback으로 '기억'
    """
    # 감정 기반 우선
    emotion_tag = detect_emotion_tag(content)
    if emotion_tag and emotion_tag not in tags:
        tags[emotion_tag] = content
        return emotion_tag

    # 명사 기반 추출
    nouns = extract_nouns(content)
    for noun in nouns:
        if noun not in tags:
            tags[noun] = content
            return noun

    return "기억"  # fallback


def get_all_tags() -> list:
    """
    현재 저장된 태그 목록 반환
    """
    return list(tags.keys())


def get_tagged_content(tag: str) -> str:
    """
    특정 태그에 연결된 콘텐츠 반환
    """
    return tags.get(tag, "")


def reset_tags():
    """
    모든 태그 초기화
    """
    tags.clear()