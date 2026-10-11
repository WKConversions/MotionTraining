from __future__ import annotations

import html
import json
import sqlite3
from pathlib import Path

from .util import atomic_bytes, atomic_json, digest, disk_bytes, now, read_json


def write_report(root, cfg):
    root = Path(root)
    connection = sqlite3.connect(root/"experiments.sqlite")
    rows = connection.execute("SELECT round,status,record,zip_sha256,error FROM rounds ORDER BY round").fetchall()
    candidate_counts = dict(connection.execute("SELECT status,count(*) FROM candidates GROUP BY status"))
    latest_event = connection.execute("SELECT time,kind,detail FROM events ORDER BY id DESC LIMIT 1").fetchone()
    connection.close()
    records = [json.loads(row[2]) for row in rows if row[1]=="completed" and row[2]]
    state = read_json(root/"controller.json") if (root/"controller.json").exists() else {"status":"not_started"}
    version = read_json(root/"skill"/"VERSION.json") if (root/"skill"/"VERSION.json").exists() else None
    # Load metadata directly from latest ZIP, without mutating active output.
    verified = False
    if (root/"motion-design-skill.zip").exists():
        from .skill import verify_bytes
        try:
            files = verify_bytes((root/"motion-design-skill.zip").read_bytes())
            verified = (root/"motion-design-skill.zip.sha256").read_text().strip() == digest(root/"motion-design-skill.zip")
            version = json.loads(files["VERSION.json"])
        except (ValueError,OSError,KeyError):
            verified = False
    summary = {"generated_at":now(),"controller":state,"completed_rounds":len(records),
        "rendered_animations":candidate_counts.get("completed",0),"candidate_statuses":candidate_counts,
        "skill":version,"latest_zip":str(root/"motion-design-skill.zip"),"zip_verified":verified,
        "validated_discoveries":sum(r["classification"]=="validated" for r in records),
        "rejected_hypotheses":sum(r["classification"]=="rejected" for r in records),
        "experimental_hypotheses":sum(r["classification"]=="experimental" for r in records),
        "subjective_quality":"Unevaluated unless an independently operated capable evaluator is configured",
        "disk_mb":round(disk_bytes(root)/(1024*1024),2),"disk_limit_mb":cfg["max_disk_mb"],
        "model_calls":0,"api_cost":0,"current_checkpoint":read_json(root/"checkpoint.json") if (root/"checkpoint.json").exists() else None,
        "latest_event":latest_event,"benchmark_history":[{"round":r["round"],"regression":r.get("regression")} for r in records if r.get("regression")],
        "most_successful_techniques":[r["finding"] for r in records if r["classification"]=="validated"],
        "weakest_unverified_capabilities":["Visual hierarchy","Typography legibility","Originality","Professional polish"],
        "round_statuses":[{"round":row[0],"status":row[1],"error":row[4]} for row in rows]}
    atomic_json(root/"status.json",summary)
    cards = []
    for r in reversed(records):
        candidates = [{"path":r["baseline_path"],"label":"Baseline"}]+[
            {"path":c["path"],"label":f"{c['label']}: {r['variable']}={c['value']}"} for c in r["candidates"]]
        media = []
        for c in candidates:
            path = html.escape(c["path"],quote=True)
            media.append(f'<figure><figcaption>{html.escape(c["label"])}</figcaption>'
                         f'<video controls preload="metadata" src="{path}/animation.mp4"></video>'
                         f'<a href="{path}/evaluation.json">Evaluation</a> · '
                         f'<a href="{path}/scene.json">Source configuration</a> · '
                         f'<a href="{path}/contact-sheet.jpg">Decoded frames</a></figure>')
        cards.append(f'<section><h2>Round {r["round"]} · {r["classification"]}</h2>'
                     f'<p>{html.escape(r["hypothesis"])}</p><p>{html.escape(r["reason"])}</p>'
                     f'<div class="samples">{"".join(media)}</div></section>')
    document = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Motion Training — experiment report</title><style>
body{background:#101827;color:#edf3fe;font:16px system-ui;max-width:1400px;margin:40px auto;padding:0 24px}
h1{font-size:42px}p{line-height:1.6;color:#bdcadf}a{color:#55d9c2}.samples{display:flex;flex-wrap:wrap;gap:20px}
figure{margin:0;flex:1;min-width:280px}video{width:100%;display:block;margin:12px 0}section{border-top:1px solid #344359;padding:24px 0}
.stats{display:flex;flex-wrap:wrap;gap:28px;background:#203049;padding:24px;border-radius:16px}figcaption{font-weight:600}
</style><h1>Motion Training</h1><p>Original procedural experiments. Technical evidence and visual judgment are tracked separately.</p>'''
    document += '<div class="stats">'+''.join(f'<span><strong>{html.escape(str(v))}</strong> {label}</span>' for label,v in [
        ("completed rounds",summary["completed_rounds"]),("renders",summary["rendered_animations"]),
        ("technical findings",summary["validated_discoveries"]),("MiB used",summary["disk_mb"])])+'</div>'
    document += f'<p>Controller: {html.escape(state["status"])} · ZIP integrity: {verified}. '
    document += '<a href="motion-design-skill.zip">Current skill ZIP</a> · <a href="status.json">Detailed status</a></p>'
    document += '<p>Subjective professional quality remains unevaluated without an independent capable evaluator. '
    document += 'Lower motion jerk alone does not establish better design.</p>'+''.join(cards)+'</html>'
    atomic_bytes(root/"report.html",document.encode())
    return summary
