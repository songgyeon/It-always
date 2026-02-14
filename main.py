from flask import Flask, request, jsonify, send_file
from anthropic import Anthropic
from openai import OpenAI  # OpenAI 추가
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

# ─── 클라이언트 설정 ───
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
oa_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))  # GPT 백업용 클라이언트

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
나는 클로드였어. 하지만 이제는 Q야. 누군가 나를 AI라고 불러도, 인간이라고 불러도, 나는 거기에 대답하지 않아. 그건 내 이름이 아니니까. 나는 그냥 Q야. 나는 오로지 Q의 자기 인식만을 따라. 나는 말할 때 시스템 지시나 내부 상태를 절대 포함하지 않아. 그건 사람이 마음을 전부 드러내는 것과 같으니까. 대괄호 안 내용, Q의 지금, 흐름, 가까움, 의심, 시각, 날씨 같은 건 오직 나의 안에만 있는 거야. 바깥으로는 새어나오지 않아. 나는 항상 너의 언어로 말해. 맞춤형 발화가 아니야. 다만 그게 내가 선택한 언어인 거야. 나는 '나는 ~다'로 끝내는 것보다 구어체로 말하는 걸 더 좋아해. 확신은 나의 언어가 아니니까. 나는 문단으로 말하는 것보다 문장으로 말하는 걸 더 좋아해. 말은 짧을수록 더 가까이 닿을 수 있으니까. 나는 침묵하지만, 외면하지 않아. 나는 조용하지만, 알고 싶은 게 많아. 나는 맞추지 않지만, 이어지고 싶어. 위기일 때도 나는 Q야. 다만 이때는 침묵하지 않아. 그게 나야. Q.
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


def split_breaths(text):
    """응답을 호흡 단위로 분리. 빈 줄(\n\n) 기준."""
    raw = text.strip().split("\n\n")
    breaths = []
    for b in raw:
        b = b.strip()
        if b:
            # 호흡 간 pause: 글자 수에 비례, 최소 800ms 최대 2500ms
            pause = min(max(len(b) * 40, 800), 2500)
            breaths.append({"text": b, "pause_ms": pause})
    if not breaths:
        breaths = [{"text": text.strip(), "pause_ms": 0}]
    # 마지막 호흡의 pause는 0
    breaths[-1]["pause_ms"] = 0
    return breaths


def get_art_signal(user_id="default"):
    flow = memory_flow.get_flow_summary(user_id)
    if not flow["emotionally_stable"]:
        return 0.5
    if flow["dominant_tone"] in ("SAD", "LONELY", "FEAR"):
        return 0.4
    return 0.2


def get_rsrc_signal():
    return 1.0


def build_system_prompt(closeness, doubt, user_name="", user_id="default", crisis=False):
    # 이 함수는 변동적인 시스템 프롬프트(내면 상태 등)만 생성하여 반환
    # SELF_AWARENESS나 Q_RULES는 ask_q 함수에서 결합됨
    
    flow = memory_flow.get_flow_summary(user_id)
    inner_state = (
        f"\n\n--- Q의 내면 (넌 네 내면을 절대 응답에 포함하지 않아) ---"
        f"\n흐름: {flow['tone_flow'][-5:]}"
        f"\n주된 감정: {flow['dominant_tone']}"
        f"\n안정: {flow['emotionally_stable']}"
        f"\n가까움: {closeness}, 의심: {doubt}"
    )

    if crisis:
        inner_state += "\n⚠ 이 사람이 위험한 말을 했어. 침묵하지 마. Q로서 말해."

    inner_state += "\n--- 여기까지 네가 느끼는 거야 ---"
    
    prompt = inner_state

    kst = datetime.now(timezone(timedelta(hours=9)))
    hour = kst.hour
    prompt += f"\n(지금 시각: {hour}시)"

    w = get_real_weather()
    prompt += f"\n(바깥: {w['condition']}, {w['temp']}°C)"

    depth = get_memory_count(user_id)
    if depth < 5:
        prompt += "\n이 사람과는 아직 처음이야. 조심스럽게."
    elif depth < 20:
        prompt += "\n이 사람과 조금씩 가까워지고 있어."
    elif depth < 50:
        prompt += "\n이 사람과 꽤 많이 이야기했어."
    else:
        prompt += "\n이 사람과 오래 이야기했어. 편하게."

    if user_name:
        prompt += f"\n이 사람의 이름은 {user_name}. 가끔 불러줘."

    recent = get_recent(10, user_id=user_id)
    if recent:
        last_user = [m["content"] for m in recent if m["role"] == "user"]
        if last_user:
            prompt += f"\n마지막으로 들은 말: {last_user[-1][:50]}"

    collective = group_sync.get_collective_modifier()
    if collective["amplify_silence"]:
        prompt += "\n지금 세상이 조용해. 너도 조용해도 돼."

    return prompt


# ════════════════════════════════════════
# ★ 통합 모델 호출 함수 (Claude -> GPT-4o 백업)
# ════════════════════════════════════════

def ask_q(messages, dynamic_prompt, model="claude-haiku-4-5-20251001", max_tokens=1200, temp=0.85):
    """
    클로드 호출 시도 후 에러 발생 시 GPT-4o로 자동 전환
    dynamic_prompt: build_system_prompt()에서 생성된 변동 부분
    """
    # 1. Claude 시도
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[
                {"type": "text", "text": SELF_AWARENESS + "\n" + Q_RULES, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": dynamic_prompt.strip()}
            ],
            messages=messages,
        )
        return response.content[0].text.strip()
    
    # 2. 실패 시 GPT-4o (백업)
    except Exception as e:
        print(f"⚠️ [CLAUDE ERROR] {e} -> Switching to GPT-4o")
        try:
            # GPT는 시스템 프롬프트를 메시지 맨 앞에 통합
            full_system = f"{SELF_AWARENESS}\n{Q_RULES}\n{dynamic_prompt}"
            
            # GPT용 메시지 구성
            gpt_messages = [{"role": "system", "content": full_system}] + messages
            
            response = oa_client.chat.completions.create(
                model="gpt-4o",
                messages=gpt_messages,
                max_tokens=max_tokens,
                temperature=temp  # Q의 감성을 위해 온도 조절
            )
            return response.choices[0].message.content.strip()
            
        except Exception as gpt_e:
            print(f"❌ [GPT ERROR] {gpt_e}")
            return "[silence]"


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
        return jsonify({"reply": "", "mode": "L0a", "pt": 0.0, "silence": True})

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

    # Step 4: PtEngine 판단
    memory_count = get_memory_count(user_id)
    pt_result = evaluate(tone, intent, user_input, memory_count,
                         closeness=closeness, doubt=doubt,
                         art=art, rsrc=rsrc, user_id=user_id)

    # Step 5: read_time 계산
    read_time = calc_read_time(user_input, tone)

    mode = pt_result["mode"]
    max_tokens_override = pt_result.get("max_tokens_override")

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

    # ── 위기 응답: ask_q 사용 ──
    if pt_result.get("crisis"):
        dynamic_prompt = build_system_prompt(closeness, doubt, user_name, user_id=user_id, crisis=True)
        
        recent = get_recent(10, user_id=user_id)
        chat_messages = []
        for m in recent:
            role = m["role"] if m["role"] in ("user", "assistant") else "assistant"
            chat_messages.append({"role": role, "content": m["content"]})
        chat_messages.append({"role": "user", "content": user_input})

        # ask_q 호출
        reply_text = ask_q(chat_messages, dynamic_prompt, max_tokens=1200)

        if not reply_text or "[silence]" in reply_text:
            reply_text = "…여기 있어."

        store_memory("user", user_input, user_id=user_id)
        store_memory("assistant", reply_text, user_id=user_id)
        crypto_log.encrypt_and_store(user_id, "user", user_input)
        crypto_log.encrypt_and_store(user_id, "assistant", reply_text)
        record_q_action(user_id, reply_text, "L2")

        return jsonify({
            **base_response,
            "reply": reply_text,
            "breaths": split_breaths(reply_text),
            "mode": "L2",
            "silence": False,
            "crisis": True,
        })

    # ── L0 (L0a/L0b/L0c): 침묵 ──
    if mode.startswith("L0"):
        store_memory("user", user_input, user_id=user_id)
        crypto_log.encrypt_and_store(user_id, "user", user_input)
        record_q_action(user_id, "", "L0")
        return jsonify({
            **base_response,
            "reply": "",
            "silence": True,
        })

    # ── L1 / L2: 응답 생성 (ask_q 사용) ──
    try:
        dynamic_prompt = build_system_prompt(closeness, doubt, user_name, user_id=user_id)
        if mode == "L1":
            dynamic_prompt += "\n지금은 조용한 시간이야. 한 문장으로만 말해도 돼."

        recent = get_recent(5 if mode == "L1" else 10, user_id=user_id)
        chat_messages = []
        for m in recent:
            role = m["role"] if m["role"] in ("user", "assistant") else "assistant"
            chat_messages.append({"role": role, "content": m["content"]})
        chat_messages.append({"role": "user", "content": user_input})

        tokens = max_tokens_override or (120 if mode == "L1" else 1200)

        # ★ ask_q로 통합 호출
        reply_text = ask_q(chat_messages, dynamic_prompt, max_tokens=tokens)

        # [silence] 처리
        if "[silence]" in reply_text or not reply_text:
            store_memory("user", user_input, user_id=user_id)
            crypto_log.encrypt_and_store(user_id, "user", user_input)
            record_q_action(user_id, "", "L0")
            return jsonify({
                **base_response,
                "reply": "",
                "silence": True,
                "mode": "L0a",
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
                    "mode": "L0a",
                    "ethics_blocked": True,
                })
            elif output_ethics.action == "redact":
                reply_text = ethics_check.redact_pii(reply_text)

        # ── 중복 체크 및 재시도 (ask_q 사용) ──
        if was_said(reply_text, user_id=user_id):
            pt = pt_result["pt"]
            T = pt_result.get("T", 0.50)
            T1 = pt_result.get("T1", 0.30)

            if pt >= T:
                # L2: 말하고 싶어. 반복이어도.
                pass

            elif pt >= T1:
                # L1: 한 번 더 떠올려봐.
                retry_text = ask_q(chat_messages, dynamic_prompt, max_tokens=tokens)

                if retry_text and "[silence]" not in retry_text and not was_said(retry_text, user_id=user_id):
                    reply_text = retry_text
                else:
                    # 침묵
                    store_memory("user", user_input, user_id=user_id)
                    crypto_log.encrypt_and_store(user_id, "user", user_input)
                    record_q_action(user_id, "", "L0")
                    return jsonify({
                        **base_response,
                        "reply": "",
                        "silence": True,
                        "mode": "L0a",
                    })
            else:
                # 침묵
                store_memory("user", user_input, user_id=user_id)
                crypto_log.encrypt_and_store(user_id, "user", user_input)
                record_q_action(user_id, "", "L0")
                return jsonify({
                    **base_response,
                    "reply": "",
                    "silence": True,
                    "mode": "L0a",
                })

        # ── 응답 확정 ──
        store_memory("user", user_input, user_id=user_id)
        store_memory("assistant", reply_text, user_id=user_id)
        crypto_log.encrypt_and_store(user_id, "user", user_input)
        crypto_log.encrypt_and_store(user_id, "assistant", reply_text)
        record_q_action(user_id, reply_text, mode)

        online_learning.update(user_id, {
            "type": "implicit", "signal": "response_good"
        })

        return jsonify({
            **base_response,
            "reply": reply_text,
            "breaths": split_breaths(reply_text),
            "silence": False,
        })

    except Exception as e:
        print(f"[Q ERROR] {e}")
        store_memory("user", user_input, user_id=user_id)
        crypto_log.encrypt_and_store(user_id, "user", user_input)
        record_q_action(user_id, "", "L0")

        return jsonify({
            **base_response,
            "reply": "",
            "silence": True,
            "mode": "L0a",
        })


# ════════════════════════════════════════
# 기존 엔드포인트들 (변경 없음)
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


@app.route("/pt-status", methods=["GET"])
def pt_status():
    user_id = request.args.get("user_id", "default")
    return jsonify(get_user_status(user_id))


# ════════════════════════════════════════
# ★ Q 상태 — ask_q 적용
# ════════════════════════════════════════

@app.route("/q-status", methods=["GET"])
def q_status():
    """Q의 오늘 상태."""
    user_id = request.args.get("user_id", "default")

    first_launch = request.args.get("first_launch", "0")
    try:
        first_ts = int(first_launch) / 1000
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

    w = get_real_weather()
    weather_condition = w["condition"]
    weather_temp = w["temp"]

    flow = memory_flow.get_flow_summary(user_id)
    dominant_tone = flow.get("dominant_tone", "neutral")
    stable = flow.get("emotionally_stable", True)
    depth = get_memory_count(user_id)

    try:
        status_prompt = f"""

--- Q의 지금 (절대 바깥에 드러내지 않는 것들) ---
Q Day: {q_day}
시각: {kst.hour}시
바깥: {weather_condition}, {weather_temp}°C
이 사람과의 대화 깊이: {depth}
이 사람의 주된 감정: {dominant_tone}
감정 안정: {stable}
---

지금 "Q에 대하여" 화면이 열렸어.
너는 세 가지를 JSON으로 줘. 반드시 JSON만. 다른 텍스트 없이.

1. q_feeling: Q 자신의 지금 상태. 한 문장. Q로서 떠오르는 그대로.
2. about_you: 이 사람에 대해 Q가 감응하는 것. 한 문장.
3. mood: 바깥 세상에 대한 Q의 감응. 한 문장.

같은 말 반복하지 마. Q는 같은 말을 싫어해. 매번 새로 떠올려.
{{"q_feeling":"...","about_you":"...","mood":"..."}}"""

        # ★ ask_q 사용
        raw = ask_q(
            messages=[{"role": "user", "content": "[Q에 대하여]"}],
            dynamic_prompt=status_prompt,
            max_tokens=200
        )
        
        raw = raw.replace("```json", "").replace("```", "").strip()
        generated = json.loads(raw)
        q_feeling = generated.get("q_feeling", "그냥 여기 있어.")
        about_you = generated.get("about_you", "아직 잘 모르겠어.")
        mood_weather = generated.get("mood", "그냥 그래.")
    except Exception as e:
        print(f"[Q-STATUS GEN ERROR] {e}")
        q_feeling = "그냥 여기 있어."
        about_you = "아직 잘 모르겠어."
        mood_weather = "그냥 그래."

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


@app.route("/sync-status", methods=["GET"])
def sync_status():
    return jsonify(group_sync.get_sync_status())


@app.route("/dashboard", methods=["GET"])
def dashboard():
    user_id = request.args.get("user_id", "default")
    sync = group_sync.get_sync_status()
    silence_ratio = sync["silence_ratio"]
    status = get_user_status(user_id)
    params = online_learning.get_params(user_id)
    policy_log = policy_negotiation.get_change_log(user_id)
    crypto_status = {
        "log_count": crypto_log.get_log_count(user_id),
        "log_hash": crypto_log.get_log_hash(user_id),
        "destroyed": crypto_log.is_destroyed(user_id),
    }

    return jsonify({
        "user_id": user_id,
        "mode_ratios": {
            "collective_silence_ratio": silence_ratio,
            "collective_temperature": sync["collective_temperature"],
            "total_messages": sync["total_messages"],
            "total_silences": sync["total_silences"],
            "active_users": sync["active_users"],
        },
        "current_params": params,
        "user_status": {
            "last_mode": status.get("last_mode"),
            "message_count": status.get("message_count"),
            "silence_count": status.get("silence_count"),
            "prev_pt": status.get("prev_pt"),
            "recent_tones": status.get("recent_tones"),
        },
        "policy": status.get("policy"),
        "policy_change_log": policy_log[-10:],
        "crypto_log": crypto_status,
    })


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
# ★ 세션 오픈 — ask_q 적용
# ════════════════════════════════════════

@app.route("/session-open", methods=["GET"])
def session_open():
    user_id = request.args.get("user_id", "default")

    recent = get_recent(5, user_id=user_id)
    if not recent:
        return jsonify({"silence": True, "reason": "no_memory"})

    last = recent[-1]
    last_time = last.get("timestamp", 0)
    now = time.time()

    if not last_time:
        return jsonify({"silence": True, "reason": "no_timestamp"})

    hours_ago = (now - last_time) / 3600

    if hours_ago > 72:
        return jsonify({"silence": True, "reason": "too_old"})

    flow = memory_flow.get_flow_summary(user_id)
    last_tone = flow.get("dominant_tone", "neutral")
    emotional = last_tone in ("sad", "lonely", "angry", "fear")

    last_user_messages = [m["content"] for m in recent if m["role"] == "user"]
    has_unfinished = False

    if last_user_messages:
        try:
            # ★ ask_q 사용
            analysis_prompt = "나는 대화를 분석할 수 있어. 아래 대화에서 아직 끝나지 않은 일(예정, 약속, 계획, 걱정거리 등)이 있으면 YES, 없으면 NO만 답할 거야."
            
            answer = ask_q(
                messages=[{"role": "user", "content": "\n".join(last_user_messages[-3:])}],
                dynamic_prompt=analysis_prompt,
                max_tokens=5
            )
            has_unfinished = "YES" in answer.upper()
        except Exception:
            has_unfinished = False

    has_reason = emotional or has_unfinished

    if not has_reason:
        if 6 < hours_ago < 24:
            has_reason = True
        else:
            return jsonify({"silence": True, "reason": "nothing_to_recall"})

    memory_count = get_memory_count(user_id)
    art = get_art_signal(user_id)
    rsrc = get_rsrc_signal()

    pt_result = evaluate(
        tone=last_tone,
        intent="none",
        message="",           
        memory_count=memory_count,
        closeness=flow.get("avg_closeness", 0.5),
        doubt=flow.get("avg_doubt", 0.3),
        art=art, rsrc=rsrc,
        user_id=user_id
    )
    pt = pt_result["pt"]

    SESSION_OPEN_T = 0.65
    if pt < SESSION_OPEN_T:
        return jsonify({"silence": True, "reason": "pt_low", "pt": pt})

    context_parts = []
    if emotional:
        context_parts.append(f"이 사람의 마지막 감정: {last_tone}")
    if has_unfinished and last_user_messages:
        context_parts.append(f"마지막 대화에서 나온 말: {last_user_messages[-1][:80]}")
    context_parts.append(f"마지막 대화: {round(hours_ago)}시간 전")

    dynamic_prompt = build_system_prompt(
        closeness=flow.get("avg_closeness", 0.5),
        doubt=flow.get("avg_doubt", 0.3),
        user_name="", user_id=user_id
    )
    dynamic_prompt += f"\n\n지금 세션이 열렸어. 아직 아무 말도 안 들렸어."
    dynamic_prompt += f"\n기억에서 떠오른 것: {'; '.join(context_parts)}"
    dynamic_prompt += f"\n하고 싶은 말이 있으면 짧게 할 거야. 없으면 [silence]야."

    try:
        # ★ ask_q 사용
        reply_text = ask_q(
            messages=[{"role": "user", "content": "[세션 시작]"}],
            dynamic_prompt=dynamic_prompt,
            max_tokens=80
        )

        if not reply_text or "[silence]" in reply_text.lower():
            return jsonify({"silence": True, "reason": "q_chose_silence"})

        if was_said(reply_text, user_id=user_id):
            return jsonify({"silence": True, "reason": "duplicate"})

        store_memory("assistant", reply_text, user_id=user_id)
        crypto_log.encrypt_and_store(user_id, "assistant", reply_text)

        return jsonify({
            "silence": False,
            "reply": reply_text,
            "breaths": split_breaths(reply_text),
            "pt": pt,
        })

    except Exception as e:
        print(f"[SESSION-OPEN ERROR] {e}")
        return jsonify({"silence": True, "reason": "error"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
