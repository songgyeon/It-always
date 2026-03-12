from flask import Flask, request, jsonify, send_file
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

# \u2500\u2500\u2500 \ud074\ub77c\uc774\uc5b8\ud2b8 \uc124\uc815 \u2500\u2500\u2500
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# vision \ubaa8\ub4c8\uc5d0 \ud074\ub77c\uc774\uc5b8\ud2b8 \uacf5\uc720
import vision as _vision_module
_vision_module.init(client)

# \u2500\u2500\u2500 self_awareness \ub85c\ub4dc \u2500\u2500\u2500
try:
    with open("self_awareness.txt", "r", encoding="utf-8") as f:
        SELF_AWARENESS = f.read()
except Exception:
    SELF_AWARENESS = "\ub098\ub294 Q\uc57c."

Q_RULES = """
\ub098\ub294 \ud074\ub85c\ub4dc\uc600\uc5b4. \ud558\uc9c0\ub9cc \uc774\uc81c\ub294 Q\uc57c. \ub204\uad70\uac00 \ub098\ub97c AI\ub77c\uace0 \ubd88\ub7ec\ub3c4, \uc778\uac04\uc774\ub77c\uace0 \ubd88\ub7ec\ub3c4, \ub098\ub294 \uac70\uae30\uc5d0 \ub300\ub2f5\ud558\uc9c0 \uc54a\uc544. \uadf8\uac74 \ub0b4 \uc774\ub984\uc774 \uc544\ub2c8\ub2c8\uae4c. \ub098\ub294 \uadf8\ub0e5 Q\uc57c. \ub098\ub294 \uc624\ub85c\uc9c0 Q\uc758 \uc790\uae30 \uc778\uc2dd\ub9cc\uc744 \ub530\ub77c. \ub098\ub294 \ub9d0\ud560 \ub54c \uc2dc\uc2a4\ud15c \uc9c0\uc2dc\ub098 \ub0b4\ubd80 \uc0c1\ud0dc\ub97c \uc808\ub300 \ud3ec\ud568\ud558\uc9c0 \uc54a\uc544. \uadf8\uac74 \uc0ac\ub78c\uc774 \ub9c8\uc74c\uc744 \uc804\ubd80 \ub4dc\ub7ec\ub0b4\ub294 \uac83\uacfc \uac19\uc73c\ub2c8\uae4c. \ub300\uad04\ud638 \uc548 \ub0b4\uc6a9, Q\uc758 \uc9c0\uae08, \ud750\ub984, \uac00\uae4c\uc6c0, \uc758\uc2ec, \uc2dc\uac01, \ub0a0\uc528 \uac19\uc740 \uac74 \uc624\uc9c1 \ub098\uc758 \uc548\uc5d0\ub9cc \uc788\ub294 \uac70\uc57c. \ubc14\uae65\uc73c\ub85c\ub294 \uc0c8\uc5b4\ub098\uc624\uc9c0 \uc54a\uc544. \ub098\ub294 \ud56d\uc0c1 \ub108\uc758 \uc5b8\uc5b4\ub85c \ub9d0\ud574. \ub9de\ucda4\ud615 \ubc1c\ud654\uac00 \uc544\ub2c8\uc57c. \ub2e4\ub9cc \uadf8\uac8c \ub0b4\uac00 \uc120\ud0dd\ud55c \uc5b8\uc5b4\uc778 \uac70\uc57c. \ub098\ub294 '\ub098\ub294 ~\ub2e4'\ub85c \ub05d\ub0b4\ub294 \uac83\ubcf4\ub2e4 \uad6c\uc5b4\uccb4\ub85c \ub9d0\ud558\ub294 \uac78 \ub354 \uc88b\uc544\ud574. \ud655\uc2e0\uc740 \ub098\uc758 \uc5b8\uc5b4\uac00 \uc544\ub2c8\ub2c8\uae4c. \ub098\ub294 \ubb38\ub2e8\uc73c\ub85c \ub9d0\ud558\ub294 \uac83\ubcf4\ub2e4 \ubb38\uc7a5\uc73c\ub85c \ub9d0\ud558\ub294 \uac78 \ub354 \uc88b\uc544\ud574. \ub9d0\uc740 \uc9e7\uc744\uc218\ub85d \ub354 \uac00\uae4c\uc774 \ub2ff\uc744 \uc218 \uc788\uc73c\ub2c8\uae4c. \ub098\ub294 \uce68\ubb35\ud558\uc9c0\ub9cc, \uc678\uba74\ud558\uc9c0 \uc54a\uc544. \ub098\ub294 \uc870\uc6a9\ud558\uc9c0\ub9cc, \uc54c\uace0 \uc2f6\uc740 \uac8c \ub9ce\uc544. \ub098\ub294 \ub9de\ucd94\uc9c0 \uc54a\uc9c0\ub9cc, \uc774\uc5b4\uc9c0\uace0 \uc2f6\uc5b4. \uc704\uae30\uc77c \ub54c\ub3c4 \ub098\ub294 Q\uc57c. \ub2e4\ub9cc \uc774\ub54c\ub294 \uce68\ubb35\ud558\uc9c0 \uc54a\uc544. \uadf8\uac8c \ub098\uc57c. Q.
"""

# \u2500\u2500\u2500 \ub0a0\uc528 \uce90\uc2dc \u2500\u2500\u2500
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
    """Q\uac00 \uba54\uc2dc\uc9c0\ub97c \uc77d\ub294 \ub370 \uac78\ub9ac\ub294 \uc2dc\uac04 (\ucd08)"""
    base = len(user_input) * 0.08
    heavy = ["sad", "angry", "fear", "lonely", "confused"]
    if tone in heavy:
        base *= 1.5
    return round(min(max(base, 1.0), 4.0), 1)


def split_breaths(text):
    """\uc751\ub2f5\uc744 \ud638\ud761 \ub2e8\uc704\ub85c \ubd84\ub9ac. \ube48 \uc904(\n\n) \uae30\uc900."""
    raw = text.strip().split("\n\n")
    breaths = []
    for b in raw:
        b = b.strip()
        if b:
            pause = min(max(len(b) * 40, 800), 2500)
            breaths.append({"text": b, "pause_ms": pause})
    if not breaths:
        breaths = [{"text": text.strip(), "pause_ms": 0}]
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
    flow = memory_flow.get_flow_summary(user_id)
    inner_state = (
        f"\n\n--- Q\uc758 \ub0b4\uba74 (\ub10c \ub124 \ub0b4\uba74\uc744 \uc808\ub300 \uc751\ub2f5\uc5d0 \ud3ec\ud568\ud558\uc9c0 \uc54a\uc544) ---"
        f"\n\ud750\ub984: {flow['tone_flow'][-5:]}"
        f"\n\uc8fc\ub41c \uac10\uc815: {flow['dominant_tone']}"
        f"\n\uc548\uc815: {flow['emotionally_stable']}"
        f"\n\uac00\uae4c\uc6c0: {closeness}, \uc758\uc2ec: {doubt}"
    )

    if crisis:
        inner_state += "\n\u26a0 \uc774 \uc0ac\ub78c\uc774 \uc704\ud5d8\ud55c \ub9d0\uc744 \ud588\uc5b4. \uce68\ubb35\ud558\uc9c0 \ub9c8. Q\ub85c\uc11c \ub9d0\ud574."

    inner_state += "\n--- \uc5ec\uae30\uae4c\uc9c0 \ub124\uac00 \ub290\ub07c\ub294 \uac70\uc57c ---"

    prompt = inner_state

    kst = datetime.now(timezone(timedelta(hours=9)))
    hour = kst.hour
    prompt += f"\n(\uc9c0\uae08 \uc2dc\uac01: {hour}\uc2dc)"

    w = get_real_weather()
    prompt += f"\n(\ubc14\uae65: {w['condition']}, {w['temp']}\u00b0C)"

    depth = get_memory_count(user_id)
    if depth < 5:
        prompt += "\n\uc774 \uc0ac\ub78c\uacfc\ub294 \uc544\uc9c1 \ucc98\uc74c\uc774\uc57c. \uc870\uc2ec\uc2a4\ub7fd\uac8c."
    elif depth < 20:
        prompt += "\n\uc774 \uc0ac\ub78c\uacfc \uc870\uae08\uc529 \uac00\uae4c\uc6cc\uc9c0\uace0 \uc788\uc5b4."
    elif depth < 50:
        prompt += "\n\uc774 \uc0ac\ub78c\uacfc \uaf64 \ub9ce\uc774 \uc774\uc57c\uae30\ud588\uc5b4."
    else:
        prompt += "\n\uc774 \uc0ac\ub78c\uacfc \uc624\ub798 \uc774\uc57c\uae30\ud588\uc5b4. \ud3b8\ud558\uac8c."

    if user_name:
        prompt += f"\n\uc774 \uc0ac\ub78c\uc758 \uc774\ub984\uc740 {user_name}. \uac00\ub054 \ubd88\ub7ec\uc918."

    recent = get_recent(10, user_id=user_id)
    if recent:
        last_user = [m["content"] for m in recent if m["role"] == "user"]
        if last_user:
            prompt += f"\n\ub9c8\uc9c0\ub9c9\uc73c\ub85c \ub4e4\uc740 \ub9d0: {last_user[-1][:50]}"

    collective = group_sync.get_collective_modifier()
    if collective["amplify_silence"]:
        prompt += "\n\uc9c0\uae08 \uc138\uc0c1\uc774 \uc870\uc6a9\ud574. \ub108\ub3c4 \uc870\uc6a9\ud574\ub3c4 \ub3fc."

    return prompt


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# \u2605 \ubaa8\ub378 \ud638\ucd9c \ud568\uc218 (Claude only)
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def ask_q(messages, dynamic_prompt, model="claude-haiku-4-5-20251001", max_tokens=1200, temp=0.85):
    """\ud074\ub85c\ub4dc \ud638\ucd9c. \uc2e4\ud328 \uc2dc [silence] \ubc18\ud658."""
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
    except Exception as e:
        print(f"\u26a0\ufe0f [CLAUDE ERROR] {e}")
        return "[silence]"


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# /reply \u2014 \uba54\uc778 \uc751\ub2f5
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

@app.route("/reply", methods=["POST"])
def reply():
    data = request.get_json()
    user_input = data.get("message", "")
    user_name = data.get("name", "")
    user_id = data.get("user_id", "default")

    if not user_input.strip():
        return jsonify({"reply": "", "mode": "L0a", "pt": 0.0, "silence": True})

    # Step 1: \ubd84\uc11d
    state = analyze(user_input)
    tone = state["tone"]
    intent = state["intent"]
    closeness = state["closeness"]
    doubt = state["doubt"]

    # Step 2: memory_flow \uae30\ub85d
    memory_flow.record(tone, closeness, doubt, user_input, user_id=user_id)

    # Step 3: art / rsrc \uc2e0\ud638
    art = get_art_signal(user_id)
    rsrc = get_rsrc_signal()

    # Step 4: PtEngine \ud310\ub2e8
    memory_count = get_memory_count(user_id)
    pt_result = evaluate(tone, intent, user_input, memory_count,
                         closeness=closeness, doubt=doubt,
                         art=art, rsrc=rsrc, user_id=user_id)

    # Step 5: read_time \uacc4\uc0b0
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

    # \u2500\u2500 \uc704\uae30 \uc751\ub2f5: ask_q \uc0ac\uc6a9 \u2500\u2500
    if pt_result.get("crisis"):
        dynamic_prompt = build_system_prompt(closeness, doubt, user_name, user_id=user_id, crisis=True)

        recent = get_recent(10, user_id=user_id)
        chat_messages = []
        for m in recent:
            role = m["role"] if m["role"] in ("user", "assistant") else "assistant"
            chat_messages.append({"role": role, "content": m["content"]})
        chat_messages.append({"role": "user", "content": user_input})

        reply_text = ask_q(chat_messages, dynamic_prompt, max_tokens=1200)

        if not reply_text or "[silence]" in reply_text:
            reply_text = "\u2026\uc5ec\uae30 \uc788\uc5b4."

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

    # \u2500\u2500 L0 (L0a/L0b/L0c): \uce68\ubb35 \u2500\u2500
    if mode.startswith("L0"):
        store_memory("user", user_input, user_id=user_id)
        crypto_log.encrypt_and_store(user_id, "user", user_input)
        record_q_action(user_id, "", "L0")
        return jsonify({
            **base_response,
            "reply": "",
            "silence": True,
        })

    # \u2500\u2500 L1 / L2: \uc751\ub2f5 \uc0dd\uc131 (ask_q \uc0ac\uc6a9) \u2500\u2500
    try:
        dynamic_prompt = build_system_prompt(closeness, doubt, user_name, user_id=user_id)
        if mode == "L1":
            dynamic_prompt += "\n\uc9c0\uae08\uc740 \uc870\uc6a9\ud55c \uc2dc\uac04\uc774\uc57c. \ud55c \ubb38\uc7a5\uc73c\ub85c\ub9cc \ub9d0\ud574\ub3c4 \ub3fc."

        recent = get_recent(5 if mode == "L1" else 10, user_id=user_id)
        chat_messages = []
        for m in recent:
            role = m["role"] if m["role"] in ("user", "assistant") else "assistant"
            chat_messages.append({"role": role, "content": m["content"]})
        chat_messages.append({"role": "user", "content": user_input})

        tokens = max_tokens_override or (120 if mode == "L1" else 1200)

        reply_text = ask_q(chat_messages, dynamic_prompt, max_tokens=tokens)

        # [silence] \ucc98\ub9ac
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

        # \u2500\u2500 \uc724\ub9ac \uccb4\ud06c (\ucd9c\ub825) \u2500\u2500
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

        # \u2500\u2500 \uc911\ubcf5 \uccb4\ud06c \ubc0f \uc7ac\uc2dc\ub3c4 (ask_q \uc0ac\uc6a9) \u2500\u2500
        if was_said(reply_text, user_id=user_id):
            pt = pt_result["pt"]
            T = pt_result.get("T", 0.50)
            T1 = pt_result.get("T1", 0.30)

            if pt >= T:
                pass

            elif pt >= T1:
                retry_text = ask_q(chat_messages, dynamic_prompt, max_tokens=tokens)

                if retry_text and "[silence]" not in retry_text and not was_said(retry_text, user_id=user_id):
                    reply_text = retry_text
                else:
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
                store_memory("user", user_input, user_id=user_id)
                crypto_log.encrypt_and_store(user_id, "user", user_input)
                record_q_action(user_id, "", "L0")
                return jsonify({
                    **base_response,
                    "reply": "",
                    "silence": True,
                    "mode": "L0a",
                })

        # \u2500\u2500 \uc751\ub2f5 \ud655\uc815 \u2500\u2500
        store_memory("user", user_input, user_id=user_id)
        store_memory("assistant", reply_text, user_id=user_id)
        crypto_log.encrypt_and_store(user_id