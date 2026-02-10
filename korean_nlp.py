# korean_nlp.py
# 한국어 형태소 분석 래퍼 — kiwipiepy → 정규식 폴백

"""
Render 배포 안정성을 위한 2단 폴백:
  1차: kiwipiepy (C++ 기반, 가볍고 빠름)
  2차: 정규식 (의존성 없음, 최소 기능)

KoNLPy(Java 기반)는 메모리 400MB+ 차지하여 제거됨.
512MB 환경에서도 안정적으로 동작.
"""

import re
import logging

logger = logging.getLogger("korean_nlp")

# ─── 분석기 초기화 (폴백 체인) ───
_backend = None
_analyzer = None


def _init():
    global _backend, _analyzer

    if _backend is not None:
        return

    # 1차: kiwipiepy
    try:
        from kiwipiepy import Kiwi
        _analyzer = Kiwi(num_workers=0, load_default_dict=False)
        _backend = "kiwi"
        logger.info("✅ korean_nlp: kiwipiepy 로드 성공")
        return
    except Exception as e:
        logger.warning(f"⚠️ kiwipiepy 실패: {e}")

    # 2차: 정규식 폴백
    _backend = "regex"
    _analyzer = None
    logger.warning("⚠️ korean_nlp: 형태소 분석기 없음 → 정규식 폴백")


def get_backend() -> str:
    """현재 사용 중인 백엔드 확인"""
    _init()
    return _backend


# ────────────────────────────────────
# 품사 태깅 (POS tagging)
# ────────────────────────────────────

def pos(text: str) -> list:
    """
    형태소 분석 + 품사 태깅
    반환: [(형태소, 품사), ...] — Okt 태그셋 기준으로 통일

    통일 태그:
      Noun(명사), Verb(동사), Adjective(형용사),
      Adverb(부사), Josa(조사), Exclamation(감탄사),
      Punctuation(구두점), Foreign(외국어)
    """
    _init()

    if _backend == "kiwi":
        # kiwi 태그 → okt 태그로 매핑
        kiwi_to_okt = {
            "NNG": "Noun", "NNP": "Noun", "NNB": "Noun", "NR": "Noun", "NP": "Noun",
            "VV": "Verb", "VA": "Adjective", "VX": "Verb", "VCP": "Verb", "VCN": "Verb",
            "MAG": "Adverb", "MAJ": "Adverb",
            "IC": "Exclamation",
            "JKS": "Josa", "JKC": "Josa", "JKG": "Josa", "JKO": "Josa",
            "JKB": "Josa", "JKV": "Josa", "JKQ": "Josa", "JX": "Josa", "JC": "Josa",
            "SF": "Punctuation", "SP": "Punctuation", "SS": "Punctuation",
            "SE": "Punctuation", "SO": "Punctuation", "SW": "Punctuation",
            "SL": "Foreign", "SH": "Foreign", "SN": "Number",
        }
        tokens = _analyzer.tokenize(text)
        return [(t.form, kiwi_to_okt.get(t.tag, t.tag)) for t in tokens]

    else:
        # 정규식 폴백: 한글 단어만 추출, 전부 Noun 취급
        words = re.findall(r"[\uAC00-\uD7A3]+", text)
        return [(w, "Noun") for w in words]


# ────────────────────────────────────
# 명사 추출
# ────────────────────────────────────

def nouns(text: str) -> list:
    """명사만 추출"""
    _init()

    if _backend == "kiwi":
        tokens = _analyzer.tokenize(text)
        return [t.form for t in tokens if t.tag.startswith("NN")]
    else:
        return re.findall(r"[\uAC00-\uD7A3]{2,}", text)


# ────────────────────────────────────
# 형용사 추출 (감정 분석 핵심)
# ────────────────────────────────────

def adjectives(text: str) -> list:
    """형용사 원형 추출 (감정 키워드 포착용)"""
    tagged = pos(text)
    return [word for word, tag in tagged if tag == "Adjective"]


# ────────────────────────────────────
# 동사 추출
# ────────────────────────────────────

def verbs(text: str) -> list:
    """동사 원형 추출"""
    tagged = pos(text)
    return [word for word, tag in tagged if tag == "Verb"]


# ────────────────────────────────────
# 감정 형용사 사전 (형태소 원형 기반)
# ────────────────────────────────────

# 형태소 원형 매핑
EMOTION_ADJ_MAP = {
    # SAD
    "슬프다": "SAD", "외롭다": "SAD", "힘들다": "SAD", "아프다": "SAD",
    "우울하다": "SAD", "쓸쓸하다": "SAD", "괴롭다": "SAD", "허전하다": "SAD",
    "공허하다": "SAD", "무기력하다": "SAD", "서럽다": "SAD", "처지다": "SAD",
    "무섭다": "SAD", "두렵다": "SAD", "불안하다": "SAD", "지치다": "SAD",
    "차갑다": "SAD", "그립다": "SAD", "서운하다": "SAD", "답답하다": "SAD",
    "막막하다": "SAD", "암담하다": "SAD",

    # FIRM
    "싫다": "FIRM", "화나다": "FIRM", "짜증나다": "FIRM", "열받다": "FIRM",
    "밉다": "FIRM", "귀찮다": "FIRM", "어이없다": "FIRM", "한심하다": "FIRM",
    "역겹다": "FIRM", "분하다": "FIRM", "억울하다": "FIRM",

    # GENTLE
    "괜찮다": "GENTLE", "조심스럽다": "GENTLE", "부드럽다": "GENTLE",
    "편하다": "GENTLE", "따뜻하다": "GENTLE", "포근하다": "GENTLE",
    "잔잔하다": "GENTLE", "고요하다": "GENTLE", "평화롭다": "GENTLE",

    # CURIOUS
    "궁금하다": "CURIOUS", "신기하다": "CURIOUS", "흥미롭다": "CURIOUS",
    "재미있다": "CURIOUS", "신선하다": "CURIOUS", "놀랍다": "CURIOUS",
    "독특하다": "CURIOUS",

    # SARCASTIC
    "웃기다": "SARCASTIC", "황당하다": "SARCASTIC", "어처구니없다": "SARCASTIC",
    "기가 막히다": "SARCASTIC", "뜬금없다": "SARCASTIC",
    "어이없다": "SARCASTIC",

    # HAPPY (→ GENTLE로 매핑)
    "좋다": "GENTLE", "기쁘다": "GENTLE", "행복하다": "GENTLE",
    "즐겁다": "GENTLE", "설레다": "GENTLE", "반갑다": "GENTLE",
    "감사하다": "GENTLE",
}

# 활용형 매핑
EMOTION_CONJUGATED = {
    # SAD
    "슬퍼": "SAD", "외로워": "SAD", "힘들어": "SAD", "아파": "SAD",
    "우울해": "SAD", "괴로워": "SAD", "허전해": "SAD", "무서워": "SAD",
    "두려워": "SAD", "불안해": "SAD", "지쳐": "SAD", "지친": "SAD",
    "차가워": "SAD", "그리워": "SAD", "서운해": "SAD", "답답해": "SAD",
    "서러워": "SAD", "막막해": "SAD",

    # FIRM
    "싫어": "FIRM", "화나": "FIRM", "짜증나": "FIRM", "열받아": "FIRM",
    "미워": "FIRM", "귀찮아": "FIRM", "어이없어": "FIRM",

    # GENTLE
    "괜찮아": "GENTLE", "편해": "GENTLE", "따뜻해": "GENTLE",
    "포근해": "GENTLE", "고요해": "GENTLE",

    # CURIOUS
    "궁금해": "CURIOUS", "신기해": "CURIOUS", "재밌어": "CURIOUS",
    "놀라워": "CURIOUS",

    # SARCASTIC
    "웃겨": "SARCASTIC", "황당해": "SARCASTIC",
    "어이없": "SARCASTIC", "어이가": "SARCASTIC",

    # GENTLE (추가)
    "감사해": "GENTLE", "고마워": "GENTLE", "반가워": "GENTLE",
}


def detect_emotion_from_morphemes(text: str) -> str:
    """
    형태소 분석 기반 감정 감지.
    형용사 원형 → EMOTION_ADJ_MAP 매칭.

    반환: "SAD", "FIRM", "GENTLE", "CURIOUS", "SARCASTIC", "" (미감지)
    """
    _init()

    tagged = pos(text)

    # 1차: 형태소 분석 결과에서 형용사 원형 매칭
    for word, tag in tagged:
        if tag == "Adjective":
            if word + "다" in EMOTION_ADJ_MAP:
                return EMOTION_ADJ_MAP[word + "다"]
            if word in EMOTION_ADJ_MAP:
                return EMOTION_ADJ_MAP[word]

    # 2차: 활용형 직접 매칭 (폴백)
    for word, _ in tagged:
        if word in EMOTION_CONJUGATED:
            return EMOTION_CONJUGATED[word]

    # 3차: 원문에서 활용형 매칭
    for conj, emotion in EMOTION_CONJUGATED.items():
        if conj in text:
            return emotion

    return ""


def detect_intent_from_morphemes(text: str) -> str:
    """
    형태소 분석 기반 의도 감지.
    동사/형용사 어미 패턴으로 질문/선언/회피 등을 판단.

    반환: "QUESTION", "REFLECT", "DECLARE", "AVOID", "" (미감지)
    """
    _init()

    tagged = pos(text)

    # 회상/기억 관련 명사 (물음표보다 우선)
    memory_nouns = {"기억", "추억", "예전", "옛날", "그때", "과거", "회상"}
    memory_verbs = {"기억나다", "기억하다", "돌아보다", "회상하다", "떠오르다"}
    found_nouns = set(w for w, t in tagged if t == "Noun")
    found_verbs = set(w for w, t in tagged if t == "Verb")
    if (found_nouns & memory_nouns) or (found_verbs & memory_verbs):
        return "REFLECT"

    # 질문 패턴: 의문형 어미
    if text.strip().endswith("?") or text.strip().endswith("？"):
        return "QUESTION"

    # 회피 동사/부사
    avoid_words = {"모르다", "그만", "됐다", "귀찮다", "상관없다", "관심없다"}
    for word, tag in tagged:
        if tag in ("Verb", "Adjective"):
            if word + "다" in avoid_words or word in avoid_words:
                return "AVOID"

    return ""
