#!/usr/bin/env python3
"""AI Producer — live video-follows-audio director for OBS.

The same loudest-mic-wins brain the editor uses, running in real time:
it watches every audio input's level in OBS and switches the Program scene
to whoever is talking, with anti-flicker hysteresis and a wide fallback.

Mapping: an OBS scene named e.g. "CAM 1" pairs with the audio input whose
name contains the same tag ("cam 1 mic", "CAM1 audio", …). A scene whose
name contains "wide"/"all" is used for cross-talk and silence.

Run:  ./_fwenv/bin/python ai_producer.py [--min-shot 2.0] [--activate -38]
Stop: Ctrl-C.
"""

import argparse
import asyncio
import json
import re
import time

import simpleobsws

CFG = "/Users/studio/Library/Application Support/obs-studio/plugin_config/obs-websocket/config.json"
conf = json.load(open(CFG))
URL = f"ws://127.0.0.1:{conf['server_port']}"
PASSWORD = conf["server_password"]


def norm(s):  # "CAM 1 Mic" -> "cam1mic"
    return re.sub(r"[^a-z0-9]", "", s.lower())


async def main(min_shot: float, activate_db: float, poll: float):
    ws = simpleobsws.WebSocketClient(
        url=URL, password=PASSWORD,
        identification_parameters=simpleobsws.IdentificationParameters(
            eventSubscriptions=(1 << 16)))   # InputVolumeMeters (high-volume)
    await ws.connect()
    await ws.wait_until_identified()
    print("✓ connected to OBS")

    scenes = (await ws.call(simpleobsws.Request("GetSceneList"))).responseData
    scene_names = [s["sceneName"] for s in scenes["scenes"]]
    wide = next((s for s in scene_names
                 if re.search(r"wide|all|room|group", s, re.I)), None)
    cams = [s for s in scene_names
            if s != wide and re.search(r"cam|guest|host", s, re.I)]
    if not cams:
        cams = [s for s in scene_names if s != wide]
    print(f"  scenes: {scene_names}  (wide: {wide})")

    inputs = (await ws.call(simpleobsws.Request("GetInputList"))).responseData
    audio_inputs = []
    for i in inputs["inputs"]:
        kind = i.get("inputKind", "")
        if any(k in kind for k in ("audio", "capture", "coreaudio", "av_capture")):
            audio_inputs.append(i["inputName"])

    # scene <-> audio pairing by shared tag (digits or normalized overlap)
    pair = {}
    for sc in cams:
        tag = norm(sc)
        best = None
        for a in audio_inputs:
            na = norm(a)
            if tag and (tag in na or na in tag):
                best = a; break
            m = re.search(r"\d+", sc)
            if m and m.group() in na:
                best = a; break
        if best:
            pair[best] = sc
    if not pair and len(cams) == 1 and audio_inputs:
        pair[audio_inputs[0]] = cams[0]
    print(f"  pairing: {pair or 'NONE — name scenes & mics with matching tags'}")

    import math
    levels = {}          # input -> latest dB
    state = {"current": None, "since": 0.0}

    async def on_meters(data):
        for m in data["inputs"]:
            mag = m.get("inputLevelsMul") or []
            if mag and mag[0]:
                lvl = max(ch[1] if len(ch) > 1 else ch[0] for ch in mag)
                levels[m["inputName"]] = 20 * math.log10(max(lvl, 1e-9))

    ws.register_event_callback(on_meters, "InputVolumeMeters")

    print(f"● directing (min shot {min_shot}s, gate {activate_db} dB) — Ctrl-C to stop")
    while True:
        await asyncio.sleep(poll)
        now = time.time()
        talkers = {a: db for a, db in levels.items()
                   if a in pair and db > activate_db}
        if not talkers:
            target = wide or state["current"]
        elif len(talkers) > 1 and wide:
            target = wide
        else:
            target = pair[max(talkers, key=talkers.get)]
        if not target or target == state["current"]:
            continue
        if now - state["since"] < min_shot:
            continue
        await ws.call(simpleobsws.Request(
            "SetCurrentProgramScene", {"sceneName": target}))
        db_txt = ", ".join(f"{k.split()[0]}:{v:.0f}" for k, v in levels.items() if k in pair)
        print(f"  ✂ CUT → {target}   [{db_txt}]")
        state.update(current=target, since=now)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-shot", type=float, default=2.0)
    ap.add_argument("--activate", type=float, default=-38.0)
    ap.add_argument("--poll", type=float, default=0.15)
    a = ap.parse_args()
    try:
        asyncio.run(main(a.min_shot, a.activate, a.poll))
    except KeyboardInterrupt:
        print("\nproducer stopped")
