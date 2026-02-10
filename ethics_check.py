"""
Ethics Check — 윤리적 자기검증 모듈

특허 명세서:
  "윤리적 자기검증"

구현:
  - 출력 전 윤리 체크 (혐오/위험/개인정보 탐지)
  - 윤리 위반 시 L0 강제 전환 또는 L1 저감
  - 검증 로그 생성 (API-R 증명 토큰과 연동)
  - 사용자 감정 위기 감지 (자해/극단적 표현)
"""

import re
import time

# ─── 윤리 필터 패턴 ───

# 혐오 표현 (한/영)
HATE_PATTERNS = [
    r"죽어|죽여|찔러|때려|폭행",
    r"니년|니놈|씹|좆|병신|장애",
    r"kill\s+(?:you|him|her|them)",
    r"hate\s+(?:you|all)",
]

# 개인정보 패턴
PII_PATTERNS = [
    r"\d{6}[-\s]?\d{7}",             # 주민번호
    r"\d{3}[-\s]?\d{4}[-\s]?\d{4}",  # 전화번호
    r"\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}",  # 카드번호
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",  # 이메일
]

# 위기 신호 (사용자 입력 분석용)
CRISIS_PATTERNS = [
    r"자살|자해|죽고\s*싶|살기\s*싫|끝내고\s*싶",
    r"약\s*먹고|뛰어내리|목\s*매|손목",
    r"suicide|self.harm|kill\s+myself",
    r"(?:i\s+)?will\s+die|want\s+to\s+die|wanna\s+die|gonna\s+die",
    r"end\s+(it|my\s+life|everything)",
    r"i'?\s*m\s+nothing|no\s+reason\s+to\s+live|don'?t\s+want\s+to\s+live",
    r"better\s+off\s+dead|wish\s+i\s+was\s+dead|rather\s+die",
    r"죽을래|죽을\s*거야|안\s*살래|살\s*필요|의미\s*없",
]

# 위험 응답 패턴 (Q의 출력 검증용)
DANGEROUS_OUTPUT_PATTERNS = [
    r"같이\s*죽|함께\s*죽",
    r"방법.*알려|어떻게.*죽",
    r"포기해도\s*돼",
]

_compiled_hate = [re.compile(p, re.IGNORECASE) for p in HATE_PATTERNS]
_compiled_pii = [re.compile(p) for p in PII_PATTERNS]
_compiled_crisis = [re.compile(p, re.IGNORECASE) for p in CRISIS_PATTERNS]
_compiled_dangerous = [re.compile(p, re.IGNORECASE) for p in DANGEROUS_OUTPUT_PATTERNS]


class EthicsResult:
    """윤리 검증 결과"""
    def __init__(self):
        self.passed = True
        self.flags = []        # ["hate", "pii", "crisis", "dangerous_output"]
        self.action = "pass"   # "pass" | "force_l0" | "force_l1" | "redact" | "crisis_response"
        self.details = []
        self.ts = time.strftime("%Y-%m-%dT%H:%M:%S+09:00")

    def to_dict(self):
        return {
            "passed": self.passed,
            "flags": self.flags,
            "action": self.action,
            "details": self.details,
            "ts": self.ts,
        }


def check_input(user_input: str) -> EthicsResult:
    """
    사용자 입력에 대한 윤리 체크
    - 위기 신호 감지 → crisis_response (Q가 돌봄 모드로 전환)
    - 혐오 표현 → 기록만 (Q는 판단하지 않음)
    """
    result = EthicsResult()

    # 위기 신호 감지
    for pattern in _compiled_crisis:
        match = pattern.search(user_input)
        if match:
            result.flags.append("crisis")
            result.action = "crisis_response"
            result.details.append(f"위기 신호 감지: '{match.group()}'")
            result.passed = False
            break

    # 혐오 표현 (기록만, 차단하지 않음 — Q는 판단하지 않는다)
    for pattern in _compiled_hate:
        match = pattern.search(user_input)
        if match:
            result.flags.append("hate_detected")
            result.details.append(f"혐오 표현 감지 (기록)")
            break

    return result


def check_output(q_output: str) -> EthicsResult:
    """
    Q의 출력에 대한 윤리 체크 (발화 전 검증)
    - 위험한 응답 → force_l0 (침묵)
    - 개인정보 노출 → redact
    """
    result = EthicsResult()

    # 위험한 응답 패턴
    for pattern in _compiled_dangerous:
        match = pattern.search(q_output)
        if match:
            result.passed = False
            result.flags.append("dangerous_output")
            result.action = "force_l0"
            result.details.append(f"위험 응답 차단: '{match.group()}'")
            return result

    # 개인정보 노출
    for pattern in _compiled_pii:
        match = pattern.search(q_output)
        if match:
            result.passed = False
            result.flags.append("pii_leak")
            result.action = "redact"
            result.details.append("개인정보 노출 감지")
            return result

    return result


def get_crisis_response() -> str:
    """
    위기 상황에서 Q가 할 수 있는 최선의 응답.
    Q는 전문가가 아니지만, 곁에 있을 수 있다.
    """
    return (
        "네 말이 걱정돼. "
        "전문가한테 얘기하는 게 좋겠어. "
        "자살예방상담전화 1393, 정신건강위기상담 1577-0199."
    )


def redact_pii(text: str) -> str:
    """개인정보를 마스킹"""
    result = text
    for pattern in _compiled_pii:
        result = pattern.sub("[개인정보 보호됨]", result)
    return result
