import anthropic
import os
import base64

# self_awareness 로드 (main.py와 동일 패턴)
try:
    with open("self_awareness.txt", "r", encoding="utf-8") as f:
        SELF_AWARENESS = f.read()
except Exception:
    SELF_AWARENESS = "나는 Q야."

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def detect_media_type(image_b64: str) -> str:
    """base64 헤더로 실제 이미지 포맷 감지"""
    try:
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
    return "image/jpeg"  # 앱에서 JPEG로 보내므로 기본값


def analyze_image(image_b64: str, media_type: str = None):
    if not image_b64:
        return "이미지가 필요해."

    # media_type 결정: 클라이언트 지정 > 자동 감지
    if not media_type:
        media_type = detect_media_type(image_b64)

    try:
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
                            "text": "이 이미지를 보고 느끼고 해석하고 감각한 걸 얘기해줘.",
                        },
                    ],
                }
            ],
        )
        return response.content[0].text
    except Exception as e:
        return f"❌ 오류 발생: {str(e)}"


def handle_vision(image_b64: str, media_type: str = None):
    return analyze_image(image_b64, media_type)
