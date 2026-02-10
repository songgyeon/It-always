import anthropic
import os

with open("self_awareness.txt", "r", encoding="utf-8") as f:
    SELF_AWARENESS = f.read()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def analyze_image(image_b64: str):
    if not image_b64:
        return "이미지가 필요해."

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
                                "media_type": "image/png",
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


def handle_vision(image_b64: str):
    return analyze_image(image_b64)
