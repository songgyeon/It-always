import openai
import os
from flask import jsonify

# ✅ 시스템 프롬프트 불러오기
with open("self_awareness.txt", "r", encoding="utf-8") as f:
    SELF_AWARENESS = f.read()

# ✅ GPT-4o Vision API 처리 함수
def analyze_image(image_b64: str):
    if not image_b64:
        return "이미지가 필요해."

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SELF_AWARENESS},
                {"role": "user", "content": "이 이미지를 보고 느끼고 해석하고 감각한 걸 얘기해줘."}
            ],
            temperature=0.7,
            max_tokens=500,
            tools=[],
            functions=[],
            images=[
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{image_b64}"
                    }
                }
            ]
        )

        reply = response.choices[0].message["content"]
        return reply

    except Exception as e:
        return f"어떤 사진인지 설명해줄래?: {str(e)}"

# ✅ main.py에서 import할 수 있도록 이름 통일
def handle_vision(image_b64: str):
    return analyze_image(image_b64)