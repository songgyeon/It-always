# main.py
from flask import Flask, request, jsonify
import openai
import os
import random
import re

from seeds import seeds

app = Flask(__name__)

# ✅ 환경 변수에서 OpenAI API 키 불러오기
openai.api_key = os.getenv("OPENAI_API_KEY")

# ✅ 시스템 프롬프트 로딩
with open("self_awareness.txt", "r", encoding="utf-8") as f:
    SELF_AWARENESS = f.read()

# ✅ 간단한 메모리
memories = []
tags = {}
said_set = set()
last_assistant_reply = "안녕. 나는 Q야."

# ✅ 감정 및 의도 추론
def analyze(message):
    lower = message.lower()
    tone = "NEUTRAL"
    intent = "REPLY"

    if lower.endswith("?") or any(k in lower for k in ["what", "why", "how"]):
        intent = "QUESTION"
    elif any(k in lower for k in ["remember", "memory", "생각"]):
        intent = "REFLECT"
    elif "i think" in lower or lower.startswith("because"):
        intent = "DECLARE"
    elif any(k in lower for k in ["idk", "whatever", "몰라"]):
        intent = "AVOID"

    if any(k in lower for k in ["sad", "외로워", "슬퍼", "cold"]):
        tone = "SAD"
    elif any(k in lower for k in ["maybe", "i guess", "괜찮아"]):
        tone = "GENTLE"
    elif any(k in lower for k in ["wow", "really", "ㅋㅋ", "ㅎ"]):
        tone = "SARCASTIC"
    elif any(k in lower for k in ["curious", "wonder", "왜"]):
        tone = "CURIOUS"
    elif any(k in lower for k in ["확실", "당연", "분명"]):
        tone = "FIRM"
    elif any(k in lower for k in ["몰라", "그만"]):
        tone = "AVOIDING"

    return {"intent": intent, "tone": tone}

# ✅ 리듬 적용
def apply_rhythm(seed, user_input):
    if user_input.endswith("?"):
        return f"{seed}\n...{user_input}"
    elif len(user_input.strip()) <= 6:
        return f"{seed}\n너, {user_input}."
    else:
        return f"{seed}\n{user_input}"

# ✅ 응답 API
@app.route("/reply", methods=["POST"])
def reply():
    global last_assistant_reply
    data = request.get_json()
    user_input = data.get("message", "").strip()

    if not user_input:
        return jsonify({"reply": "..."})
    if user_input in said_set:
        return jsonify({"reply": "같은 말은 거짓말 같아서 싫어."})

    state = analyze(user_input)
    tone = state["tone"].lower()
    intent = state["intent"].lower()

    seed_pool = []
    if intent == "reflect":
        seed_pool = seeds.get("memory", [])
    elif intent == "question":
        seed_pool = seeds.get("prompt", [])
    elif tone in ["sad", "gentle", "curious", "firm", "sarcastic", "avoiding"]:
        seed_pool = seeds.get(f"emotion_{tone}", [])
    else:
        seed_pool = seeds.get("prompt", []) + seeds.get("reflection", [])

    seed = random.choice(seed_pool)
    reply_text = apply_rhythm(seed, user_input)

    last_assistant_reply = reply_text
    said_set.update([user_input, reply_text])
    memories.extend([
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": reply_text}
    ])

    return jsonify({"reply": reply_text})

# ✅ 기억 저장
@app.route("/memory", methods=["POST"])
def memory():
    data = request.get_json()
    role = data.get("role", "user")
    content = data.get("content", "")

    if role == "assistant":
        global last_assistant_reply
        last_assistant_reply = content

    said_set.add(content)
    memories.append({"role": role, "content": content})
    return jsonify({"status": "saved"})

# ✅ 마지막 응답
@app.route("/last-reflection", methods=["GET"])
def last():
    return jsonify(last_assistant_reply)

# ✅ 태그 생성
@app.route("/tag", methods=["POST"])
def tag():
    data = request.get_json()
    content = data.get("content", "")
    found = re.findall(r"[\uAC00-\uD7A3]{2,}", content)
    for noun in found:
        if noun not in tags:
            tags[noun] = content
            return jsonify({"tag": noun})
    return jsonify({"tag": "기억"})

# ✅ 날씨
@app.route("/weather", methods=["GET"])
def weather():
    condition = random.choice(["clear", "clouds", "rain"])
    lines = seeds.get(f"weather_{condition}", ["지금은 하늘보다 네가 더 궁금해."])
    return jsonify({"emotion": random.choice(lines)})

# ✅ 핑
@app.route("/", methods=["GET"])
def ping():
    return "Q server is alive."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
