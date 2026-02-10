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
    store_memory, fetch_last_memory, was_said,
    get_recent, start_session, get_session_summary,
    get_session_memories, reset_memory,
    search_memories, get_memory_stats, get_memory_count,
)
from tag import tag_store, get_all_tags, reset_tags
from rhythm import apply_rhythm, idle_line
from seeds import get_seed, get_fallback, weather_lines
from vision import handle_vision
from pt_engine import evaluate, reset as pt_reset, get_user_status
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


def build_system_prompt(closeness, doubt, user_name="", user_id="default"):
    """Q의 시스템 프롬프트 구성"""
    system_prompt = SELF_AWARENESS

    # ── Q의 내면 상태 ──
    flow = memory_flow.get_flow_summary(user_id)
    inner_state = (
        f"\n\n[Q의 지금: "
        f"흐름={flow['tone_flow'][-5:]}, "
        f"주된 감정={flow['dominant_tone']}, "
        f"안정={flow['emotionally_stable']}, "
        f"가까움={closeness}, 의심={doubt}]"
        f"\n[이건 너만 느끼는 거야. 절대 응답에 포함하지 마.]"
    )
    system_prompt += inner_state

    # ── 시간 인식 (KST 고정) ──
    kst = datetime.now(timezone(timedelta(hours=9)))
    hour = kst.hour
    system_prompt += f"\n[지금 시각: {hour}시. 느끼기만 해.]"

    # ── 날씨 ──
    w = get_real_weather()
    system_prompt += (
        f"\n[지금 바깥: {w['condition']}, {w['temp']}°C. 이것도 말하지 마. 느끼기만 해.]"
    )

    # ── 대화 깊이 (사용자별) ──
    depth = get_memory_count(user_id)
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
    recent = get_recent(10, user_id=user_id)
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
    user_id = data.get("user_id", "default")

    if not user_input.strip():
        return jsonify({"reply": "", "mode": "L0", "pt": 0.0, "silence": True})

    # Step 1: 분석
    state = analyze(user_input)
    tone = state["tone"]
    intent = state["intent"]
    closeness = state["closeness"]
    doubt = state["doubt"]

    # Step 2: memory_flow 기록
    memory_flow.record(tone, closeness, doubt, user_input, user_id=user_id)

    # Step 3: PtEngine 판단
    memory_count = get_memory_count(user_id)
    pt_result = evaluate(tone, intent, user_input, memory_count,
                         closeness=closeness, doubt=doubt, user_id=user_id)

    # Step 4: 기억 저장
    store_memory("user", user_input, user_id=user_id)

    # Step 5: 모드별 응답 생성
    mode = pt_result["mode"]

    if mode == "L0":
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
        try:
            system_prompt = build_system_prompt(closeness, doubt, user_name,
                                                user_id=user_id)
            system_prompt += "\n[지금은 조용한 시간이야. 한 문장으로만 말해.]"

            recent = get_recent(5, user_id=user_id)
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

            store_memory("assistant", reply_text, user_id=user_id)

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
            seed = get_seed(intent, tone)
            reply_text = apply_rhythm(seed, user_input)
            if was_said(reply_text, user_id=user_id):
                reply_text = get_fallback()
            store_memory("assistant", reply_text, user_id=user_id)

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
            system_prompt = build_system_prompt(closeness, doubt, user_name,
                                                user_id=user_id)

            recent = get_recent(10, user_id=user_id)
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

            if was_said(reply_text, user_id=user_id):
                seed = get_seed(intent, tone)
                reply_text = apply_rhythm(seed, user_input)
                if was_said(reply_text, user_id=user_id):
                    reply_text = get_fallback()

            store_memory("assistant", reply_text, user_id=user_id)

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
            if was_said(reply_text, user_id=user_id):
                reply_text = get_fallback()
            store_memory("assistant", reply_text, user_id=user_id)

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
def memory_route():
    data = request.get_json()
    role = data.get("role", "user")
    content = data.get("content", "")
    tag = data.get("tag", None)
    user_id = data.get("user_id", "default")
    store_memory(role, content, tag=tag, user_id=user_id)
    return jsonify({"status": "saved"})


@app.route("/last-reflection", methods=["GET"])
def last_reflection():
    user_id = request.args.get("user_id", "default")
    return jsonify(fetch_last_memory(user_id=user_id))


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
def vision_route():
    data = request.get_json()
    image_b64 = data.get("image", "")
    media_type = data.get("media_type", "image/jpeg")
    user_id = data.get("user_id", "default")
    result = handle_vision(image_b64, media_type=media_type)
    store_memory("user", "[이미지 전송]", user_id=user_id)
    if result:
        store_memory("assistant", result, user_id=user_id)
    return jsonify({"reply": result})


# ─── 상태 확인 ───

@app.route("/pt-status", methods=["GET"])
def pt_status():
    user_id = request.args.get("user_id", "default")
    return jsonify(get_user_status(user_id))


@app.route("/flow-status", methods=["GET"])
def flow_status():
    user_id = request.args.get("user_id", "default")
    return jsonify(memory_flow.get_flow_summary(user_id))


@app.route("/session-status", methods=["GET"])
def session_status():
    user_id = request.args.get("user_id", "default")
    return jsonify(get_session_summary(user_id))


@app.route("/session/<tag>", methods=["GET"])
def session_detail(tag):
    user_id = request.args.get("user_id", "default")
    mems = get_session_memories(tag, user_id=user_id)
    return jsonify({
        "tag": tag,
        "count": len(mems),
        "memories": [{"role": m["role"], "content": m["content"]} for m in mems],
    })


@app.route("/memory-search", methods=["GET"])
def memory_search():
    keyword = request.args.get("q", "")
    limit = int(request.args.get("limit", 20))
    user_id = request.args.get("user_id", "default")
    if not keyword:
        return jsonify({"error": "q 파라미터 필요"}), 400
    results = search_memories(keyword, limit, user_id=user_id)
    return jsonify({"query": keyword, "count": len(results), "results": results})


@app.route("/memory-stats", methods=["GET"])
def memory_stats():
    user_id = request.args.get("user_id", "default")
    return jsonify(get_memory_stats(user_id))


# ─── 간단 인증 (위험 엔드포인트 보호) ───
Q_API_KEY = os.getenv("Q_API_KEY", "")


def check_api_key():
    """Q_API_KEY가 설정된 경우에만 인증 체크"""
    if not Q_API_KEY:
        return True  # 키 미설정 시 인증 건너뜀
    key = request.headers.get("X-Q-Key", "")
    return key == Q_API_KEY


# ─── 리셋 ───

@app.route("/pt-reset", methods=["POST"])
def pt_reset_route():
    if not check_api_key():
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json() or {}
    user_id = data.get("user_id", None)
    pt_reset(user_id)
    return jsonify({"status": "reset", "user_id": user_id or "all"})


@app.route("/full-reset", methods=["POST"])
def full_reset():
    if not check_api_key():
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json() or {}
    user_id = data.get("user_id", None)
    pt_reset(user_id)
    reset_memory(user_id)
    reset_tags()
    if user_id:
        memory_flow.reset(user_id)
    else:
        memory_flow.reset_all()
    return jsonify({"status": "full reset complete", "user_id": user_id or "all"})


@app.route("/", methods=["GET"])
def ping():
    return "Q server is alive."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
