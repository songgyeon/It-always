# ══════════════════════════════════════════
# ★ Q 상태 — "Q에 대하여" 화면용
# ══════════════════════════════════════════

@app.route("/q-status", methods=["GET"])
def q_status():
    """Q의 오늘 상태. 설정이 아니라 존재 리포트."""
    user_id = request.args.get("user_id", "default")

    # ── Q Day 계산 ──
    # first_launch는 앱에서 보내줌 (밀리초 timestamp)
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
