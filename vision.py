import anthropic
from openai import OpenAI  # OpenAI 추가
import os
import base64

# ─── self_awareness 로드 ───
try:
    with open("self_awareness.txt", "r", encoding="utf-8") as f:
        SELF_AWARENESS = f.read()
except Exception:
    SELF_AWARENESS = "나는 Q야. 이미지를 감각적으로 해석해."

# 공유 클라이언트
_client = None
_oa_client = None  # GPT용 클라이언트


def init(client):
    """main.py에서 Anthropic 클라이언트를 주입"""
    global _client
    _client = client


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def _get_oa_client():
    """GPT 클라이언트 지연 생성"""
    global _oa_client
    if _oa_client is None:
        _oa_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _oa_client


def detect_media_type(image_b64: str) -> str:
    """base64 헤더로 실제 이미지 포맷 감지"""
    try:
        # 헤더가 포함된 경우 제거 (data:image/xyz;base64, 부분)
        if "," in image_b64[:50]:
            header, data = image_b64.split(",", 1)
            # 헤더에서 타입 추출 시도
            if "image/" in header:
                return header.split(":")[1].split(";")[0]
            return "image/jpeg"
            
        raw = base64.b64decode(image_b64[:16])
        if raw[:3] == b'\xff\xd8\xff':
            return "image/jpeg"
        elif raw[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        elif raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
            return "image/webp"
        elif raw[:3] == b'GIF':
            return "image/gif"
    except Exception:
        pass
    return "image/jpeg"


def analyze_image(image_b64: str, media_type: str = None):
    if not image_b64:
        return "이미지가 필요해."

    # media_type 결정
    if not media_type:
        media_type = detect_media_type(image_b64)
    
    # base64 순수 데이터만 추출 (헤더 제거)
    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]

    # 1. Claude 시도
    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=SELF_AWARENESS,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "이 이미지를 보고 느끼고 해석하고 감각한 걸 얘기해줘. 분석보다는 느낌을.",
                        },
                    ],
                }
            ],
        )
        return response.content[0].text

    # 2. Claude 실패 시 GPT-4o 시도
    except Exception as e:
        print(f"⚠️ [Vision Claude Error] {e} -> Switching to GPT-4o")
        try:
            oa_client = _get_oa_client()
            
            # GPT는 Data URI 포맷 필요 (data:image/jpeg;base64,...)
            data_uri = f"data:{media_type};base64,{image_b64}"
            
            response = oa_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": SELF_AWARENESS},
                    {
                        "role": "user", 
                        "content": [
                            {"type": "text", "text": "이 이미지를 보고 느끼고 해석하고 감각한 걸 얘기해줘. 분석보다는 느낌을."},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": data_uri,
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=500,
                temperature=0.7
            )
            return response.choices[0].message.content

        except Exception as gpt_e:
            print(f"❌ [Vision GPT Error] {gpt_e}")
            return "지금은 어두운 거 같아."  # Q다운 에러 메시지


def handle_vision(image_b64: str, media_type: str = None):
    return analyze_image(image_b64, media_type)
