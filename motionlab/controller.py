from __future__ import annotations

import fcntl
import json
import os
import shutil
import signal
import time
import hashlib
from pathlib import Path

from .design import SCENARIOS, plan
from .evaluate import compare, evaluate, visual_evaluate
from .render import render
from .skill import SkillStore
from .storage import Database
from .util import atomic_bytes, atomic_json, digest, disk_bytes, now, read_json
from .versioning import History


class BudgetStop(Exception):
    pass


class Controller:
    def __init__(self, cfg):
        self.cfg = cfg
        self.root = Path(cfg["output"])
        self.root.mkdir(parents=True,exist_ok=True)
        self.store = SkillStore(self.root)
        self.database = Database(self.root)
        self.history = History(self.root)
        self.deadline = time.monotonic()+cfg["max_runtime_seconds"]
        self.stopping = False

    def check_budget(self):
        if self.stopping or (self.root/"STOP").exists():
            raise BudgetStop("Graceful stop requested")
        if time.monotonic() >= self.deadline:
            raise BudgetStop("Maximum runtime reached")
        # Reserve 64 MiB for atomic checkpoints / ZIP publication / the active render.
        if disk_bytes(self.root)+64*1024*1024 > self.cfg["max_disk_mb"]*1024*1024:
            raise BudgetStop("Disk budget reached (including publication reserve)")

    def timeout(self):
        self.check_budget()
        return max(0.1,min(self.cfg["render_timeout_seconds"],self.deadline-time.monotonic()))

    def candidate(self, number, label, scenario, params, seed):
        self.check_budget()
        folder = self.root/"rounds"/f"{number:06d}"/label
        scene = plan(scenario,params,seed)
        identity = {"scene":scene,"width":self.cfg["width"],"height":self.cfg["height"],
                    "fps":self.cfg["fps"],"background":self.cfg["background"],
                    "pipeline_sha256":hashlib.sha256(b''.join(Path(__file__).with_name(n).read_bytes()
                        for n in ("design.py","render.py","evaluate.py"))).hexdigest()}
        marker = folder/"ready.json"
        if marker.exists():
            try:
                saved = read_json(marker)
                assessment = read_json(folder/"evaluation.json")
                if (saved["identity"] == identity and digest(folder/"animation.mp4") == saved["checksum"]
                    and digest(folder/"evaluation.json") == saved.get("evaluation_sha256")
                    and digest(folder/"motion.json") == saved.get("motion_sha256")):
                    self.database.candidate(number,label,"completed",scene,folder,assessment)
                    return folder,assessment
            except (OSError,ValueError,KeyError):
                pass
        for attempt in range(self.cfg["retries"]+1):
            self.database.candidate(number,label,"rendering",scene,folder)
            atomic_json(self.root/"checkpoint.json",{"round":number,"candidate":label,"attempt":attempt,"time":now()})
            try:
                render(scene,folder,self.cfg,self.timeout())
                self.check_budget()
                assessment = evaluate(folder,self.cfg,self.timeout())
                atomic_json(marker,{"identity":identity,"checksum":digest(folder/"animation.mp4"),
                    "evaluation_sha256":digest(folder/"evaluation.json"),"motion_sha256":digest(folder/"motion.json")})
                self.database.candidate(number,label,"completed",scene,folder,assessment)
                return folder,assessment
            except BudgetStop:
                raise
            except Exception as error:
                self.database.candidate(number,label,"failed",scene,folder,error=str(error))
                if attempt >= self.cfg["retries"]:
                    raise
                self.database.event("retry",{"round":number,"label":label,"error":str(error),
                    "diagnosis":"Discard incomplete render and recreate deterministic candidate once"})
                self.check_budget()
        raise RuntimeError("Unreachable retry state")

    def select(self, number, defaults):
        cycle = (number-1)%6
        if cycle == 0:
            variable, values = "curve",["cubic","quintic","cosine","linear"]
            hypothesis = "Endpoint derivative continuity reduces encoded centroid jerk at fixed timing."
        elif cycle == 1:
            variable, values = "travel_frames",[36,42,30,24]
            hypothesis = "A longer travel interval reduces discrete jerk while retaining at least 24 hold frames."
        elif cycle == 2:
            variable, values = "stagger_frames",[4,8,2,0]
            hypothesis = "Staggering reduces peak simultaneous pixel change without degrading motion continuity."
        elif cycle == 3:
            variable, values = "overshoot",[0.04,0.08,0.02,0.0]
            hypothesis = "A bounded transient can add follow-through without degrading endpoint continuity."
        elif cycle == 4:
            variable, values = "curve",["cosine","quintic","cubic","linear"]
            hypothesis = "An alternate curve transfers across changing silhouettes and text frames."
        else:
            variable, values = "travel_frames",[30,36,42,24]
            hypothesis = "Shorter or longer motion can balance continuity against readable hold."
        alternatives = [value for value in values if value != defaults[variable]][:self.cfg["candidates"]]
        # Exactly one variable changes for every primary / held-out comparison.
        return variable, alternatives, hypothesis, SCENARIOS[(number-1)%len(SCENARIOS)]

    def regression(self, number, baseline, proposed):
        results = []
        for index, scenario in enumerate(("cards","mask","wave")):
            seed = self.cfg["seed"]+90000+index
            before, a = self.candidate(number,f"regression-{index}-best",scenario,baseline,seed)
            after, b = self.candidate(number,f"regression-{index}-proposed",scenario,proposed,seed)
            ratio = b["objective"]["decoded_centroid_jerk_rms"]/max(a["objective"]["decoded_centroid_jerk_rms"],1e-9)
            results.append({"scenario":scenario,"relative_jerk":ratio,"passed":ratio<=1.10,
                            "baseline":str(before.relative_to(self.root)),"proposed":str(after.relative_to(self.root))})
        return {"round":number,"kind":"fixed technical benchmarks", "passed":all(r["passed"] for r in results),
                "results":results,"subjective_status":"unevaluated", "best_defaults":baseline}

    def run_round(self, files, loaded_checksum):
        number = json.loads(files["VERSION.json"])["round"]+1
        defaults = json.loads(files["techniques/defaults.json"])
        variable, values, hypothesis, scenario = self.select(number,defaults)
        self.database.round_status(number,"running")
        folder = self.root/"rounds"/f"{number:06d}"
        folder.mkdir(parents=True,exist_ok=True)
        # Full infrastructure snapshot and config make every video replayable after source changes.
        source = folder/"source"/"motionlab"
        if not source.exists():
            shutil.copytree(Path(__file__).parent,source,ignore=shutil.ignore_patterns("__pycache__"))
            atomic_json(folder/"source"/"config.json",self.cfg)
        primary_seed = self.cfg["seed"]+number
        baseline_path, baseline = self.candidate(number,"baseline",scenario,defaults,primary_seed)
        candidates = []
        for index,value in enumerate(values):
            params = {**defaults,variable:value}
            path, assessment = self.candidate(number,f"candidate-{index}",scenario,params,primary_seed)
            candidates.append({"label":f"candidate-{index}","value":value,"params":params,
                               "path":str(path.relative_to(self.root)),"evaluation":assessment,
                               "comparison":compare(baseline,assessment,self.cfg["minimum_relative_gain"])})
        winner = min(candidates,key=lambda c:c["evaluation"]["objective"]["decoded_centroid_jerk_rms"])
        chosen = winner["params"]
        transfers = []
        if winner["comparison"]["supported"]:
            # Seeded composition and silhouette holdouts not used to select the winner.
            remaining = [s for s in SCENARIOS if s != scenario]
            import random
            held_out = random.Random(self.cfg["seed"]+number*7919).sample(remaining,2)
            for index,scene in enumerate(held_out):
                seed = self.cfg["seed"]+number*100+index
                a_path, a = self.candidate(number,f"transfer-{index}-baseline",scene,defaults,seed)
                b_path, b = self.candidate(number,f"transfer-{index}-candidate",scene,chosen,seed)
                transfers.append({"scenario":scene,"seed":seed,"baseline":str(a_path.relative_to(self.root)),
                    "candidate":str(b_path.relative_to(self.root)),"comparison":compare(a,b,self.cfg["minimum_relative_gain"]),
                    "baseline_objective":a["objective"],"candidate_objective":b["objective"]})
        supported = winner["comparison"]["supported"] and len(transfers)==2 and all(t["comparison"]["supported"] for t in transfers)
        classification = "validated" if supported else ("experimental" if winner["comparison"]["supported"] else "rejected")
        reason = ("Both rendered-video and trajectory jerk improved on primary and two held-out scenes" if supported else
                  "Primary gain did not transfer to both held-out scenes" if winner["comparison"]["supported"] else
                  "Candidates did not meet the technical gain threshold; aesthetic hypothesis remains unevaluated")
        regression = None
        # Round one establishes fixed baselines; then broader checks at least every ten rounds.
        if number == 1 or number%self.cfg["regression_every"] == 0:
            regression = self.regression(number,defaults,chosen if supported else defaults)
            if not regression["passed"]:
                supported = False
                classification,reason = "rejected","Fixed benchmark regression exceeded 10% degradation; defaults preserved"
        # An optional evaluator must fit inside the remaining invocation budget too.
        visual_cfg = {**self.cfg,"visual_evaluator_timeout_seconds":min(
            self.cfg["visual_evaluator_timeout_seconds"],self.timeout())}
        visual = visual_evaluate([baseline_path]+[self.root/c["path"] for c in candidates],visual_cfg,folder)
        self.check_budget()
        record = {"id":f"round-{number:06d}","round":number,"completed_at":now(),
            "skill_version_loaded":json.loads(files["VERSION.json"])["version"],"loaded_zip_sha256":loaded_checksum,
            "objective":"Improve technical continuity while preserving original composition and timing controls",
            "hypothesis":hypothesis,"scenario":scenario,"seed":primary_seed,"variable":variable,
            "baseline_params":defaults,"chosen_value":winner["value"],"chosen_params":chosen,
            "baseline_path":str(baseline_path.relative_to(self.root)),"baseline_evaluation":baseline,
            "candidates":candidates,"comparison":winner["comparison"],"transfer_validation":transfers,
            "classification":classification,"reason":reason,"visual_evaluation":visual,"regression":regression,
            "finding":(f"For the tested displacement and {defaults['travel_frames']}-frame timing, changing {variable} "
                       f"from {defaults[variable]!r} to {winner['value']!r} reduced decoded centroid and trajectory jerk "
                       "by at least the configured threshold in three original scenes. Apply this technical default "
                       "within the tested parameter family; aesthetics and other timings remain unverified."),
            "weaknesses":baseline["critique"],"source":str((folder/"source").relative_to(self.root)),
            "zip_snapshot":f"archives/motion-design-skill-round-{number:06d}.zip"}
        # Prepared journal survives crashes before ZIP publication. Rerendering is cached on resume.
        atomic_json(folder/"record.json",record)
        self.database.round_status(number,"publishing",record)
        updated, checksum = self.store.finish_round(files,record)
        commit = self.history.snapshot(updated,folder/"source")
        self.database.round_status(number,"completed",record,checksum)
        atomic_json(folder/"zip-receipt.json",{"sha256":checksum,"snapshot":record["zip_snapshot"],"git_commit":commit})
        self.database.event("round_completed",{"round":number,"classification":classification,"zip_sha256":checksum})
        return record

    def run(self, rounds=None):
        rounds = rounds or self.cfg["rounds"]
        lock = open(self.root/"controller.lock","a+")
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise RuntimeError("Another controller owns this output directory")
        previous = {}
        for sig in (signal.SIGTERM,signal.SIGINT):
            previous[sig] = signal.signal(sig,lambda *_:setattr(self,"stopping",True))
        atomic_json(self.root/"controller.json",{"pid":os.getpid(),"status":"running","started_at":now(),
                    "round_limit":rounds,"runtime_limit_seconds":self.cfg["max_runtime_seconds"]})
        result = "completed_budget"
        try:
            files, _ = self.store.load()
            self.database.reconcile(files,self.store)
            # Recover Git history too if interrupted after ZIP publication.
            for archive in sorted(self.store.archives.glob("*.zip")):
                from .skill import verify_bytes
                try:
                    archived = verify_bytes(archive.read_bytes())
                    sidecar = archive.with_suffix(".zip.sha256")
                    if sidecar.read_text().strip() != digest(archive):
                        raise ValueError("History import archive SHA256 mismatch")
                except (ValueError,OSError) as error:
                    self.database.event("history_import_skipped",{"archive":str(archive),"error":str(error)})
                    continue
                number = json.loads(archived["VERSION.json"])["round"]
                self.history.snapshot(archived,self.root/"rounds"/f"{number:06d}"/"source")
            for _ in range(rounds):
                self.check_budget()
                files, checksum = self.store.load()
                # Publication interrupted after archive write: restore latest verified snapshot on load.
                self.database.reconcile(files,self.store)
                self.run_round(files,checksum)
                self.report()
            return result
        except BudgetStop as error:
            result = "stopped"
            if (self.root/"checkpoint.json").exists():
                number = read_json(self.root/"checkpoint.json")["round"]
                if number > json.loads(self.store.load()[0]["VERSION.json"])["round"]:
                    self.database.round_status(number,"interrupted",error=str(error))
            self.database.event("budget_stop",{"reason":str(error)})
            return str(error)
        except BaseException as error:
            result = "failed"
            if (self.root/"checkpoint.json").exists():
                number = read_json(self.root/"checkpoint.json")["round"]
                self.database.round_status(number,"failed",error=str(error))
            self.database.event("controller_error",{"type":type(error).__name__,"error":str(error)})
            raise
        finally:
            atomic_json(self.root/"controller.json",{"pid":os.getpid(),"status":result,"stopped_at":now()})
            self.report()
            for sig,handler in previous.items():
                signal.signal(sig,handler)
            fcntl.flock(lock,fcntl.LOCK_UN)
            lock.close()

    def report(self):
        from .report import write_report
        return write_report(self.root,self.cfg)
