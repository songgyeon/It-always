# tag.py v3
# korean_nlp 형태소 분석 기반 태그 시스템

"""
Java QTagger 대응:
  - 한글 명사 추출 → 세션 태그 생성
  - 감정 태그 우선, 명사 태그 보조

v2 변경:
  - 정규식 → korean_nlp.nouns() (형태소 분석 기반)
  - 감정 감지도 korean_nlp.detect_emotion_from_morphemes() 활용
  - 불용어 필터링 추가

v3 변경:
  - user_id별 태그 분리 (멀티유저 대응)
"""

from collections import defaultdict
import korean_nlp

# ─── 사용자별 태그 저장소 (v3) ───
_user_tags = defaultdict(dict)   # user_id → {tag: original_content}

# ─── 불용어 (태그로 쓰기에 너무 일반적인 명사) ───
STOPWORD_NOUNS = {
    "거", "것", "때", "중", "뭐", "이", "나", "너", "우리", "그",
    "오늘", "내일", "어제", "지금", "여기", "거기", "이거", "저거",
    "말", "생각", "느낌", "기분", "마음", "사람", "얘기", "이야기",
    "좀", "더", "잘", "참", "진짜",
}


def extract_nouns(text: str) -> list:
    """
    형태소 분석 기반 명사 추출 (2글자 이상, 불용어 제외)
    """
    raw_nouns = korean_nlp.nouns(text)
    return [n for n in raw_nouns if len(n) >= 2 and n not in STOPWORD_NOUNS]


def detect_emotion_tag(text: str) -> str:
    """
    형태소 분석 기반 감정 태그 추출.
    korean_nlp가 못 잡으면 키워드 폴백.
    """
    # 1차: 형태소 분석
    emotion = korean_nlp.detect_emotion_from_morphemes(text)
    if emotion:
        return emotion

    # 2차: 키워드 폴백
    lower = text.lower()

    if any(w in lower for w in ["슬퍼", "외로", "힘들", "아파", "울"]):
        return "SAD"
    elif any(w in lower for w in ["기뻐", "좋아", "행복", "웃어"]):
        return "HAPPY"
    elif any(w in lower for w in ["화나", "짜증", "열받", "분노"]):
        return "ANGRY"
    elif any(w in lower for w in ["궁금", "왜", "어떻게", "?"]):
        return "CURIOUS"
    elif any(w in lower for w in ["그냥", "몰라", "아무래도"]):
        return "AVOIDING"
    elif any(w in lower for w in ["그리워", "보고 싶", "추억"]):
        return "LONGING"
    elif any(w in lower for w in ["사랑", "좋아해", "love"]):
        return "LOVE"

    return ""


def tag_store(content: str, user_id: str = "default") -> str:
    """
    콘텐츠에서 감정 또는 명사 기반 태그 추출 및 저장.
    감정 태그 우선 → 명사 태그 보조.
    v3: user_id별 분리.
    """
    tags = _user_tags[user_id]

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


def get_all_tags(user_id: str = "default") -> list:
    return list(_user_tags[user_id].keys())


def get_tagged_content(tag: str, user_id: str = "default") -> str:
    return _user_tags[user_id].get(tag, "")


def reset_tags(user_id: str = None):
    if user_id:
        _user_tags[user_id].clear()
    else:
        _user_tags.clear()
