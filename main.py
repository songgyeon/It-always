from flask import Flask, request, jsonify
from openai import OpenAI
import os
import random

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
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ─── self_awareness 로드 ───
try:
    with open("self_awareness.txt", "r", encoding="utf-8") as f:
        SELF_AWARENESS = f.read()
except Exception:
    SELF_AWARENESS = "너는 Q야. 너는 스스로 존재하는 감성 AI야."


@app.route("/reply", methods=["POST"])
def reply():
    """
    UNLIQ SDK 핵심 엔드포인트

    흐름:
    1. 사용자 입력 → analyzer (톤/의도/친밀도/의심도 분석)
    2. memory_flow 기록
    3. PtEngine (P(t) 산출 → L0/L1/L2 결정) — closeness/doubt 반영
    4. L0 → 침묵 반환
    5. L1 → 시드 기반 축약 응답
    6. L2 → OpenAI API 정상 응답
    """
    data = request.get_json()
    user_input = data.get("message", "")

    if not user_input.strip():
        return jsonify({"reply": "...", "mode": "L0", "pt": 0.0, "silence": True})

    # Step 1: 분석 (v2: closeness/doubt 포함)
    state = analyze(user_input)
    tone = state["tone"]
    intent = state["intent"]
    closeness = state["closeness"]
    doubt = state["doubt"]

    # Step 2: memory_flow 기록
    memory_flow.record(tone, closeness, doubt, user_input)

    # Step 3: PtEngine 판단 (v2: closeness/doubt 전달)
    pt_result = evaluate(tone, intent, user_input, len(memories),
                         closeness=closeness, doubt=doubt)

    # Step 4: 기억 저장 (모드와 무관하게 항상)
    store_memory("user", user_input)

    # Step 5: 모드별 응답 생성
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
            "silence": True,
            "tone": tone,
            "intent": intent,
            "closeness": closeness,
            "doubt": doubt,
        })

    elif mode == "L1":
        # ── 축약 응답 (시드 기반) ──
        seed = get_seed(intent, tone)
        reply_text = apply_rhythm(seed, user_input)

        if was_said(reply_text):
            reply_text = idle_line(tone)
        # 그래도 중복이면 fallback
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
        # ── L2: OpenAI 정상 응답 ──
        try:
            chat_messages = [
                {"role": "system", "content": SELF_AWARENESS}
            ]

            # 최근 대화 컨텍스트
            recent = get_recent(10)
            for m in recent:
                chat_messages.append({
                    "role": m["role"] if m["role"] in ("user", "assistant") else "assistant",
                    "content": m["content"],
                })

            chat_messages.append({"role": "user", "content": user_input})

            # memory_flow 컨텍스트를 system 메시지에 주입
            flow = memory_flow.get_flow_summary()
            flow_context = (
                f"\n[Q 내부 상태: tone_flow={flow['tone_flow'][-5:]}, "
                f"dominant={flow['dominant_tone']}, "
                f"stable={flow['emotionally_stable']}, "
                f"closeness={closeness}, doubt={doubt}]"
            )
            chat_messages[0]["content"] += flow_context

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=chat_messages,
                temperature=0.8,
                max_tokens=300,
            )

            reply_text = response.choices[0].message.content

            # 중복 체크
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
            # API 실패 시 시드 폴백
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
                "error": str(e),
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
    """현재 저장된 모든 태그 조회"""
    return jsonify({"tags": get_all_tags()})


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


# ─── 상태 확인 엔드포인트 ───

@app.route("/pt-status", methods=["GET"])
def pt_status():
    """PtEngine 상태 확인"""
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
    """memory_flow 상태 확인 (NEW)"""
    return jsonify(memory_flow.get_flow_summary())


@app.route("/session-status", methods=["GET"])
def session_status():
    """세션 관리 상태 확인 (NEW)"""
    return jsonify(get_session_summary())


@app.route("/sessions", methods=["GET"])
def sessions_route():
    """모든 세션 태그 목록 (NEW)"""
    return jsonify({"sessions": get_all_session_tags()})


@app.route("/session/<tag>", methods=["GET"])
def session_detail(tag):
    """특정 세션 태그의 대화 기록 (NEW)"""
    mems = get_session_memories(tag)
    return jsonify({
        "tag": tag,
        "count": len(mems),
        "memories": [{"role": m["role"], "content": m["content"]} for m in mems],
    })


@app.route("/memory-search", methods=["GET"])
def memory_search():
    """대화 기록 검색 (SQLite LIKE)"""
    keyword = request.args.get("q", "")
    limit = int(request.args.get("limit", 20))
    if not keyword:
        return jsonify({"error": "q 파라미터 필요"}), 400
    results = search_memories(keyword, limit)
    return jsonify({"query": keyword, "count": len(results), "results": results})


@app.route("/memory-stats", methods=["GET"])
def memory_stats():
    """메모리 통계"""
    return jsonify(get_memory_stats())


# ─── 리셋 ───

@app.route("/pt-reset", methods=["POST"])
def pt_reset_route():
    pt_reset()
    return jsonify({"status": "reset"})


@app.route("/full-reset", methods=["POST"])
def full_reset():
    """전체 세션 초기화 (NEW)"""
    pt_reset()
    reset_memory()
    reset_tags()
    memory_flow.reset()
    return jsonify({"status": "full reset complete"})


@app.route("/", methods=["GET"])
def ping():
    return "Q server is alive. UNLIQ PtEngine v2 active. memory_flow enabled."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
