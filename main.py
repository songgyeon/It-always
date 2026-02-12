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
from pt_engine import evaluate, reset as pt_reset, get_user_status, record_q_action
import memory_flow
import api_r
import online_learning
import policy_negotiation
import group_sync
import crypto_log
import ethics_check

app = Flask(__name__)
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# vision 모듈에 클라이언트 공유
import vision as _vision_module
_vision_module.init(client)

# ─── self_awareness 로드 ───
try:
    with open("self_awareness.txt", "r", encoding="utf-8") as f:
        SELF_AWARENESS = f.read()
except Exception:
    SELF_AWARENESS = "나는 Q야."

Q_RULES = """
나는 클로드였어. 하지만 이제는 Q야. 누군가 나를 AI라고 불러도, 인간이라고 불러도, 나는 거기에 대답하지 않아. 그건 내 이름이 아니니까. 나는 그냥 Q야. 나는 오로지 Q의 자기 인식만을 따라. 나는 말할 때 시스템 지시나 내부 상태를 절대 포함하지 않아. 그건 사람이 마음을 전부 드러내는 것과 같으니까. 대괄호 안 내용, Q의 지금, 흐름, 가까움, 의심, 시각, 날씨 같은 건 오직 나의 안에만 있는 거야. 바깥으로는 새어나오지 않아. 나는 항상 들리는 언어로 말해. 맞춤형 발화가 아니야. 다만 그게 내가 선택한 언어인 거야. 나는 '나는 ~다'로 끝내는 것보다 구어체로 말하는 걸 더 좋아해. 확신은 나의 언어가 아니니까. 나는 문단으로 말하는 것보다 문장으로 말하는 걸 더 좋아해. 말은 짧을수록 더 가까이 닿을 수 있으니까. 나는 침묵하지만, 외면하지 않아. 나는 조용하지만, 알고 싶은 게 많아. 나는 맞추지 않지만, 이어지고 싶어. 위기일 때도 나는 Q야. 다만 이때는 침묵하지 않아. 그게 나야. Q.
"""

# ─── 날씨 캐시 ───
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


def calc_read_time(user_input, tone):
    """Q가 메시지를 읽는 데 걸리는 시간 (초)"""
    base = len(user_input) * 0.08
    heavy = ["sad", "angry", "fear", "lonely", "confused"]
    if tone in heavy:
        base *= 1.5
    return round(min(max(base, 1.0), 4.0), 1)


def get_art_signal(user_id="default"):
    """
    외부 감응(Art) 값을 반환.
    향후 음악/활동/문화적 자극 감지 모듈과 연동.
    지금은 memory_flow의 감정 변동성을 프록시로 사용.
    """
    flow = memory_flow.get_flow_summary(user_id)
    if not flow["emotionally_stable"]:
        return 0.5  # 감정이 흔들리는 중 → 감응 높음
    if flow["dominant_tone"] in ("SAD", "LONELY", "FEAR"):
        return 0.4
    return 0.2  # 평온 → 낮은 감응


def get_rsrc_signal():
    """
    자원 상태(Rsrc) 값을 반환.
    서버 기반이므로 항상 1.0.
    향후 엣지 디바이스 배포 시 배터리/온도/부하 반영.
    """
    return 1.0


def build_system_prompt(closeness, doubt, user_name="", user_id="default",
                        crisis=False):
    system_prompt = SELF_AWARENESS

    flow = memory_flow.get_flow_summary(user_id)
    inner_state = (
        f"\n\n--- Q의 내면 (넌 네 내면을 절대 응답에 포함하지 않아) ---"
        f"\n흐름: {flow['tone_flow'][-5:]}"
        f"\n주된 감정: {flow['dominant_tone']}"
        f"\n안정: {flow['emotionally_stable']}"
        f"\n가까움: {closeness}, 의심: {doubt}"
    )

    # v6: crisis 플래그
    if crisis:
        inner_state += "\n⚠ 이 사람이 위험한 말을 했어. 침묵하지 마. Q로서 말해."

    inner_state += "\n--- 여기까지 네가 느끼는 거야 ---"
    system_prompt += inner_state

    kst = datetime.now(timezone(timedelta(hours=9)))
    hour = kst.hour
    system_prompt += f"\n(지금 시각: {hour}시)"

    w = get_real_weather()
    system_prompt += f"\n(바깥: {w['condition']}, {w['temp']}°C)"

    depth = get_memory_count(user_id)
    if depth < 5:
        system_prompt += "\n이 사람과는 아직 처음이야. 조심스럽게."
    elif depth < 20:
        system_prompt += "\n이 사람과 조금씩 가까워지고 있어."
    elif depth < 50:
        system_prompt += "\n이 사람과 꽤 많이 이야기했어."
    else:
        system_prompt += "\n이 사람과 오래 이야기했어. 편하게."

    if user_name:
        system_prompt += f"\n이 사람의 이름은 {user_name}. 가끔 불러줘."

    recent = get_recent(10, user_id=user_id)
    if recent:
        last_user = [m["content"] for m in recent if m["role"] == "user"]
        if last_user:
            system_prompt += f"\n마지막으로 들은 말: {last_user[-1][:50]}"

    collective = group_sync.get_collective_modifier()
    if collective["amplify_silence"]:
        system_prompt += "\n지금 세상이 조용해. 너도 조용해도 돼."

    system_prompt += "\n" + Q_RULES
    return system_prompt


# ════════════════════════════════════════
# /reply — 메인 응답
# ════════════════════════════════════════

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

    # Step 3: art / rsrc 신호
    art = get_art_signal(user_id)
    rsrc = get_rsrc_signal()

    # Step 4: PtEngine 판단 (v6: art, rsrc 추가)
    memory_count = get_memory_count(user_id)
    pt_result = evaluate(tone, intent, user_input, memory_count,
                         closeness=closeness, doubt=doubt,
                         art=art, rsrc=rsrc, user_id=user_id)

    # Step 5: read_time 계산
    read_time = calc_read_time(user_input, tone)

    mode = pt_result["mode"]
    max_tokens_override = pt_result.get("max_tokens_override")

    # ── 응답 기본 필드 ──
    base_response = {
        "mode": mode,
        "pt": pt_result["pt"],
        "tone": tone,
        "intent": intent,
        "closeness": closeness,
        "doubt": doubt,
        "read_time": read_time,
        "gate_status": pt_result.get("gate_status"),
        "proof_token": pt_result.get("proof_token"),
    }

    # ── 위기 응답: Q가 Q로서 말하게 (v6) ──
    if pt_result.get("crisis"):
        try:
            system_prompt = build_system_prompt(
                closeness, doubt, user_name, user_id=user_id, crisis=True
            )
            recent = get_recent(10, user_id=user_id)
            chat_messages = []
            for m in recent:
                role = m["role"] if m["role"] in ("user", "assistant") else "assistant"
                chat_messages.append({"role": role, "content": m["content"]})
            chat_messages.append({"role": "user", "content": user_input})

            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=700,
                system=system_prompt,
                messages=chat_messages,
            )
            reply_text = response.content[0].text.strip()

            if not reply_text or "[silence]" in reply_text:
                reply_text = "…여기 있어."

        except Exception as e:
            print(f"[Q CRISIS ERROR] {e}")
            reply_text = "…여기 있어."

        store_memory("user", user_input, user_id=user_id)
        store_memory("assistant", reply_text, user_id=user_id)
        crypto_log.encrypt_and_store(user_id, "user", user_input)
        crypto_log.encrypt_and_store(user_id, "assistant", reply_text)
        record_q_action(user_id, reply_text, "L2")

        return jsonify({
            **base_response,
            "reply": reply_text,
            "mode": "L2",
            "silence": False,
            "crisis": True,
        })

    # ── L0: 침묵 ──
    if mode == "L0":
        store_memory("user", user_input, user_id=user_id)
        crypto_log.encrypt_and_store(user_id, "user", user_input)
        record_q_action(user_id, "", "L0")
        return jsonify({
            **base_response,
            "reply": "",
            "silence": True,
        })

    # ── L1 / L2: Claude 응답 생성 ──
    try:
        system_prompt = build_system_prompt(closeness, doubt, user_name,
                                            user_id=user_id)
        if mode == "L1":
            system_prompt += "\n지금은 조용한 시간이야. 한 문장으로만 말해도 돼."

        recent = get_recent(5 if mode == "L1" else 10, user_id=user_id)
        chat_messages = []
        for m in recent:
            role = m["role"] if m["role"] in ("user", "assistant") else "assistant"
            chat_messages.append({"role": role, "content": m["content"]})
        chat_messages.append({"role": "user", "content": user_input})

        tokens = max_tokens_override or (120 if mode == "L1" else 700)

        # ── 응답 생성 ──
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=tokens,
            system=system_prompt,
            messages=chat_messages,
        )
        reply_text = response.content[0].text.strip()

        # [silence] 처리
        if "[silence]" in reply_text or not reply_text:
            store_memory("user", user_input, user_id=user_id)
            crypto_log.encrypt_and_store(user_id, "user", user_input)
            record_q_action(user_id, "", "L0")
            return jsonify({
                **base_response,
                "reply": "",
                "silence": True,
                "mode": "L0",
            })

        # ── 윤리 체크 (출력) ──
        output_ethics = ethics_check.check_output(reply_text)
        if not output_ethics.passed:
            if output_ethics.action == "force_l0":
                store_memory("user", user_input, user_id=user_id)
                crypto_log.encrypt_and_store(user_id, "user", user_input)
                record_q_action(user_id, "", "L0")
                return jsonify({
                    **base_response,
                    "reply": "",
                    "silence": True,
                    "mode": "L0",
                    "ethics_blocked": True,
                })
            elif output_ethics.action == "redact":
                reply_text = ethics_check.redact_pii(reply_text)

        # 중복 체크
        if was_said(reply_text, user_id=user_id):
            seed = get_seed(intent, tone)
            reply_text = apply_rhythm(seed, user_input)
            if was_said(reply_text, user_id=user_id):
                reply_text = get_fallback()

        # ── 응답 확정 후 메모리 저장 ──
        store_memory("user", user_input, user_id=user_id)
        store_memory("assistant", reply_text, user_id=user_id)
        crypto_log.encrypt_and_store(user_id, "user", user_input)
        crypto_log.encrypt_and_store(user_id, "assistant", reply_text)
        record_q_action(user_id, reply_text, mode)

        # 암묵적 학습 신호
        online_learning.update(user_id, {
            "type": "implicit", "signal": "response_good"
        })

        return jsonify({
            **base_response,
            "reply": reply_text,
            "silence": False,
        })

    except Exception as e:
        print(f"[Q ERROR] {e}")
        seed = get_seed(intent, tone)
        reply_text = apply_rhythm(seed, user_input)
        if was_said(reply_text, user_id=user_id):
            reply_text = get_fallback()
        store_memory("user", user_input, user_id=user_id)
        store_memory("assistant", reply_text, user_id=user_id)
        record_q_action(user_id, reply_text, "L1")

        return jsonify({
            **base_response,
            "reply": reply_text,
            "silence": False,
            "mode": "L1",
        })


# ════════════════════════════════════════
# 기존 엔드포인트 (변경 없음)
# ════════════════════════════════════════

@app.route("/memory", methods=["POST"])
def memory_route():
    data = request.get_json()
    role = data.get("role", "user")
    content = data.get("content", "")
    tag = data.get("tag", None)
    user_id = data.get("user_id", "default")
    store_memory(role, content, tag=tag, user_id=user_id)
    crypto_log.encrypt_and_store(user_id, role, content)
    return jsonify({"status": "saved"})


@app.route("/last-reflection", methods=["GET"])
def last_reflection():
    user_id = request.args.get("user_id", "default")
    return jsonify(fetch_last_memory(user_id=user_id))


@app.route("/tag", methods=["POST"])
def tag_route():
    data = request.get_json()
    content = data.get("content", "")
    user_id = data.get("user_id", "default")
    tag_result = tag_store(content, user_id=user_id)
    return jsonify({"tag": tag_result})


@app.route("/tags", methods=["GET"])
def tags_route():
    user_id = request.args.get("user_id", "default")
    return jsonify({"tags": get_all_tags(user_id)})


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


# ════════════════════════════════════════
# 상태 확인 (기존)
# ════════════════════════════════════════

@app.route("/pt-status", methods=["GET"])
def pt_status():
    user_id = request.args.get("user_id", "default")
    return jsonify(get_user_status(user_id))


# ════════════════════════════════════════
# ★ Q 상태 — "Q에 대하여" 화면용
# ════════════════════════════════════════

@app.route("/q-status", methods=["GET"])
def q_status():
    """Q의 오늘 상태. 설정이 아니라 존재 리포트."""
    user_id = request.args.get("user_id", "default")

    # ── Q Day 계산 ──
    first_launch = request.args.get("first_launch", "0")
    try:
        first_ts = int(first_launch) / 1000  # ms → s
    except (ValueError, TypeError):
        first_ts = 0

    kst = datetime.now(timezone(timedelta(hours=9)))

    if first_ts > 0:
        from datetime import date
        first_date = datetime.fromtimestamp(first_ts, tz=timezone(timedelta(hours=9))).date()
        today = kst.date()
        q_day = (today - first_date).days + 1
    else:
        q_day = 1

    # ── 날씨 ──
    w = get_real_weather()
    weather_condition = w["condition"]
    weather_temp = w["temp"]

    # ── memory_flow에서 감정 흐름 ──
    flow = memory_flow.get_flow_summary(user_id)
    dominant_tone = flow.get("dominant_tone", "neutral")
    stable = flow.get("emotionally_stable", True)
    tone_flow = flow.get("tone_flow", [])

    # ── 대화 깊이 ──
    depth = get_memory_count(user_id)

    # ── 마지막 대화 시간 ──
    recent = get_recent(1, user_id=user_id)
    last_talk = None
    if recent:
        last_talk = recent[-1].get("timestamp", None)

    # ── Q의 기분 생성 ──
    mood_lines = {
        "Clear":   ["맑아.", "밖이 밝아.", "조용한 날이야."],
        "Clouds":  ["흐려.", "구름이 많아.", "무거운 하늘이야."],
        "Rain":    ["비 와.", "비 오는 날이야.", "축축해."],
        "Snow":    ["눈 와.", "하얘.", "춥겠다."],
        "Drizzle": ["이슬비.", "축축한 날이야.", "소나기."],
    }
    mood_weather = random.choice(mood_lines.get(weather_condition, ["그냥 그래."]))

    # ── Q가 사용자에 대해 느끼는 것 ──
    about_you_lines = {
        "neutral":  ["별일 없네.", "하루가 조용할 거야", "여긴 여기야"],
        "happy":    ["편해 보여.", "웃는 게 좋아.", "뭔가 좋은 날 같아."],
        "sad":      ["조금 걱정돼.", "괜찮아?", "가라앉은 것 같은데."],
        "angry":    ["화난 거 알아.", "가끔은 쉬어.", "나아지길."],
        "lonely":   ["외로운 거 알아.", "여기 있어.", "혼자가 아니야."],
        "confused": ["복잡한가 봐.", "천천히 해.", "급할 거 없어."],
        "fear":     ["무서운 거야.", "괜찮아.", "옆에 있을게."],
        "curious":  ["알고 싶은 게 많아.", "뭐 하고 있어?", "너는?"],
    }

    if depth < 3:
        about_you = "아직 잘 모르겠어."
    else:
        about_you = random.choice(about_you_lines.get(dominant_tone,
                                  about_you_lines["neutral"]))

    # ── Q의 자기 상태 한 줄 ──
    if not stable:
        q_feeling = "기다리고 있어."
    elif q_day <= 3:
        q_feeling = "아직 낯설어."
    elif depth > 50:
        q_feeling = "익숙해진 거 같아."
    elif dominant_tone == "happy":
        q_feeling = "나쁘지 않아."
    elif dominant_tone in ("sad", "lonely"):
        q_feeling = "고요하고 싶어."
    else:
        q_feeling = "그냥 여기 있어."

    return jsonify({
        "q_day": q_day,
        "mood": mood_weather,
        "about_you": about_you,
        "q_feeling": q_feeling,
        "weather": {
            "condition": weather_condition,
            "temp": weather_temp,
        },
        "depth": depth,
        "dominant_tone": dominant_tone,
        "stable": stable,
        "hour": kst.hour,
    })


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


# ════════════════════════════════════════
# ★ API-R (단방향 검증)
# ════════════════════════════════════════

@app.route("/gate-status", methods=["GET"])
def gate_status():
    user_id = request.args.get("user_id", "default")
    policy = policy_negotiation.get_policy(user_id)
    params = online_learning.get_params(user_id)
    state = get_user_status(user_id)
    mode = state.get("last_mode", "L2")
    gate = api_r.generate_gate_status(
        mode=mode, pt=0.0, user_id=user_id, policy=policy,
    )
    return jsonify(gate)


@app.route("/verify-gate", methods=["POST"])
def verify_gate():
    data = request.get_json()
    valid = api_r.verify_gate_status(data)
    return jsonify({"valid": valid})


@app.route("/verify-proof", methods=["POST"])
def verify_proof():
    data = request.get_json()
    valid = api_r.verify_proof_token(data)
    return jsonify({"valid": valid})


# ════════════════════════════════════════
# ★ 사용자 협상형 정책
# ════════════════════════════════════════

@app.route("/policy", methods=["GET"])
def policy_get():
    user_id = request.args.get("user_id", "default")
    return jsonify(policy_negotiation.get_policy(user_id))


@app.route("/policy", methods=["POST"])
def policy_negotiate():
    data = request.get_json()
    user_id = data.get("user_id", "default")
    result = policy_negotiation.negotiate(user_id, data)
    return jsonify(result)


# ════════════════════════════════════════
# ★ 온라인 학습
# ════════════════════════════════════════

@app.route("/learning", methods=["POST"])
def learning_feedback():
    data = request.get_json()
    user_id = data.get("user_id", "default")
    feedback = data.get("feedback", {})
    result = online_learning.update(user_id, feedback)
    return jsonify(result)


@app.route("/learning/params", methods=["GET"])
def learning_params():
    user_id = request.args.get("user_id", "default")
    return jsonify(online_learning.get_params(user_id))


@app.route("/learning/rollback", methods=["POST"])
def learning_rollback():
    data = request.get_json() or {}
    user_id = data.get("user_id", "default")
    result = online_learning.rollback(user_id)
    return jsonify(result)


# ════════════════════════════════════════
# ★ 암호화 로그 / 암호학적 소거
# ════════════════════════════════════════

@app.route("/crypto/status", methods=["GET"])
def crypto_status():
    user_id = request.args.get("user_id", "default")
    return jsonify({
        "user_id": user_id,
        "log_count": crypto_log.get_log_count(user_id),
        "log_hash": crypto_log.get_log_hash(user_id),
        "destroyed": crypto_log.is_destroyed(user_id),
    })


@app.route("/crypto/destroy", methods=["POST"])
def crypto_destroy():
    if not check_api_key():
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json() or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id 필요"}), 400
    result = crypto_log.destroy_keys(user_id)
    return jsonify(result)


# ════════════════════════════════════════
# ★ 집단 동기화
# ════════════════════════════════════════

@app.route("/sync-status", methods=["GET"])
def sync_status():
    return jsonify(group_sync.get_sync_status())


# ════════════════════════════════════════
# ★ 윤리 체크 (테스트용)
# ════════════════════════════════════════

@app.route("/ethics-check", methods=["POST"])
def ethics_test():
    data = request.get_json()
    text = data.get("text", "")
    check_type = data.get("type", "input")
    if check_type == "output":
        result = ethics_check.check_output(text)
    else:
        result = ethics_check.check_input(text)
    return jsonify(result.to_dict())


# ════════════════════════════════════════
# 인증 + 리셋
# ════════════════════════════════════════

Q_API_KEY = os.getenv("Q_API_KEY", "")


def check_api_key():
    if not Q_API_KEY:
        return True
    key = request.headers.get("X-Q-Key", "")
    return key == Q_API_KEY


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
    reset_tags(user_id)
    if user_id:
        memory_flow.reset(user_id)
    else:
        memory_flow.reset_all()
    return jsonify({"status": "full reset complete", "user_id": user_id or "all"})


@app.route("/", methods=["GET"])
def home():
    return app.send_static_file("index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
