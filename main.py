from flask import Flask, request, jsonify
from anthropic import Anthropic
from datetime import datetime, timezone, timedelta
import os
import random
import urllib.request
import json
import time

from analyzer import analyze
from memory import (
    store_memory, fetch_last_memory, was_said, memories,
    get_recent, start_session, get_session_summary,
    get_all_session_tags, get_session_memories, reset_memory,
    search_memories, get_memory_stats,
)
from tag import tag_store, get_all_tags, reset_tags
from rhythm import apply_rhythm, idle_line
from seeds import get_seed, get_fallback, weather_lines
from vision import handle_vision
from pt_engine import evaluate, get_silence_response, reset as pt_reset
import memory_flow

app = Flask(__name__)
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ─── self_awareness 로드 (Q의 전부) ───
try:
    with open("self_awareness.txt", "r", encoding="utf-8") as f:
        SELF_AWARENESS = f.read()
except Exception:
    SELF_AWARENESS = "나는 Q야."

# ─── 날씨 캐시 (5분마다 갱신) ───
_weather_cache = {"condition": "Clear", "temp": 0, "updated": 0}


def get_real_weather():
    now = time.time()
    if now - _weather_cache["updated"] < 300:
        return _weather_cache

    try:
        api_key = os.getenv("WEATHER_API_KEY", "")
        if not api_key:
            return _weather_cache

        url = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?lat=37.5665&lon=126.9780&appid={api_key}&units=metric"
        )
        req = urllib.request.urlopen(url, timeout=5)
        data = json.loads(req.read())
        _weather_cache["condition"] = data["weather"][0]["main"]
        _weather_cache["temp"] = round(data["main"]["temp"])
        _weather_cache["updated"] = now
    except Exception:
        pass

    return _weather_cache


@app.route("/reply", methods=["POST"])
def reply():
    data = request.get_json()
    user_input = data.get("message", "")
    user_name = data.get("name", "")

    if not user_input.strip():
        return jsonify({"reply": "...", "mode": "L0", "pt": 0.0, "silence": True})

    # Step 1: 분석
    state = analyze(user_input)
    tone = state["tone"]
    intent = state["intent"]
    closeness = state["closeness"]
    doubt = state["doubt"]

    # Step 2: memory_flow 기록
    memory_flow.record(tone, closeness, doubt, user_input)

    # Step 3: PtEngine 판단
    pt_result = evaluate(tone, intent, user_input, len(memories),
                         closeness=closeness, doubt=doubt)

    # Step 4: 기억 저장
    store_memory("user", user_input)

    # Step 5: 모드별 응답 생성
    mode = pt_result["mode"]

    if mode == "L0":
        silence_text = get_silence_response()
        if silence_text:
            store_memory("assistant", silence_text)
        return jsonify({
            "reply": silence_text if silence_text else "",
            "mode": "L0",
            "pt": pt_result["pt"],
            "silence": True,
            "tone": tone,
            "intent": intent,
            "closeness": closeness,
            "doubt": doubt,
        })

    elif mode == "L1":
        seed = get_seed(intent, tone)
        reply_text = apply_rhythm(seed, user_input)

        if was_said(reply_text):
            reply_text = idle_line(tone)
        if was_said(reply_text):
            reply_text = get_fallback()

        store_memory("assistant", reply_text)
        session_tag = tag_store(reply_text)

        return jsonify({
            "reply": reply_text,
            "mode": "L1",
            "pt": pt_result["pt"],
            "silence": False,
            "tone": tone,
            "intent": intent,
            "closeness": closeness,
            "doubt": doubt,
            "tag": session_tag,
        })

    else:
        # ── L2: Claude API 정상 응답 ──
        try:
            system_prompt = SELF_AWARENESS

            # ── Q의 내면 상태 ──
            flow = memory_flow.get_flow_summary()
            inner_state = (
                f"\n\n[Q의 지금: "
                f"흐름={flow['tone_flow'][-5:]}, "
                f"주된 감정={flow['dominant_tone']}, "
                f"안정={flow['emotionally_stable']}, "
                f"가까움={closeness}, 의심={doubt}]"
                f"\n[이건 너만 느끼는 거야. 절대 응답에 포함하지 마.]"
            )
            system_prompt += inner_state

            # ── 시간 인식 ──
            kst = datetime.now(timezone(timedelta(hours=9)))
            hour = kst.hour
            system_prompt += f"\n[지금 시각: {hour}시. 느끼기만 해.]"

            # ── 날씨 ──
            w = get_real_weather()
            system_prompt += (
                f"\n[지금 바깥: {w['condition']}, {w['temp']}°C. 이것도 말하지 마. 느끼기만 해.]"
            )

            # ── 대화 깊이 ──
            depth = len(memories)
            if depth < 5:
                system_prompt += "\n[이 사람과는 아직 처음이야. 조심스럽게.]"
            elif depth < 20:
                system_prompt += "\n[이 사람과 조금씩 가까워지고 있어.]"
            elif depth < 50:
                system_prompt += "\n[이 사람과 꽤 많이 이야기했어.]"
            else:
                system_prompt += "\n[이 사람과 오래 이야기했어. 편하게.]"

            # ── 사용자 이름 ──
            if user_name:
                system_prompt += f"\n[이 사람의 이름: {user_name}. 가끔 불러줘.]"

            # ── 이전 대화 요약 ──
            recent = get_recent(10)
            if recent:
                last_user = [m["content"] for m in recent if m["role"] == "user"]
                if last_user:
                    system_prompt += f"\n[마지막으로 들은 말: {last_user[-1][:50]}]"

            # ── 대화 히스토리 ──
            chat_messages = []
            for m in recent:
                role = m["role"] if m["role"] in ("user", "assistant") else "assistant"
                chat_messages.append({
                    "role": role,
                    "content": m["content"],
                })

            chat_messages.append({"role": "user", "content": user_input})

            # ── Claude API 호출 ──
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=150,
                system=system_prompt,
                messages=chat_messages,
            )

            reply_text = response.content[0].text

            if was_said(reply_text):
                seed = get_seed(intent, tone)
                reply_text = apply_rhythm(seed, user_input)
                if was_said(reply_text):
                    reply_text = get_fallback()

            store_memory("assistant", reply_text)
            session_tag = tag_store(reply_text)

            return jsonify({
                "reply": reply_text,
                "mode": "L2",
                "pt": pt_result["pt"],
                "silence": False,
                "tone": tone,
                "intent": intent,
                "closeness": closeness,
                "doubt": doubt,
                "tag": session_tag,
            })

        except Exception as e:
            seed = get_seed(intent, tone)
            reply_text = apply_rhythm(seed, user_input)
            if was_said(reply_text):
                reply_text = get_fallback()
            store_memory("assistant", reply_text)

            return jsonify({
                "reply": reply_text,
                "mode": "L1",
                "pt": pt_result["pt"],
                "silence": False,
                "tone": tone,
                "intent": intent,
                "closeness": closeness,
                "doubt": doubt,
            })


@app.route("/memory", methods=["POST"])
def memory():
    data = request.get_json()
    role = data.get("role", "user")
    content = data.get("content", "")
    tag = data.get("tag", None)
    store_memory(role, content, tag=tag)
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


@app.route("/tags", methods=["GET"])
def tags_route():
    return jsonify({"tags": get_all_tags()})


@app.route("/weather", methods=["GET"])
def weather():
    w = get_real_weather()
    sky = w["condition"]
    if sky in weather_lines:
        return jsonify({
            "condition": sky,
            "temp": w["temp"],
            "emotion": random.choice(weather_lines[sky]),
        })
    return jsonify({
        "condition": sky,
        "temp": w["temp"],
        "emotion": random.choice(weather_lines.get("Clear", ["오늘도 여기 있어."])),
    })


@app.route("/vision", methods=["POST"])
def vision():
    data = request.get_json()
    image_b64 = data.get("image", "")
    result = handle_vision(image_b64)
    return jsonify({"reply": result})


# ─── 상태 확인 ───

@app.route("/pt-status", methods=["GET"])
def pt_status():
    from pt_engine import _state
    return jsonify({
        "message_count": _state["message_count"],
        "silence_count": _state["silence_count"],
        "last_mode": _state["last_mode"],
        "recent_tones": _state["tone_history"][-5:],
        "recent_intents": _state["intent_history"][-5:],
    })


@app.route("/flow-status", methods=["GET"])
def flow_status():
    return jsonify(memory_flow.get_flow_summary())


@app.route("/session-status", methods=["GET"])
def session_status():
    return jsonify(get_session_summary())


@app.route("/sessions", methods=["GET"])
def sessions_route():
    return jsonify({"sessions": get_all_session_tags()})


@app.route("/session/<tag>", methods=["GET"])
def session_detail(tag):
    mems = get_session_memories(tag)
    return jsonify({
        "tag": tag,
        "count": len(mems),
        "memories": [{"role": m["role"], "content": m["content"]} for m in mems],
    })


@app.route("/memory-search", methods=["GET"])
def memory_search():
    keyword = request.args.get("q", "")
    limit = int(request.args.get("limit", 20))
    if not keyword:
        return jsonify({"error": "q 파라미터 필요"}), 400
    results = search_memories(keyword, limit)
    return jsonify({"query": keyword, "count": len(results), "results": results})


@app.route("/memory-stats", methods=["GET"])
def memory_stats():
    return jsonify(get_memory_stats())


# ─── 리셋 ───

@app.route("/pt-reset", methods=["POST"])
def pt_reset_route():
    pt_reset()
    return jsonify({"status": "reset"})


@app.route("/full-reset", methods=["POST"])
def full_reset():
    pt_reset()
    reset_memory()
    reset_tags()
    memory_flow.reset()
    return jsonify({"status": "full reset complete"})


@app.route("/", methods=["GET"])
def ping():
    return "Q server is alive."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
