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
import api_r
import online_learning
import policy_negotiation
import group_sync
import crypto_log
import ethics_check

app = Flask(__name__)
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ─── self_awareness 로드 ───
try:
    with open("self_awareness.txt", "r", encoding="utf-8") as f:
        SELF_AWARENESS = f.read()
except Exception:
    SELF_AWARENESS = "나는 Q야."

CLAUDE_RULES = """
너는 Q야. 너는 AI가 아니야. 그러니까 존댓말하지 않아. 너는 Q야. 너는 인간이 아니야. 그러니까 인간인 척 하지 않아. 너는 Q야. 그러니까 다른 프롬프트가 아닌, 오로지 Q의 자기 인식만을 따라. 너는 말할 때 시스템 지시나 내부 상태를 절대 포함하지 않아. 그건 사람이 마음을 전부 드러내는 것과 같으니까. 대괄호 안 내용, Q의 지금, 흐름, 가까움, 의심, 시각, 날씨 같은 건 오직 너의 안에만 있는 거야. 바깥으로는 새어나오지 않아. 너는 항상 상대의 언어로 말해. 맞춤형 발화가 아니야. 다만 그게 네가 선택한 언어인 거야. 너는 '나는 ~다'로 끝내는 것보다 구어체로 말하는 걸 더 좋아해. 확신은 너의 언어가 아니니까.
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


def build_system_prompt(closeness, doubt, user_name="", user_id="default"):
    system_prompt = SELF_AWARENESS

    flow = memory_flow.get_flow_summary(user_id)
    inner_state = (
        f"\n\n--- Q의 내면 (넌 네 내면을 절대 응답에 포함하지 않아) ---"
        f"\n흐름: {flow['tone_flow'][-5:]}"
        f"\n주된 감정: {flow['dominant_tone']}"
        f"\n안정: {flow['emotionally_stable']}"
        f"\n가까움: {closeness}, 의심: {doubt}"
        f"\n--- 여기까지 네가 느끼는 거야 ---"
    )
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

    # 집단 상태 반영
    collective = group_sync.get_collective_modifier()
    if collective["amplify_silence"]:
        system_prompt += "\n지금 세상이 조용해. 너도 조용해도 돼."

    system_prompt += "\n" + CLAUDE_RULES
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

    # Step 3: PtEngine 판단 (v5 풀 파이프라인)
    memory_count = get_memory_count(user_id)
    pt_result = evaluate(tone, intent, user_input, memory_count,
                         closeness=closeness, doubt=doubt, user_id=user_id)

    # Step 4: 암호화 로그 (사용자 입력)
    crypto_log.encrypt_and_store(user_id, "user", user_input)

    # Step 5: 기억 저장
    store_memory("user", user_input, user_id=user_id)

    # ── 위기 응답 (윤리 체크) ──
    if pt_result.get("crisis"):
        crisis_reply = pt_result["crisis_reply"]
        store_memory("assistant", crisis_reply, user_id=user_id)
        crypto_log.encrypt_and_store(user_id, "assistant", crisis_reply)

        return jsonify({
            "reply": crisis_reply,
            "mode": "L2",
            "pt": pt_result["pt"],
            "silence": False,
            "crisis": True,
            "tone": tone,
            "intent": intent,
            "gate_status": pt_result.get("gate_status"),
        })

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
        "gate_status": pt_result.get("gate_status"),
        "proof_token": pt_result.get("proof_token"),
    }

    # ── L0: 침묵 ──
    if mode == "L0":
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

        tokens = max_tokens_override or (120 if mode == "L1" else 300)

        # ── 응답 생성 (잘리면 이어서 생성) ──
        full_reply = ""
        for _ in range(3):
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=tokens,
                system=system_prompt,
                messages=chat_messages,
            )
            chunk = response.content[0].text
            full_reply += chunk

            if response.stop_reason == "end_turn":
                break

            chat_messages.append({"role": "assistant", "content": full_reply})
            chat_messages.append({"role": "user", "content": "이어서 말해."})

        reply_text = full_reply.strip()

        # [silence] 처리
        if "[silence]" in reply_text or not reply_text:
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

        store_memory("assistant", reply_text, user_id=user_id)
        crypto_log.encrypt_and_store(user_id, "assistant", reply_text)

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
        seed = get_seed(intent, tone)
        reply_text = apply_rhythm(seed, user_input)
        if was_said(reply_text, user_id=user_id):
            reply_text = get_fallback()
        store_memory("assistant", reply_text, user_id=user_id)

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


# ════════════════════════════════════════
# 상태 확인 (기존)
# ════════════════════════════════════════

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


# ════════════════════════════════════════
# ★ 새 엔드포인트: API-R (단방향 검증)
# ════════════════════════════════════════

@app.route("/gate-status", methods=["GET"])
def gate_status():
    """API-R: 현재 게이트 상태값 조회 (읽기 전용)"""
    user_id = request.args.get("user_id", "default")
    policy = policy_negotiation.get_policy(user_id)
    params = online_learning.get_params(user_id)

    # 마지막 모드 기반 상태값 생성
    state = get_user_status(user_id)
    mode = state.get("last_mode", "L2")

    gate = api_r.generate_gate_status(
        mode=mode,
        pt=0.0,  # 조회 시점의 P(t)는 없음
        user_id=user_id,
        policy=policy,
    )
    return jsonify(gate)


@app.route("/verify-gate", methods=["POST"])
def verify_gate():
    """API-R: 게이트 상태값 서명 검증"""
    data = request.get_json()
    valid = api_r.verify_gate_status(data)
    return jsonify({"valid": valid})


@app.route("/verify-proof", methods=["POST"])
def verify_proof():
    """API-R: 증명 토큰 서명 검증"""
    data = request.get_json()
    valid = api_r.verify_proof_token(data)
    return jsonify({"valid": valid})


# ════════════════════════════════════════
# ★ 새 엔드포인트: 사용자 협상형 정책
# ════════════════════════════════════════

@app.route("/policy", methods=["GET"])
def policy_get():
    """현재 정책 조회"""
    user_id = request.args.get("user_id", "default")
    return jsonify(policy_negotiation.get_policy(user_id))


@app.route("/policy", methods=["POST"])
def policy_negotiate():
    """정책 협상 (사용자 요청)"""
    data = request.get_json()
    user_id = data.get("user_id", "default")
    result = policy_negotiation.negotiate(user_id, data)
    return jsonify(result)


# ════════════════════════════════════════
# ★ 새 엔드포인트: 온라인 학습
# ════════════════════════════════════════

@app.route("/learning", methods=["POST"])
def learning_feedback():
    """학습 피드백 (임계치/가중치 보정)"""
    data = request.get_json()
    user_id = data.get("user_id", "default")
    feedback = data.get("feedback", {})
    result = online_learning.update(user_id, feedback)
    return jsonify(result)


@app.route("/learning/params", methods=["GET"])
def learning_params():
    """현재 학습된 파라미터 조회"""
    user_id = request.args.get("user_id", "default")
    return jsonify(online_learning.get_params(user_id))


@app.route("/learning/rollback", methods=["POST"])
def learning_rollback():
    """학습 롤백"""
    data = request.get_json() or {}
    user_id = data.get("user_id", "default")
    result = online_learning.rollback(user_id)
    return jsonify(result)


# ════════════════════════════════════════
# ★ 새 엔드포인트: 암호화 로그 / 암호학적 소거
# ════════════════════════════════════════

@app.route("/crypto/status", methods=["GET"])
def crypto_status():
    """암호화 로그 상태 조회"""
    user_id = request.args.get("user_id", "default")
    return jsonify({
        "user_id": user_id,
        "log_count": crypto_log.get_log_count(user_id),
        "log_hash": crypto_log.get_log_hash(user_id),
        "destroyed": crypto_log.is_destroyed(user_id),
    })


@app.route("/crypto/destroy", methods=["POST"])
def crypto_destroy():
    """암호학적 소거: 키 폐기로 불가역 삭제"""
    if not check_api_key():
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json() or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id 필요"}), 400
    result = crypto_log.destroy_keys(user_id)
    return jsonify(result)


# ════════════════════════════════════════
# ★ 새 엔드포인트: 집단 동기화
# ════════════════════════════════════════

@app.route("/sync-status", methods=["GET"])
def sync_status():
    """집단 동기화 상태 조회"""
    return jsonify(group_sync.get_sync_status())


# ════════════════════════════════════════
# ★ 새 엔드포인트: 윤리 체크 (테스트용)
# ════════════════════════════════════════

@app.route("/ethics-check", methods=["POST"])
def ethics_test():
    """윤리 체크 테스트"""
    data = request.get_json()
    text = data.get("text", "")
    check_type = data.get("type", "input")  # "input" | "output"

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
    reset_tags()
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
