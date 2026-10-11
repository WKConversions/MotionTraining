"""Adopt an existing skill verbatim, with recoverable provenance and a journaled ZIP."""
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath

from .skill import SkillStore, encode
from .storage import Database
from .util import atomic_bytes, atomic_json, digest, now
from .versioning import History


SENIOR_DEFAULTS = {
    "curve":"move", "travel_frames":24, "stagger_frames":3, "overshoot":0.0,
    "palette":"mint", "material":"flat", "visual_strategy":"routing", "transition":"carry",
    "library_backend":"pillow", "font_scale":1.0, "music_vibe":"tech-minimal", "music_bpm":120,
    "sfx_offset_frames":5, "voice_rate":175, "voice_pitch":50, "duck_db":6
}


def read_supplied_skill(path):
    path=Path(path)
    if path.stat().st_size > 32*1024*1024:
        raise ValueError("Supplied skill ZIP exceeds 32 MiB")
    with zipfile.ZipFile(path) as archive:
        entries=archive.infolist()
        if len(entries)>2000 or sum(i.file_size for i in entries)>64*1024*1024:
            raise ValueError("Skill exceeds safe import limits")
        names=[i.filename for i in entries if not i.is_dir()]
        roots={PurePosixPath(n).parts[0] for n in names}
        if len(roots)!=1 or len(set(names))!=len(names) or archive.testzip():
            raise ValueError("Skill must be one intact root with unique members")
        root=next(iter(roots))
        for i in entries:
            p=PurePosixPath(i.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in i.filename or stat.S_ISLNK(i.external_attr>>16):
                raise ValueError("Unsafe skill ZIP member")
        files={n[len(root)+1:]:archive.read(n) for n in names}
        if "SKILL.md" not in files:
            raise ValueError("Supplied skill has no SKILL.md")
        files["SKILL.md"].decode("utf-8")
        return root,files


def import_skill(path, output):
    import fcntl
    root=Path(output)
    root.mkdir(parents=True,exist_ok=True)
    with open(root/"controller.lock","a+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        name,supplied=read_supplied_skill(path)
        store=SkillStore(root)
        files,previous=store.load()
        checksum=digest(path)
        provenance_path="training/import-provenance.json"
        if provenance_path in files and json.loads(files[provenance_path])["source_zip_sha256"]==checksum:
            return {"already_imported":True,"checksum":checksum}
        overlaps=(set(files)&set(supplied))-{ "SKILL.md" }
        if overlaps:
            raise ValueError(f"Import conflicts with existing learning files: {sorted(overlaps)}")
        number=json.loads(files["VERSION.json"])["round"]+1
        atomic_bytes(root/"imports"/f"{name}-{checksum[:16]}.zip",Path(path).read_bytes())
        updated={**files,**supplied}
        import hashlib
        updated[provenance_path]=encode({"skill_name":name,"source_zip_sha256":checksum,"imported_at":now(),
            "import_round":number,"original_members":{n:hashlib.sha256(b).hexdigest() for n,b in supplied.items()},
            "preservation":"All supplied member bytes are retained unchanged; training notes are additive"})
        updated["training/profile.json"]=encode({"name":"senior","baseline":name,"import_round":number})
        updated["training/AUTONOMOUS.md"]=b'''# Autonomous research profile

The user's current request authorizes continuous original experiments across the supplied
skill's capabilities. Preserve SKILL.md and library/ verbatim. The ordinary client-film
approval workflow remains in the original skill; this research profile uses synthetic briefs,
procedural assets, original synthesized music/effects, and local draft speech.
Do not fetch or imitate reference videos. Existing historical reference material is preserved,
not used as visual examples. Never publish the separate private library artifact automatically.
Cycle through motion, timing, transitions, visuals, typography, materials, originality,
rendering libraries, music, sound effects, voice-over and sound-picture synchronization.
Analyze encoded video and decoded audio. Validate transferable technical gains, and keep
subjective findings experimental without a capable independent evaluator. Do not call local
robotic draft speech a professional voice-over. Record gaps and propose future hypotheses.
Every completed round rebuilds the full ZIP, including the original 105 files. Never replace
approved library modules with an unverified preference. Store validated additions in knowledge/
and techniques/ with evidence. Every next round loads the newest verified ZIP.
'''
        updated["techniques/defaults.json"]=encode(SENIOR_DEFAULTS)
        version=json.loads(updated["VERSION.json"])
        parts=list(map(int,version["version"].split('.')))
        version["version"]=f"{parts[0]}.{parts[1]+1}.0"
        updated["VERSION.json"]=encode(version)
        record={"id":f"round-{number:06d}","round":number,"completed_at":now(),"classification":"imported",
            "research_domain":"baseline_import","objective":"Adopt the user's existing skill without replacing its knowledge",
            "hypothesis":"User-selected starting point; not a measured quality claim","reason":f"Imported {name} with {len(supplied)} byte-preserved files",
            "loaded_zip_sha256":previous,"skill_version_loaded":json.loads(files["VERSION.json"])["version"],
            "baseline_params":json.loads(files["techniques/defaults.json"]),"chosen_params":SENIOR_DEFAULTS,
            "variable":"skill_baseline","chosen_value":name,"finding":"Existing approved skill adopted, no new improvement asserted",
            "baseline_path":"","baseline_evaluation":{},"candidates":[],"comparison":{"scope":"Baseline import, not an experiment"},
            "transfer_validation":[],"visual_evaluation":{"status":"not_applicable"},"regression":None,"weaknesses":[],
            "source_zip_sha256":checksum,"source":f"imports/{name}-{checksum[:16]}.zip",
            "zip_snapshot":f"archives/motion-design-skill-round-{number:06d}.zip"}
        folder=root/"rounds"/f"{number:06d}"
        atomic_json(folder/"record.json",record)
        db=Database(root)
        db.round_status(number,"publishing",record)
        final,zip_sha=store.finish_round(updated,record)
        commit=History(root).snapshot(final)
        db.round_status(number,"completed",record,zip_sha)
        db.event("skill_imported",{"name":name,"members":len(supplied),"source_checksum":checksum,"git_commit":commit})
        store.load()
        return {"name":name,"members":len(supplied),"round":number,"source_checksum":checksum,"zip_checksum":zip_sha}
