from __future__ import annotations

import math
import random
from PIL import Image, ImageDraw, ImageFont

SCENARIOS = ("orbit", "type", "cards", "mask", "morph", "wave")
DEFAULTS = {"curve": "linear", "travel_frames": 24, "stagger_frames": 0, "overshoot": 0.0}


def easing(t, curve):
    t = max(0.0, min(1.0, t))
    if curve in ('arrive','depart','move'):
        if t in (0,1):
            return t
        x1,y1,x2,y2={'arrive':(.22,1,.36,1),'depart':(.64,0,.78,0),'move':(.65,0,.35,1)}[curve]
        lo,hi=0.0,1.0
        for _ in range(32):
            u=(lo+hi)/2
            x=3*(1-u)**2*u*x1+3*(1-u)*u*u*x2+u**3
            if x<t: lo=u
            else: hi=u
        return 3*(1-u)**2*u*y1+3*(1-u)*u*u*y2+u**3
    if curve == "linear":
        return t
    if curve == "cubic":
        return t * t * (3 - 2 * t)
    if curve == "quintic":
        return t ** 3 * (10 - 15 * t + 6 * t * t)
    if curve == "cosine":
        return (1 - math.cos(math.pi * t)) / 2
    if curve == "septic":
        return t**4*(35-84*t+70*t*t-20*t**3)
    if curve == "sine-quintic":
        return 0.5*((1-math.cos(math.pi*t))/2+t**3*(10-15*t+6*t*t))
    raise ValueError(f"Unsupported curve: {curve}")


def plan(scenario, params, seed=0, profile=None):
    if scenario not in SCENARIOS:
        raise ValueError("Unknown scenario")
    p = {**DEFAULTS, **params}
    if p["travel_frames"] < 6 or p["stagger_frames"] < 0:
        raise ValueError("Invalid timing")
    rng = random.Random(seed)
    theme = ["#55D9C2", "#B4A4FF", "#FFCF78"][rng.randrange(3)]
    specs = []
    for i in range(3):
        start = 8 + i * p["stagger_frames"]
        # Canonical layout units; all geometries remain within the 1920x1080 design.
        x0 = 340 + i*510 + rng.randint(-20,20)
        specs.append({"id": i, "start": start, "end": start + p["travel_frames"],
                      "x0": x0, "x1": x0+rng.randint(60,110),
                      "y0": rng.randint(630,680), "y1": rng.randint(480,540),
                      "size": rng.randint(180,220)})
    if max(s["end"] for s in specs) > 72:
        raise ValueError("Arrival leaves too little readable hold time")
    if profile=='senior':
        for obj in specs:
            obj['size']=300 if obj['id']==1 else 130
            obj['y0']=650; obj['y1']=520 if obj['id']==1 else 570
    return {"scenario": scenario, "params": p, "seed": seed, "theme": theme, "objects": specs,
            "profile":profile}


def states(scene, frame):
    result = []
    for obj in scene["objects"]:
        t = (frame - obj["start"]) / (obj["end"] - obj["start"])
        q = easing(t, scene["params"]["curve"])
        # Original bounded transient; zero before and after arrival.
        q += scene["params"]["overshoot"] * math.sin(math.pi * max(0, min(1, t)))
        result.append({**obj, "x": obj["x0"] + (obj["x1"] - obj["x0"]) * q,
                       "y": obj["y0"] + (obj["y1"] - obj["y0"]) * q,
                       "progress": q})
    return result


FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def frame_image(scene, frame, cfg):
    if scene.get('profile')=='senior':
        from .senior_design import frame_image as senior_frame
        return senior_frame(scene,frame,cfg)
    w, h = cfg["width"], cfg["height"]
    sx, sy = w / 1920, h / 1080
    im = Image.new("RGB", (w, h), cfg["background"])
    draw = ImageDraw.Draw(im)
    font = ImageFont.truetype(FONT, max(10, round(28 * sy)))
    title_font = ImageFont.truetype(BOLD_FONT, max(10, round(72 * sy)))
    object_font = ImageFont.truetype(BOLD_FONT, max(10, round(38 * sy)))
    text_bounds = []
    shape_bounds = []

    def text(x, y, value, f, fill, anchor=None):
        pos = (round(x * sx), round(y * sy))
        kw = {"font": f, "anchor": anchor}
        box = draw.textbbox(pos, value, **kw)
        draw.text(pos, value, fill=fill, **kw)
        text_bounds.append(list(box))

    text(170, 130, "MOTION / LAB", font, "#8393AA")
    titles = {"orbit": "A deliberate arrival.", "type": "Make every word count.",
              "cards": "Three ideas. One rhythm.", "mask": "Reveal with purpose.",
              "morph": "A change of shape.", "wave": "Follow a common pulse."}
    text(170, 200, titles[scene["scenario"]], title_font, "#EFF4FF")
    draw.line((round(170*sx), round(335*sy), round(1750*sx), round(335*sy)), fill="#2A364C", width=max(1, round(2*sx)))
    text(170, 924, "ORIGINAL PROCEDURAL STUDY", font, "#8393AA")
    text(1750, 924, "03 SEC", font, "#8393AA", "ra")
    for state in states(scene, frame):
        x, y, size, q = state["x"], state["y"], state["size"], state["progress"]
        box = [round((x-size/2)*sx), round((y-size/2)*sy), round((x+size/2)*sx), round((y+size/2)*sy)]
        shape_bounds.append(box)
        color = scene["theme"] if state["id"] == 1 else "#DDE7F5"
        scene_type = scene["scenario"]
        if scene_type == "orbit":
            draw.ellipse(box, fill=color)
            r = 19 * (1 + q)
            dot = (x + 38*math.cos(q*math.pi), y + 38*math.sin(q*math.pi))
            draw.ellipse((round((dot[0]-r)*sx),round((dot[1]-r)*sy),round((dot[0]+r)*sx),round((dot[1]+r)*sy)), fill=cfg["background"])
        elif scene_type == "type":
            draw.rounded_rectangle(box, radius=round(28*sx), outline=color, width=max(1,round(3*sx)))
            text(x, y, ["IDEA", "MOVE", "LAND"][state["id"]], object_font, color, "mm")
        elif scene_type == "mask":
            # Horizontal reveal inside a stationary moving outline.
            draw.rounded_rectangle(box, radius=round(24*sx), outline=color, width=max(1,round(3*sx)))
            reveal = max(0, min(1, q))
            if reveal > 0:
                draw.rectangle([box[0]+4,box[1]+4,box[0]+round((box[2]-box[0]-8)*reveal)+4,box[3]-4],fill=color)
        elif scene_type == "morph":
            radius = max(1, round((18 + 92*q)*sx))
            draw.rounded_rectangle(box, radius=radius, fill=color)
        elif scene_type == "wave":
            points = []
            for j in range(81):
                px = x-size/2 + size*j/80
                py = y + 50*math.sin(j/80*math.pi*2 + q*math.pi)
                points.append((round(px*sx),round(py*sy)))
            draw.line(points, fill=color, width=max(2,round(12*sx)))
        else:
            draw.rounded_rectangle(box, radius=round(24*sx), fill="#233149", outline=color, width=max(1,round(3*sx)))
            text(x, y, ["01", "02", "03"][state["id"]], object_font, color, "mm")
        draw.line((round((x-45)*sx),round(815*sy),round((x+45)*sx),round(815*sy)),fill=color,width=max(1,round(3*sx)))
    # Expose renderer layout bounds, not assumed subjective quality.
    return im, {"frame": frame, "states": states(scene,frame), "text_bounds": text_bounds, "shape_bounds": shape_bounds}
