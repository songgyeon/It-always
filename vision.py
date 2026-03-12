import anthropic
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


def init(client):
    """main.py에서 Anthropic 클라이언트를 주입"""
    global _client
    _client = client


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def detect_media_type(image_b64: str) -> str:
    """base64 헤더로 실제 이미지 포맷 감지"""
    try:
        if "," in image_b64[:50]:
            header, data = image_b64.split(",", 1)
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

    if not media_type:
        media_type = detect_media_type(image_b64)

    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]

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

    except Exception as e:
        print(f"⚠️ [Vision Claude Error] {e}")
        return "지금은 어두운 거 같아."


def handle_vision(image_b64: str, media_type: str = None):
    return analyze_image(image_b64, media_type)
