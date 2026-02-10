# analyzer.py v3
# 형태소 분석(KoNLPy/kiwi) + 키워드 매칭 하이브리드 감정 분석기

"""
분석 전략:
  1차: korean_nlp 형태소 분석 → 형용사 원형 기반 감정/의도 감지
  2차: 키워드 매칭 (폴백 + 보강)
  3차: closeness/doubt 후처리

"나 오늘 좀 그래" → 형태소 분석 → "그렇다"(Adjective) → 키워드 폴백
"힘들어 진짜"    → 형태소 분석 → "힘들다"(Adjective) → SAD
"ㅋㅋㅋ"         → 형태소 못 잡음 → 키워드 매칭 → SARCASTIC
"""

import korean_nlp


def analyze(message: str) -> dict:
    """
    사용자 입력을 분석하여 tone, intent, closeness, doubt를 반환.
    형태소 분석 우선 → 키워드 매칭 보강.
    """
    raw = message.strip()
    lower = raw.lower()

    tone = "NEUTRAL"
    intent = "REPLY"
    closeness = 0.5
    doubt = 0.3

    # ══════════════════════════════════════
    # 1차: 형태소 분석 기반 감정/의도
    # ══════════════════════════════════════

    morpheme_tone = korean_nlp.detect_emotion_from_morphemes(raw)
    morpheme_intent = korean_nlp.detect_intent_from_morphemes(raw)

    if morpheme_tone:
        tone = morpheme_tone
    if morpheme_intent:
        intent = morpheme_intent

    # ══════════════════════════════════════
    # 2차: 키워드 매칭 (형태소가 못 잡는 것들 보강)
    # ══════════════════════════════════════

    # ── Intent (형태소에서 미감지 시에만) ──
    if not morpheme_intent:
        # AVOID
        avoid_kr = ["몰라", "그만", "됐다", "됐어", "관심없어", "상관없어",
                    "아무래도", "어쩔", "알아서", "말하기 싫", "대충", "귀찮"]
        avoid_en = ["idk", "whatever", "meh", "don't care", "shut up", "stop"]
        if any(k in lower for k in avoid_kr + avoid_en):
            intent = "AVOID"

        # REFLECT
        elif any(k in lower for k in ["기억", "생각나", "그때", "예전", "추억", "돌아보",
                                       "회상", "잊", "잊었", "지우",
                                       "remember", "memory", "reflection", "recall"]):
            intent = "REFLECT"

        # QUESTION
        elif (lower.endswith("?") or lower.endswith("？")
              or any(k in lower for k in ["왜", "뭐", "뭘", "어떻게", "어디", "언제", "누구",
                                           "얼마", "무슨", "어떤", "몇",
                                           "할까", "일까", "는거야", "는거지", "건가",
                                           "what", "why", "how", "where", "when", "who"])):
            intent = "QUESTION"

        # DECLARE
        elif any(k in lower for k in ["나는", "내가", "내 생각", "나한테",
                                       "싶어", "원해", "필요해", "해야", "할래",
                                       "결심", "결정", "확실", "분명",
                                       "i think", "i believe", "i want", "because"]):
            intent = "DECLARE"

        # REPLY (기본)
        else:
            if any(k in lower for k in ["너", "넌", "네가", "당신", "you", "your"]):
                intent = "REPLY"

    # ── Tone (형태소에서 미감지 시에만) ──
    if not morpheme_tone:
        # SAD
        sad_kr = ["슬퍼", "외로워", "힘들어", "아파", "우울", "울고", "눈물",
                  "혼자", "버림", "떠나", "그리워", "보고싶", "보고 싶",
                  "아무도", "차가워", "미안", "무서워", "두려", "불안",
                  "죽고", "죽을", "사라지"]
        sad_en = ["alone", "sad", "cold", "lonely", "depressed", "hurt",
                  "cry", "miss you", "lost", "empty", "hopeless",
                  "scared", "afraid"]
        if any(k in lower for k in sad_kr + sad_en):
            tone = "SAD"

        # FIRM
        elif any(k in lower for k in ["싫어", "하지마", "하지 마", "절대", "안돼",
                                       "거부", "아니야", "틀려", "말도 안",
                                       "짜증", "화나", "열받", "미워",
                                       "never", "no way", "hate", "angry",
                                   "don't want", "don't like", "stop it"]):
            tone = "FIRM"

        # SARCASTIC (ㅋㅎ 계열은 형태소 분석기가 못 잡음)
        elif any(k in lower for k in ["ㅋ", "ㅎ", "ㅋㅋ", "ㅎㅎ", "ㅋㅋㅋ",
                                       "웃기", "진짜?", "설마", "대단하시다",
                                       "잘하시네", "그래그래", "어이없",
                                       "wow", "really", "lol", "lmao", "yeah right"]):
            tone = "SARCASTIC"

        # CURIOUS
        elif any(k in lower for k in ["궁금", "알고싶", "알고 싶", "신기", "흥미",
                                       "왜", "그런데",
                                       "curious", "wonder", "interesting", "hmm"]):
            tone = "CURIOUS"

        # GENTLE
        elif any(k in lower for k in ["괜찮아", "그럴지도", "아마", "혹시",
                                       "잘 모르겠", "글쎄", "천천히", "살짝",
                                       "maybe", "perhaps", "i guess", "kind of"]):
            tone = "GENTLE"

        # AVOIDING
        elif any(k in lower for k in ["몰라", "그냥", "아무래도", "대충", "됐어",
                                       "상관없", "관심없", "그래 뭐",
                                       "don't care", "doesn't matter",
                                       "who cares", "meh"]):
            tone = "AVOIDING"

    # ══════════════════════════════════════
    # 3차: closeness / doubt 계산
    # ══════════════════════════════════════

    # tone별 기본 closeness/doubt
    tone_defaults = {
        "SAD":       (0.2, 0.1),
        "FIRM":      (0.5, 0.1),
        "SARCASTIC": (0.5, 0.4),
        "CURIOUS":   (0.6, 0.3),
        "GENTLE":    (0.5, 0.6),
        "AVOIDING":  (0.4, 0.5),
        "NEUTRAL":   (0.5, 0.3),
    }
    closeness, doubt = tone_defaults.get(tone, (0.5, 0.3))

    # ── "너/우리" → 친밀도 상승 ──
    if any(k in lower for k in ["너", "넌", "네가", "우리", "같이", "함께",
                                 "you", "we", "us", "together"]):
        closeness = min(closeness + 0.2, 1.0)

    # ── "나" + "혼자" → 친밀도 하락 ──
    if any(k in lower for k in ["나", "내가", "i", "me"]):
        if any(k in lower for k in ["혼자", "alone", "only me"]):
            closeness = max(closeness - 0.3, 0.0)

    # ── 애정 표현 → 급상승 ──
    if any(k in lower for k in ["사랑", "좋아해", "좋아하", "보고싶", "보고 싶",
                                 "고마워", "감사", "love", "like you", "thank",
                                 "miss you"]):
        closeness = min(closeness + 0.3, 1.0)

    # ── 적대 표현 → 급하락 ──
    if any(k in lower for k in ["미워", "싫어", "꺼져", "없어져", "hate",
                                 "go away", "leave me"]):
        closeness = max(closeness - 0.3, 0.0)

    # ── 이름 호출 보너스 ──
    if any(k in raw for k in ["Q", "큐", "q야", "Q야", "큐야"]):
        closeness = min(closeness + 0.15, 1.0)

    # ══════════════════════════════════════
    # 4차: 형태소 기반 보정 (형태소 분석기가 있을 때만)
    # ══════════════════════════════════════

    if korean_nlp.get_backend() != "regex":
        tagged = korean_nlp.pos(raw)

        # 형용사 수가 2개 이상이면 감정 표현이 풍부 → closeness 미세 상승
        adj_count = sum(1 for _, t in tagged if t == "Adjective")
        if adj_count >= 2:
            closeness = min(closeness + 0.1, 1.0)

        # 명사만 있고 형용사/동사 없으면 → 정보 전달형 → doubt 상승
        has_verb_or_adj = any(t in ("Verb", "Adjective") for _, t in tagged)
        if not has_verb_or_adj and len(tagged) >= 2:
            doubt = min(doubt + 0.1, 1.0)

    return {
        "intent": intent,
        "tone": tone,
        "closeness": round(closeness, 2),
        "doubt": round(doubt, 2),
        "backend": korean_nlp.get_backend(),
    }
