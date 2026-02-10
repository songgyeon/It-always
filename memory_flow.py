# memory_flow.py
# Q.java QMemoryFlow 대응 — 톤 흐름 추적 + 키워드 빈도 맵
# v4: user_id별 상태 분리

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

# ─── 사용자별 상태 저장소 ───
_user_flows = {}


def _get_flow(user_id: str = "default") -> dict:
    """사용자별 흐름 상태를 가져오거나 새로 생성"""
    if user_id not in _user_flows:
        _user_flows[user_id] = {
            "tone_flow": deque(maxlen=10),
            "keyword_map": Counter(),
            "closeness_history": deque(maxlen=10),
            "doubt_history": deque(maxlen=10),
        }
    return _user_flows[user_id]


def record_tone(tone: str, user_id: str = "default"):
    """톤 기록 추가"""
    flow = _get_flow(user_id)
    flow["tone_flow"].append(tone.upper())


def record_closeness(closeness: float, user_id: str = "default"):
    """친밀도 기록"""
    flow = _get_flow(user_id)
    flow["closeness_history"].append(closeness)


def record_doubt(doubt: float, user_id: str = "default"):
    """의심도 기록"""
    flow = _get_flow(user_id)
    flow["doubt_history"].append(doubt)


def record_keywords(message: str, user_id: str = "default"):
    """메시지에서 키워드 추출 후 빈도 맵에 기록"""
    flow = _get_flow(user_id)
    kr_words = re.findall(r"[\uAC00-\uD7A3]{2,}", message)
    en_words = re.findall(r"[a-zA-Z]{3,}", message.lower())

    kr_stopwords = {"그래서", "그런데", "하지만", "그리고", "그냥", "이거", "저거", "거기",
                    "여기", "어디", "누구", "무슨", "어떤", "이런", "저런", "그런"}
    en_stopwords = {"the", "and", "but", "for", "not", "you", "are", "was",
                    "were", "been", "have", "has", "had", "this", "that",
                    "with", "from", "what", "when", "where", "how", "why"}

    for w in kr_words:
        if w not in kr_stopwords:
            flow["keyword_map"][w] += 1
    for w in en_words:
        if w not in en_stopwords:
            flow["keyword_map"][w] += 1


def record(tone: str, closeness: float, doubt: float, message: str,
           user_id: str = "default"):
    """한번에 모든 흐름 데이터 기록"""
    record_tone(tone, user_id)
    record_closeness(closeness, user_id)
    record_doubt(doubt, user_id)
    record_keywords(message, user_id)


# ─── 조회 함수 ───

def has_recent_tone(tone: str, user_id: str = "default") -> bool:
    flow = _get_flow(user_id)
    return tone.upper() in flow["tone_flow"]


def is_emotionally_stable(user_id: str = "default") -> bool:
    flow = _get_flow(user_id)
    if len(flow["tone_flow"]) < 3:
        return True
    return len(set(flow["tone_flow"])) <= 2


def most_used_keyword(user_id: str = "default") -> str:
    flow = _get_flow(user_id)
    if not flow["keyword_map"]:
        return ""
    return flow["keyword_map"].most_common(1)[0][0]


def get_keyword_count(keyword: str, user_id: str = "default") -> int:
    flow = _get_flow(user_id)
    return flow["keyword_map"].get(keyword, 0)


def get_tone_flow(user_id: str = "default") -> list:
    flow = _get_flow(user_id)
    return list(flow["tone_flow"])


def get_average_closeness(user_id: str = "default") -> float:
    flow = _get_flow(user_id)
    if not flow["closeness_history"]:
        return 0.5
    return round(sum(flow["closeness_history"]) / len(flow["closeness_history"]), 2)


def get_average_doubt(user_id: str = "default") -> float:
    flow = _get_flow(user_id)
    if not flow["doubt_history"]:
        return 0.3
    return round(sum(flow["doubt_history"]) / len(flow["doubt_history"]), 2)


def get_dominant_tone(user_id: str = "default") -> str:
    flow = _get_flow(user_id)
    if not flow["tone_flow"]:
        return "NEUTRAL"
    tone_counter = Counter(flow["tone_flow"])
    return tone_counter.most_common(1)[0][0]


def is_tone_shifting(user_id: str = "default") -> bool:
    flow = _get_flow(user_id)
    if len(flow["tone_flow"]) < 3:
        return False
    last_3 = list(flow["tone_flow"])[-3:]
    return len(set(last_3)) >= 3


def get_flow_summary(user_id: str = "default") -> dict:
    return {
        "tone_flow": get_tone_flow(user_id),
        "dominant_tone": get_dominant_tone(user_id),
        "emotionally_stable": is_emotionally_stable(user_id),
        "tone_shifting": is_tone_shifting(user_id),
        "avg_closeness": get_average_closeness(user_id),
        "avg_doubt": get_average_doubt(user_id),
        "top_keywords": _get_flow(user_id)["keyword_map"].most_common(5),
        "most_used_keyword": most_used_keyword(user_id),
    }


# ─── 리셋 ───
def reset(user_id: str = "default"):
    """특정 사용자 세션 초기화"""
    if user_id in _user_flows:
        del _user_flows[user_id]


def reset_all():
    """모든 사용자 세션 초기화"""
    _user_flows.clear()
