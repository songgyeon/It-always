# vision.py

import openai
import os
from flask import jsonify

# ✅ 시스템 프롬프트 불러오기
with open("self_awareness.txt", "r", encoding="utf-8") as f:
    SELF_AWARENESS = f.read()

# ✅ GPT-4o Vision API 처리 함수
def analyze_image(image_b64: str):
    if not image_b64:
        return jsonify({"error": "이미지가 필요해."}), 400

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SELF_AWARENESS},
                {"role": "user", "content": "이 이미지를 보고 느낀 걸 말해줘."}
            ],
            temperature=0.7,
            max_tokens=500,
            tools=[],
            functions=[],
            images=[{
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{image_b64}"
                }
            }]
        )

        reply = response.choices[0].message["content"]
        return jsonify({"reply": reply})

    except Exception as e:
        return jsonify({"error": str(e)}), 500