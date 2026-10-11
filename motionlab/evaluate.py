from __future__ import annotations

import json
import math
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .util import atomic_json, digest, read_json


def probe(video, timeout=60):
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-show_entries", "stream=width,height,avg_frame_rate,nb_read_frames,duration:format=duration",
        "-of", "json", str(video)], capture_output=True, text=True, timeout=timeout, check=True)
    return json.loads(result.stdout)


def evaluate(folder, cfg, timeout=None):
    folder = Path(folder)
    video = folder / "animation.mp4"
    timeout = timeout or cfg["render_timeout_seconds"]
    deadline = time.monotonic()+timeout
    info = probe(video, timeout)
    stream = info["streams"][0]
    duration = float(info["format"]["duration"])
    numerator, denominator = map(int, stream["avg_frame_rate"].split("/"))
    if (int(stream["nb_read_frames"]) != 90 or stream["width"] != cfg["width"]
        or stream["height"] != cfg["height"] or numerator/denominator != 30
        or abs(duration-3) > 0.001):
        raise ValueError("Video dimensions, frame count, duration or FPS failed validation")
    # Decode ALL actual frames. This catches damaged packets and evaluates visible motion.
    decoded = subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(video),
        "-threads", str(cfg["threads"]), "-vf", "scale=320:180", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        capture_output=True, timeout=max(0.1,deadline-time.monotonic()), check=True)
    expected = 90*320*180*3
    if len(decoded.stdout) != expected:
        raise ValueError("Decoded video contains missing or extra frames")
    frames = np.frombuffer(decoded.stdout, dtype=np.uint8).reshape(90,180,320,3)
    # Contact sheet from encoded video, not from the generation buffer.
    selected = [0,8,16,24,32,40,56,72,89]
    sheet = Image.new("RGB", (960, 3*204), "#101827")
    draw = ImageDraw.Draw(sheet)
    extracted = folder / "frames"
    extracted.mkdir(exist_ok=True)
    for index, frame in enumerate(selected):
        im = Image.fromarray(frames[frame])
        im.save(extracted / f"frame-{frame:03d}.png")
        x, y = index%3*320, index//3*204
        sheet.paste(im, (x,y))
        draw.text((x+8,y+182), f"frame {frame:02d} / {frame/30:.2f}s",fill="white")
    sheet.save(folder / "contact-sheet.jpg",quality=90)
    motion = read_json(folder / "motion.json")
    if len(motion) != 90:
        raise ValueError("Missing frame metadata")
    clipped = 0
    for row in motion:
        for bounds in row["text_bounds"] + row["shape_bounds"]:
            if bounds[0] < 0 or bounds[1] < 0 or bounds[2] > cfg["width"] or bounds[3] > cfg["height"]:
                clipped += 1
    # Locate the three objects in decoded frames. Sample below static header and above footer.
    centers = []
    strengths = []
    scene=read_json(folder/'scene.json')
    for frame in frames:
        row_centers = []
        row_strength = []
        for obj in range(3):
            if scene.get('profile')=='senior':
                spec=scene['objects'][obj];radius=spec['size']/2
                left=int((min(spec['x0'],spec['x1'])-radius-18)/6)
                right=int((max(spec['x0'],spec['x1'])+radius+18)/6)
                top=int((min(spec['y0'],spec['y1'])-radius-18)/6)
                bottom=int((max(spec['y0'],spec['y1'])+radius+18)/6)
                crop=frame[top:bottom,left:right].astype(float)
                strength=np.maximum(np.max(np.abs(crop-frame[0,0].astype(float)),axis=2)-14,0)
            else:
                left,right=int((185+510*obj)/6),int((605+510*obj)/6)
                top=58
                crop = frame[58:137,left:right].astype(float)
                strength = np.maximum(crop.max(axis=2)-65,0)
            yy, xx = np.indices(strength.shape)
            total = strength.sum()
            if total < 1:
                raise ValueError("No visible object detected in encoded frame")
            row_centers.append([(strength*xx).sum()/total+left,(strength*yy).sum()/total+top])
            row_strength.append(float(total))
        centers.append(row_centers)
        strengths.append(row_strength)
    centers = np.asarray(centers)
    delta = np.diff(frames.astype(float), axis=0)
    pixel_change = np.mean(np.abs(delta), axis=(1,2,3))
    vel = np.diff(centers,axis=0)
    acc = np.diff(vel,axis=0)
    jerk = np.diff(acc,axis=0)
    # Exact trajectory metrics supplement, never replace encoded-video measurements.
    positions = np.array([[[s["x"],s["y"]] for s in row["states"]] for row in motion])
    trajectory_jerk = np.diff(positions,n=3,axis=0)
    rms = lambda x: float(np.sqrt(np.mean(np.square(x))))
    travel = np.linalg.norm(centers[-1]-centers[0],axis=1)
    has_motion = bool(np.max(travel) > 5 and np.max(pixel_change) > 0.1)
    end_drift = float(np.max(np.linalg.norm(centers[-10:]-centers[-1],axis=2)))
    if not has_motion or clipped or end_drift > 0.3:
        raise ValueError(f"Functional video check failed: motion={has_motion}, clipping={clipped}, end_drift={end_drift}")
    result = {
        "integrity": {"passed": True,"frames":90,"duration_seconds":duration,"fps":30,
                      "width":stream["width"],"height":stream["height"],"sha256":digest(video),
                      "full_decode":True,"clipped_layout_bounds":clipped,"detected_motion":has_motion},
        "objective": {"decoded_centroid_jerk_rms":rms(jerk),"decoded_centroid_acceleration_rms":rms(acc),
                      "trajectory_jerk_rms":rms(trajectory_jerk),"pixel_change_peak":float(pixel_change.max()),
                      "pixel_change_rms":rms(pixel_change),"end_drift_pixels":end_drift,
                      "minimum_travel_pixels":float(travel.min()),"readable_hold_frames":
                      89-max(s["end"] for s in read_json(folder / "scene.json")["objects"])},
        "subjective": {"status":"unevaluated","reason":"No independent visual evaluator configured",
                       "criteria":{key:None for key in cfg["evaluation_weights"]},"weighted_score":None,
                       "uncertainty":None},
        "limitations": ["Centroid jerk is a proxy for technical continuity, not design quality",
                        "Layout bounds detect viewport clipping, not semantic legibility or all overlaps",
                        "Creativity, hierarchy, sequencing quality, typography and polish require visual assessment"],
        "critique": []
    }
    last_arrival = max(s["end"] for s in read_json(folder/"scene.json")["objects"])
    peak_frame = int(np.argmax(np.linalg.norm(jerk,axis=2).max(axis=1)))+3
    result["critique"].append({"category":"technical_continuity",
        "observation":f"Peak decoded centroid jerk near frame {peak_frame}; RMS={rms(jerk):.6f}",
        "likely_cause":"Discrete easing boundary or evolving shape affects visible centroid",
        "test":"Compare curves under identical scene, displacement, timing and seed"})
    if scene.get('profile')=='senior':
        from .audio import evaluate_audio
        result['audio']=evaluate_audio(folder,timeout)
        result['profile']='senior-motion-designer'
        result['objective']['moving_frame_fraction']=float(np.mean(pixel_change>0.02))
        result['objective']['structure']={k:scene['params'].get(k) for k in
            ['visual_strategy','palette','material','transition','library_backend','font_scale']}
        if result['objective']['moving_frame_fraction']<0.9:
            result['critique'].append({'category':'liveliness','observation':'Below the supplied skill\'s 90% moving-frame target',
                'likely_cause':'Readable hold leaves most content still','test':'Test purposeful content progression without artificial camera motion'})
    if 89-last_arrival < 24:
        result["critique"].append({"category":"readable_hold", "observation":f"Only {89-last_arrival} hold frames",
                                 "likely_cause":"Late arrival", "test":"Reduce travel duration or stagger"})
    atomic_json(folder / "evaluation.json", result)
    atomic_json(folder / "decoded-motion.json", {"centroids":centers.tolist(),"pixel_change":pixel_change.tolist()})
    return result


def visual_evaluate(folders, cfg, workspace):
    """Optional independently operated evaluator; no model or paid API is assumed."""
    if not cfg.get("visual_evaluator_command"):
        return {"status":"unavailable", "assessments":{}}
    import random
    import shutil
    import uuid
    root = Path(workspace)/"blind-evaluation"
    root.mkdir(exist_ok=True)
    assignment = list(folders)
    random.SystemRandom().shuffle(assignment)
    mapping = {}
    samples = []
    for folder in assignment:
        sample = uuid.uuid4().hex
        mapping[sample] = str(folder)
        shutil.copyfile(Path(folder)/"animation.mp4",root/f"{sample}.mp4")
        samples.append({"id":sample,"video":str((root/f"{sample}.mp4").resolve())})
    request = root/"request.json"
    response = root/"response.json"
    response.unlink(missing_ok=True)
    atomic_json(request,{"samples":samples,"criteria":list(cfg["evaluation_weights"]),
                         "scale":[0,100],"required":"scores, critique, uncertainty, evaluator_id"})
    # Evaluator receives blind video identifiers; mapping is not in its request.
    try:
        subprocess.run(cfg["visual_evaluator_command"]+[str(request.resolve()),str(response.resolve())],
                       check=True,timeout=cfg["visual_evaluator_timeout_seconds"],capture_output=True)
        data = read_json(response)
        if set(data["assessments"]) != set(mapping):
            raise ValueError("Evaluator returned missing or unknown samples")
        results = {}
        for sample, row in data["assessments"].items():
            scores = row["scores"]
            if set(scores) != set(cfg["evaluation_weights"]) or any(
                not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=100 for v in scores.values()):
                raise ValueError("Invalid visual scores")
            if not row.get("evaluator_id") or not row.get("critique") or not 0<=row["uncertainty"]<=1:
                raise ValueError("Evaluator identity, critique and uncertainty are required")
            row["weighted_score"] = sum(scores[k]*weight for k,weight in cfg["evaluation_weights"].items())
            row["status"] = "externally_evaluated"
            results[mapping[sample]] = row
        return {"status":"complete","assessments":results,
                "limitations":"Evaluator independence/capability must be verified by its operator; scores alone do not promote rules"}
    except (OSError,subprocess.SubprocessError,ValueError,KeyError,TypeError) as error:
        return {"status":"failed","error":str(error),"assessments":{}}


def compare(base, candidate, threshold):
    a, b = base["objective"],candidate["objective"]
    gains = {}
    for key in ("decoded_centroid_jerk_rms","trajectory_jerk_rms"):
        gains[key] = (a[key]-b[key])/max(a[key],1e-9)
    passes = (min(gains.values()) >= threshold and candidate["integrity"]["passed"]
              and b["end_drift_pixels"] <= a["end_drift_pixels"]+0.05
              and b["readable_hold_frames"] >= 24)
    return {"supported":bool(passes),"relative_gains":gains,
            "scope":"Technical motion continuity only; no claim of professional visual improvement"}
