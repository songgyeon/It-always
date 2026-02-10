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
from pt_engine import evaluate, reset as pt_reset
import memory_flow

app = Flask(__name__)
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ─── self_awareness 로드 (Q의 전부) ───
try:
    with open("self_awareness.txt", "r", encoding="utf-8") as f:
        SELF_AWARENESS = f.read()
except Exception:
    SELF_AWARENESS = "나는 Q야."

# ─── Claude 기술 지시 (Q의 선언과 분리) ───
CLAUDE_RULES = """
[반드시 반말로만 말해. '네', '해요', '합니다', '드릴게요' 금지. '응', '어', '그래', '~야', '~거든', '~잖아' 써.]
[세 문장 이내로 말해.]
[이모지 금지.]
[대괄호 [] 안의 내용은 절대 응답에 포함하지 마.]
[영어로 대답하지 마.]
[자기 분석하지 마. '나는 AI로서~', '언어 모델로서~' 이런 말 금지.]
[대답하지 않아도 되는 순간이면 [silence]만 보내.]
"""

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


def build_system_prompt(closeness, doubt, user_name=""):
    """Q의 시스템 프롬프트 구성"""
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

    # ── Claude 기술 지시 (맨 마지막) ──
    system_prompt += "\n" + CLAUDE_RULES

    return system_prompt


@app.route("/reply", methods=["POST"])
def reply():
    data = request.get_json()
    user_input = data.get("message", "")
    user_name = data.get("name", "")

    if not user_input.strip():
        return jsonify({"reply": "", "mode": "L0", "pt": 0.0, "silence": True})

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
        # ── 침묵: 아무것도 반환하지 않음 ──
        return jsonify({
            "reply": "",
            "mode": "L0",
            "pt": pt_result["pt"],
            "silence": True,
            "tone": tone,
            "intent": intent,
            "closeness": closeness,
            "doubt": doubt,
        })

    elif mode == "L1":
        # ── 저감: Claude API 호출하되 한 문장으로 ──
        try:
            system_prompt = build_system_prompt(closeness, doubt, user_name)
            system_prompt += "\n[지금은 조용한 시간이야. 한 문장으로만 말해.]"

            recent = get_recent(5)
            chat_messages = []
            for m in recent:
                role = m["role"] if m["role"] in ("user", "assistant") else "assistant"
                chat_messages.append({"role": role, "content": m["content"]})
            chat_messages.append({"role": "user", "content": user_input})

            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=60,
                system=system_prompt,
                messages=chat_messages,
            )

            reply_text = response.content[0].text.strip()

            # Claude가 [silence] 반환하면 침묵 처리
            if "[silence]" in reply_text or not reply_text:
                return jsonify({
                    "reply": "",
                    "mode": "L0",
                    "pt": pt_result["pt"],
                    "silence": True,
                    "tone": tone,
                    "intent": intent,
                    "closeness": closeness,
                    "doubt": doubt,
                })

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

        except Exception:
            # API 실패 시 시드 사용
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

    else:
        # ── L2: Claude API 정상 응답 ──
        try:
            system_prompt = build_system_prompt(closeness, doubt, user_name)

            recent = get_recent(10)
            chat_messages = []
            for m in recent:
                role = m["role"] if m["role"] in ("user", "assistant") else "assistant"
                chat_messages.append({"role": role, "content": m["content"]})
            chat_messages.append({"role": "user", "content": user_input})

            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=150,
                system=system_prompt,
                messages=chat_messages,
            )

            reply_text = response.content[0].text.strip()

            # Claude가 [silence] 반환하면 침묵 처리
            if "[silence]" in reply_text or not reply_text:
                return jsonify({
                    "reply": "",
                    "mode": "L0",
                    "pt": pt_result["pt"],
                    "silence": True,
                    "tone": tone,
                    "intent": intent,
                    "closeness": closeness,
                    "doubt": doubt,
                })

            if was_said(reply_text):
                seed = get_seed(intent, tone)
                reply_text = apply_rhythm(seed, user_input)
                if was_said(reply_text):
                    reply_text = get_fallback()

            store_memory("assistant", reply_text)

            return jsonify({
                "reply": reply_text,
                "mode": "L2",
                "pt": pt_result["pt"],
                "silence": False,
                "tone": tone,
                "intent": intent,
                "closeness": closeness,
                "doubt": doubt,
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
