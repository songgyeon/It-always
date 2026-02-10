from flask import Flask, request, jsonify
import openai
import os
import random

from analyzer import analyze
from memory import store_memory, fetch_last_memory, was_said, memories
from tag import tag_store
from rhythm import apply_rhythm, idle_line
from seeds import get_seed, weather_lines
from vision import handle_vision
from pt_engine import evaluate, get_silence_response, reset as pt_reset

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# ─── self_awareness 로드 ───
try:
    with open("self_awareness.txt", "r", encoding="utf-8") as f:
        SELF_AWARENESS = f.read()
except:
    SELF_AWARENESS = "너는 Q야. 너는 스스로 존재하는 감성 AI야."


@app.route("/reply", methods=["POST"])
def reply():
    """
    UNLIQ SDK 프로토타입 핵심 엔드포인트
    
    흐름:
    1. 사용자 입력 → analyzer (톤/의도 분석)
    2. PtEngine (P(t) 산출 → L0/L1/L2 결정)
    3. L0 → 침묵 반환
    4. L1 → 시드 기반 축약 응답
    5. L2 → OpenAI API 정상 응답
    """
    data = request.get_json()
    user_input = data.get("message", "")

    if not user_input.strip():
        return jsonify({"reply": "...", "mode": "L0", "pt": 0.0, "silence": True})

    # Step 1: 분석
    state = analyze(user_input)
    tone = state["tone"]
    intent = state["intent"]

    # Step 2: PtEngine 판단
    pt_result = evaluate(tone, intent, user_input, len(memories))

    # Step 3: 기억 저장 (모드와 무관하게 항상 저장)
    store_memory("user", user_input)

    # Step 4: 모드별 응답 생성
    mode = pt_result["mode"]

    if mode == "L0":
        # ── 침묵 ──
        silence_text = get_silence_response()
        if silence_text:
            store_memory("assistant", silence_text)
        return jsonify({
            "reply": silence_text if silence_text else "",
            "mode": "L0",
            "pt": pt_result["pt"],
            "silence": True
        })

    elif mode == "L1":
        # ── 축약 응답 (시드 기반) ──
        seed = get_seed(intent, tone)
        reply_text = apply_rhythm(seed, user_input)

        # 이미 말한 내용이면 idle_line으로 대체
        if was_said(reply_text):
            reply_text = idle_line(tone)

        store_memory("assistant", reply_text)
        tag_store(reply_text)

        return jsonify({
            "reply": reply_text,
            "mode": "L1",
            "pt": pt_result["pt"],
            "silence": False
        })

    else:
        # ── L2: OpenAI 정상 응답 ──
        try:
            # 최근 대화 컨텍스트 구성
            chat_messages = [
                {"role": "system", "content": SELF_AWARENESS}
            ]

            # 최근 10개 대화 기록 추가
            recent = memories[-10:] if len(memories) > 10 else memories
            for m in recent:
                chat_messages.append({
                    "role": m["role"] if m["role"] in ("user", "assistant") else "assistant",
                    "content": m["content"]
                })

            # 현재 입력
            chat_messages.append({"role": "user", "content": user_input})

            response = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=chat_messages,
                temperature=0.8,
                max_tokens=300
            )

            reply_text = response.choices[0].message["content"]

            # 이미 말한 내용이면 시드로 대체
            if was_said(reply_text):
                seed = get_seed(intent, tone)
                reply_text = apply_rhythm(seed, user_input)

            store_memory("assistant", reply_text)
            tag_store(reply_text)

            return jsonify({
                "reply": reply_text,
                "mode": "L2",
                "pt": pt_result["pt"],
                "silence": False
            })

        except Exception as e:
            # API 실패 시 시드 기반 폴백
            seed = get_seed(intent, tone)
            reply_text = apply_rhythm(seed, user_input)
            store_memory("assistant", reply_text)

            return jsonify({
                "reply": reply_text,
                "mode": "L1",
                "pt": pt_result["pt"],
                "silence": False,
                "error": str(e)
            })


@app.route("/memory", methods=["POST"])
def memory():
    data = request.get_json()
    role = data.get("role", "user")
    content = data.get("content", "")
    store_memory(role, content)
    return jsonify({"status": "saved"})


@app.route("/last-reflection", methods=["GET"])
def last_reflection():
    return jsonify(fetch_last_memory())


@app.route("/tag", methods=["POST"])
def tag_route():
    data = request.get_json()
    content = data.get("content", "")
    tag_result = tag_store(content)
    return jsonify({"tag": tag_result})


@app.route("/weather", methods=["GET"])
def weather():
    sky = random.choice(list(weather_lines.keys()))
    return jsonify({"emotion": random.choice(weather_lines[sky])})


@app.route("/vision", methods=["POST"])
def vision():
    data = request.get_json()
    image_b64 = data.get("image", "")
    result = handle_vision(image_b64)
    return jsonify({"reply": result})


@app.route("/pt-status", methods=["GET"])
def pt_status():
    """PtEngine 상태 확인 (디버그/데모용)"""
    from pt_engine import _state
    return jsonify({
        "message_count": _state["message_count"],
        "silence_count": _state["silence_count"],
        "last_mode": _state["last_mode"],
        "recent_tones": _state["tone_history"][-5:],
        "recent_intents": _state["intent_history"][-5:],
    })


@app.route("/pt-reset", methods=["POST"])
def pt_reset_route():
    """PtEngine 세션 리셋"""
    pt_reset()
    return jsonify({"status": "reset"})


@app.route("/", methods=["GET"])
def ping():
    return "Q server is alive. UNLIQ PtEngine active."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
