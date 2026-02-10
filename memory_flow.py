# memory_flow.py
# Q.java QMemoryFlow 대응 — 톤 흐름 추적 + 키워드 빈도 맵

"""
Java QMemoryFlow 기능:
  - Deque<QState.Tone> toneFlow  // 최근 10개 톤 기록
  - Map<String, Integer> keywordMap  // 키워드 빈도
  - hasRecentTone(tone)     → 최근에 특정 톤이 있었는지
  - isEmotionallyStable()   → 톤 종류 ≤ 2개면 안정
  - mostUsedKeyword()       → 가장 많이 쓴 키워드
"""

import re
from collections import deque, Counter

# ─── 상태 ───
_tone_flow = deque(maxlen=10)       # 최근 10개 톤
_keyword_map = Counter()            # 키워드 빈도
_closeness_history = deque(maxlen=10)  # 최근 closeness 추적
_doubt_history = deque(maxlen=10)      # 최근 doubt 추적


def record_tone(tone: str):
    """톤 기록 추가"""
    _tone_flow.append(tone.upper())


def record_closeness(closeness: float):
    """친밀도 기록"""
    _closeness_history.append(closeness)


def record_doubt(doubt: float):
    """의심도 기록"""
    _doubt_history.append(doubt)


def record_keywords(message: str):
    """메시지에서 키워드 추출 후 빈도 맵에 기록"""
    # 한글 2글자 이상 명사 후보 + 영어 단어 3글자 이상
    kr_words = re.findall(r"[\uAC00-\uD7A3]{2,}", message)
    en_words = re.findall(r"[a-zA-Z]{3,}", message.lower())

    # 불용어 제거
    kr_stopwords = {"그래서", "그런데", "하지만", "그리고", "그냥", "이거", "저거", "거기",
                    "여기", "어디", "누구", "무슨", "어떤", "이런", "저런", "그런"}
    en_stopwords = {"the", "and", "but", "for", "not", "you", "are", "was",
                    "were", "been", "have", "has", "had", "this", "that",
                    "with", "from", "what", "when", "where", "how", "why"}

    for w in kr_words:
        if w not in kr_stopwords:
            _keyword_map[w] += 1
    for w in en_words:
        if w not in en_stopwords:
            _keyword_map[w] += 1


def record(tone: str, closeness: float, doubt: float, message: str):
    """한번에 모든 흐름 데이터 기록"""
    record_tone(tone)
    record_closeness(closeness)
    record_doubt(doubt)
    record_keywords(message)


# ─── 조회 함수 (Java QMemoryFlow 대응) ───

def has_recent_tone(tone: str) -> bool:
    """최근 톤 흐름에 특정 톤이 있는지"""
    return tone.upper() in _tone_flow


def is_emotionally_stable() -> bool:
    """톤 종류가 2개 이하면 감정적으로 안정"""
    if len(_tone_flow) < 3:
        return True
    return len(set(_tone_flow)) <= 2


def most_used_keyword() -> str:
    """가장 많이 사용된 키워드 반환"""
    if not _keyword_map:
        return ""
    return _keyword_map.most_common(1)[0][0]


def get_keyword_count(keyword: str) -> int:
    """특정 키워드 빈도 조회"""
    return _keyword_map.get(keyword, 0)


def get_tone_flow() -> list:
    """최근 톤 흐름 리스트 반환"""
    return list(_tone_flow)


def get_average_closeness() -> float:
    """최근 평균 친밀도"""
    if not _closeness_history:
        return 0.5
    return round(sum(_closeness_history) / len(_closeness_history), 2)


def get_average_doubt() -> float:
    """최근 평균 의심도"""
    if not _doubt_history:
        return 0.3
    return round(sum(_doubt_history) / len(_doubt_history), 2)


def get_dominant_tone() -> str:
    """최근 흐름에서 가장 지배적인 톤"""
    if not _tone_flow:
        return "NEUTRAL"
    tone_counter = Counter(_tone_flow)
    return tone_counter.most_common(1)[0][0]


def is_tone_shifting() -> bool:
    """최근 3턴 내 톤이 바뀌었는지 (감정 변동 감지)"""
    if len(_tone_flow) < 3:
        return False
    last_3 = list(_tone_flow)[-3:]
    return len(set(last_3)) >= 3


def get_flow_summary() -> dict:
    """디버그/상태 확인용 전체 요약"""
    return {
        "tone_flow": list(_tone_flow),
        "dominant_tone": get_dominant_tone(),
        "emotionally_stable": is_emotionally_stable(),
        "tone_shifting": is_tone_shifting(),
        "avg_closeness": get_average_closeness(),
        "avg_doubt": get_average_doubt(),
        "top_keywords": _keyword_map.most_common(5),
        "most_used_keyword": most_used_keyword(),
    }


# ─── 리셋 ───
def reset():
    """세션 초기화"""
    _tone_flow.clear()
    _keyword_map.clear()
    _closeness_history.clear()
    _doubt_history.clear()
