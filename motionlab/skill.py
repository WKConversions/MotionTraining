from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path, PurePosixPath

from .design import DEFAULTS
from .util import atomic_bytes, atomic_json, digest, now

PREFIX = "motion-design-skill/"
REQUIRED = {"SKILL.md", "VERSION.json", "CHANGELOG.md", "knowledge/animation-principles.md",
            "knowledge/motion-timing.md", "knowledge/composition.md", "knowledge/typography.md",
            "knowledge/transitions.md", "knowledge/procedural-animation.md", "knowledge/discoveries.md",
            "techniques/defaults.json", "techniques/interpolation.py", "experiments/experiment-index.json",
            "experiments/validated-findings.md", "experiments/rejected-hypotheses.md",
            "evaluations/benchmark-summary.json", "evaluations/regression-results.json"}


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True)+"\n").encode()


def initial_files():
    files = {
        "SKILL.md": b'''---
name: motion-design
description: Generate original procedural three-second animations using experimentally supported techniques.
---

# Motion design through controlled experiments

Use the existing isolated checkout; do not create worktrees unless requested.
Load and verify the newest skill ZIP before selecting an experiment.
Read techniques/defaults.json and knowledge/discoveries.md: accepted parameter rules must
actually influence subsequent animation generation. Preserve original sources and seeds.
Render exactly 90 frames at 30 FPS. Analyze encoded video, not just code.
Create original shapes, typography and layouts. Do not use reference videos or templates.
Keep one-variable comparisons and test transfers across at least two held-out scenes.
Technical proxy improvements do not prove aesthetics. Leave visual judgments unevaluated
without a capable independent visual evaluator. Never invent scores.
Archive all completed rounds including unsuccessful experiments. Never promote findings
on scores alone. Verify the ZIP manifest before replacing it, retain archives, and reload
the verified ZIP on the next round. Preserve permanent, experimental and historical knowledge.
Run a broader technical regression every ten rounds. Do not assume more motion is better.
''',
        "VERSION.json": encode({"version":"0.1.0","round":0,"created_at":now()}),
        "CHANGELOG.md": b"# Changelog\n\n- Initial original renderer and guarded experiment protocol.\n",
        "techniques/defaults.json": encode(DEFAULTS),
        "techniques/interpolation.py": Path(__file__).with_name("design.py").read_bytes(),
        "experiments/experiment-index.json": encode([]),
        "experiments/validated-findings.md": b"# Validated findings\n\nNo experimental findings yet.\n",
        "experiments/rejected-hypotheses.md": b"# Rejected hypotheses\n",
        "evaluations/benchmark-summary.json": encode({"subjective_status":"unevaluated", "history":[]}),
        "evaluations/regression-results.json": encode([]),
        "knowledge/discoveries.md": b"# Permanent experimental knowledge\n\nNo experimental rules promoted yet.\n",
    }
    principles = {
        "animation-principles": "General foundations (not experimental discoveries): purposeful motion, clear hierarchy, legible holds.\n",
        "motion-timing": "Hypotheses: smooth endpoint derivatives may reduce discrete jerk. Validate in encoded video before promotion.\n",
        "composition": "General foundation: keep intended content in frame. Bounds checks do not prove good composition.\n",
        "typography": "General foundation: readable text requires visual review. Renderer bounds checks establish viewport fit only.\n",
        "transitions": "Experimental: reveals and morphs may distort centroid proxies. Test separately.\n",
        "procedural-animation": "Use deterministic seeds, bounded frame-indexed functions and reproducible parameters.\n",
    }
    for key, body in principles.items():
        files[f"knowledge/{key}.md"] = ("# "+key.replace("-"," ").title()+"\n\n"+body).encode()
    return files


def build_bytes(files):
    manifest = {name:hashlib.sha256(body).hexdigest() for name,body in sorted(files.items())}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as archive:
        for name,body in sorted({**files,"MANIFEST.json":encode(manifest)}.items()):
            archive.writestr(PREFIX+name,body)
    content = buf.getvalue()
    verify_bytes(content)
    return content


def verify_bytes(content):
    if len(content) > 32*1024*1024:
        raise ValueError("Skill ZIP exceeds 32 MiB")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            items = archive.infolist()
            if len(items)>2000 or sum(i.file_size for i in items)>64*1024*1024:
                raise ValueError("Oversized skill contents")
            names = [i.filename for i in items]
            if len(set(names)) != len(names):
                raise ValueError("Duplicate ZIP members")
            if any(not n.startswith(PREFIX) or '..' in PurePosixPath(n).parts or '\\' in n for n in names):
                raise ValueError("Unsafe ZIP paths")
            if archive.testzip() is not None:
                raise ValueError("ZIP CRC failure")
            files = {name[len(PREFIX):]:archive.read(name) for name in names}
    except (zipfile.BadZipFile,KeyError,RuntimeError) as exc:
        raise ValueError("Corrupt skill ZIP") from exc
    if not REQUIRED <= files.keys() or "MANIFEST.json" not in files:
        raise ValueError("Skill is missing required files")
    manifest = json.loads(files.pop("MANIFEST.json"))
    actual = {name:hashlib.sha256(body).hexdigest() for name,body in files.items()}
    if manifest != actual:
        raise ValueError("Skill content checksum mismatch")
    version = json.loads(files["VERSION.json"])
    history = json.loads(files["experiments/experiment-index.json"])
    if version["round"] != len(history) or [r["round"] for r in history] != list(range(1,len(history)+1)):
        raise ValueError("Noncontiguous experiment history")
    return files


class SkillStore:
    def __init__(self, root):
        self.root = Path(root)
        self.archives = self.root/"archives"
        self.archives.mkdir(parents=True,exist_ok=True)
        self.current = self.root/"motion-design-skill.zip"

    def archive_path(self, round_number):
        return self.archives/f"motion-design-skill-round-{round_number:06d}.zip"

    def publish(self, files):
        data = build_bytes(files)
        number = json.loads(files["VERSION.json"])["round"]
        path = self.archive_path(number)
        # Existing round archives are immutable. Resume may republish identical bytes only.
        if path.exists():
            old = verify_bytes(path.read_bytes())
            if old != files:
                raise ValueError("Attempt to overwrite an existing round snapshot")
            data = path.read_bytes()
        else:
            atomic_bytes(path,data)
        # Resume can repair interruption between the archive and sidecar writes.
        atomic_bytes(path.with_suffix(".zip.sha256"),(digest(path)+"\n").encode())
        atomic_bytes(self.current,data)
        atomic_bytes(self.current.with_suffix(".zip.sha256"),(digest(self.current)+"\n").encode())
        verify_bytes(self.current.read_bytes())
        return digest(self.current)

    def load(self):
        candidates = []
        if self.current.exists():
            candidates.append(self.current)
        candidates.extend(sorted(self.archives.glob("*.zip"),reverse=True))
        valid = []
        errors = []
        for path in candidates:
            try:
                sidecar = path.with_suffix(".zip.sha256")
                if sidecar.exists() and sidecar.read_text().strip() != digest(path):
                    raise ValueError("Archive SHA256 sidecar invalid")
                files = verify_bytes(path.read_bytes())
                if not sidecar.exists():
                    # An internally verified immutable archive may have been interrupted
                    # before its sidecar was persisted. Never accept an existing mismatch.
                    if path == self.current:
                        raise ValueError("Current ZIP SHA256 sidecar missing")
                    atomic_bytes(sidecar,(digest(path)+"\n").encode())
                valid.append((json.loads(files["VERSION.json"])["round"],path,files))
            except (ValueError,OSError,json.JSONDecodeError) as error:
                errors.append({"path":str(path),"error":str(error)})
        if not valid:
            if candidates:
                raise ValueError("No recoverable verified skill archive; refusing to erase knowledge")
            files = initial_files()
            self.publish(files)
            return files,digest(self.current)
        _, source, files = max(valid,key=lambda v:v[0])
        if source != self.current:
            if self.current.exists():
                damaged = self.root/"recovery"/("previous-"+digest(self.current)+".zip")
                atomic_bytes(damaged,self.current.read_bytes())
            atomic_bytes(self.current,source.read_bytes())
            atomic_bytes(self.current.with_suffix(".zip.sha256"),(digest(self.current)+"\n").encode())
            atomic_json(self.root/"last-recovery.json",{"time":now(),"restored_from":str(source),"errors":errors})
        # A readable copy is convenient but the validated ZIP remains authoritative.
        for name,body in files.items():
            atomic_bytes(self.root/"skill"/name,body)
        return files,digest(self.current)

    def finish_round(self, files, record):
        updated = dict(files)
        history = json.loads(files["experiments/experiment-index.json"])
        if record["round"] != len(history)+1:
            raise ValueError("Invalid next round number")
        history.append(record)
        updated["experiments/experiment-index.json"] = encode(history)
        version = json.loads(files["VERSION.json"])
        if record["classification"] == "validated":
            parts = list(map(int,version["version"].split(".")))
            parts[-1] += 1
            version["version"] = '.'.join(map(str,parts))
            rule = record["finding"]
            updated["knowledge/discoveries.md"] += (f"\n## Round {record['round']}\n{rule}\n").encode()
            updated["experiments/validated-findings.md"] += (f"\n- Round {record['round']}: {rule}\n").encode()
            defaults = json.loads(files["techniques/defaults.json"])
            defaults[record["variable"]] = record["chosen_value"]
            updated["techniques/defaults.json"] = encode(defaults)
            # Keep the actual tested implementation with accepted new curve defaults.
            updated["techniques/interpolation.py"] = Path(__file__).with_name("design.py").read_bytes()
        elif record["classification"] == "rejected":
            updated["experiments/rejected-hypotheses.md"] += (
                f"\n- Round {record['round']}: {record['hypothesis']} — {record['reason']}\n").encode()
        version.update({"round":record["round"],"updated_at":record["completed_at"]})
        updated["VERSION.json"] = encode(version)
        updated["CHANGELOG.md"] += (
            f"\n- Round {record['round']}: {record['classification']}; {record['reason']}.\n").encode()
        # Concise reproducible experiment source configurations are inside the ZIP; videos stay outside.
        updated[f"experiments/round-{record['round']:06d}.json"] = encode(record)
        # The skill ZIP includes the complete runnable research infrastructure as
        # scoped training tooling, separate from the unchanged approved library.
        package=Path(__file__).parent
        for source in package.glob('*.py'):
            updated['training/project/motionlab/'+source.name]=source.read_bytes()
        updated['training/project/requirements.txt']=package.parent.joinpath('requirements.txt').read_bytes()
        for name in ['config.json','continuous.json']:
            updated['training/project/'+name]=package.parent.joinpath(name).read_bytes()
        updated['training/START.md']=b'''# Run the research tooling

The library and SKILL.md are usable as the supplied senior skill. The training/project/
folder preserves the exact research implementation and pinned Python requirements.
The full GitHub project supplies operating documentation and source-control history.
When using the exported tooling separately, retain the downloaded verified skill ZIP,
copy it to training/project/runtime/motion-design-skill.zip along with its SHA256 sidecar,
then run python -m motionlab verify before python -m motionlab resume --continuous.
Processes do not survive snapshots. Study both video and audio and keep subjective
findings experimental without independent evidence. Do not fetch reference videos.
'''
        if record.get('editorial_reviews'):
            updated['training/editorial-reviews.json']=encode(record['editorial_reviews'])
        bench = json.loads(files["evaluations/benchmark-summary.json"])
        bench["history"].append({"round":record["round"],"comparison":record["comparison"],
                                 "classification":record["classification"],"subjective":record["visual_evaluation"]["status"]})
        updated["evaluations/benchmark-summary.json"] = encode(bench)
        regression = json.loads(files["evaluations/regression-results.json"])
        if record.get("regression"):
            regression.append(record["regression"])
        updated["evaluations/regression-results.json"] = encode(regression)
        return updated,self.publish(updated)
