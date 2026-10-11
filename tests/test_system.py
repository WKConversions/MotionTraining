import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from motionlab.controller import Controller, BudgetStop
from motionlab.design import DEFAULTS, easing, plan, states
from motionlab.evaluate import compare, evaluate
from motionlab.render import render
from motionlab.skill import SkillStore, initial_files, verify_bytes
from motionlab.storage import Database
from motionlab.util import load_config, read_json


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = SkillStore(self.root)
        self.files,self.checksum = self.store.load()

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, classification="rejected"):
        return {"round":1,"completed_at":"2026-10-11T00:00:00Z","classification":classification,
                "finding":"A tested technical rule","variable":"curve","chosen_value":"quintic",
                "hypothesis":"Endpoint continuity","reason":"Testing persistence",
                "comparison":{},"visual_evaluation":{"status":"unavailable"},"regression":None}

    def test_every_round_archives_even_failed_hypothesis(self):
        record = self.record()
        updated,sha = self.store.finish_round(self.files,record)
        loaded,sha2 = self.store.load()
        self.assertEqual(sha,sha2)
        self.assertNotEqual(sha,self.checksum)
        self.assertEqual(json.loads(loaded["VERSION.json"])["round"],1)
        self.assertEqual(loaded["techniques/defaults.json"],self.files["techniques/defaults.json"])
        self.assertEqual(loaded["knowledge/discoveries.md"],self.files["knowledge/discoveries.md"])
        self.assertEqual(len(list(self.store.archives.glob("*.zip"))),2)

    def test_validated_rules_loaded_and_current_corruption_recovered(self):
        _,sha = self.store.finish_round(self.files,self.record("validated"))
        self.store.current.write_bytes(b"corrupted")
        files,recovered = self.store.load()
        self.assertEqual(recovered,sha)
        self.assertEqual(json.loads(files["techniques/defaults.json"])["curve"],"quintic")
        self.assertEqual(json.loads(files["VERSION.json"])["version"],"0.1.1")
        self.assertTrue((self.root/"last-recovery.json").exists())

    def test_sqlite_recovers_crash_after_zip_publication(self):
        record = self.record("validated")
        self.store.finish_round(self.files,record)
        db = Database(self.root)
        db.round_status(1,"publishing",record)
        loaded,_ = self.store.load()
        db.reconcile(loaded,self.store)
        self.assertEqual(db.db.execute("SELECT status FROM rounds WHERE round=1").fetchone()[0],"completed")

    def test_invalid_snapshot_does_not_replace_current(self):
        files = dict(self.files)
        del files["SKILL.md"]
        with self.assertRaises(ValueError):
            self.store.publish(files)
        self.assertEqual(self.store.load()[1],self.checksum)

    def test_no_valid_archive_refuses_to_reset_knowledge(self):
        self.store.current.write_bytes(b"bad")
        self.store.archive_path(0).write_bytes(b"bad")
        with self.assertRaises(ValueError):
            self.store.load()

    def test_immutable_archives(self):
        self.store.finish_round(self.files,self.record())
        different = self.record()
        different["reason"] = "tamper"
        with self.assertRaises(ValueError):
            self.store.finish_round(self.files,different)

    def test_resume_archive_written_before_sidecar_and_current(self):
        from motionlab.skill import build_bytes
        updated = dict(self.files)
        record = self.record()
        updated["experiments/experiment-index.json"] = json.dumps([record]).encode()
        version = json.loads(updated["VERSION.json"])
        version["round"] = 1
        updated["VERSION.json"] = json.dumps(version).encode()
        self.store.archive_path(1).write_bytes(build_bytes(updated))
        loaded,_ = self.store.load()
        self.assertEqual(json.loads(loaded["VERSION.json"])["round"],1)
        self.assertTrue(self.store.archive_path(1).with_suffix(".zip.sha256").exists())


class RenderTests(unittest.TestCase):
    def test_actual_mp4_decodes_all_frames_and_subjective_unscored(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config()
            cfg.update(width=640,height=360,output=tmp)
            folder = Path(tmp)/"candidate"
            render(plan("cards",DEFAULTS,12),folder,cfg)
            result = evaluate(folder,cfg)
            self.assertEqual(result["integrity"]["frames"],90)
            self.assertEqual(result["subjective"]["status"],"unevaluated")
            self.assertIsNone(result["subjective"]["weighted_score"])
            self.assertTrue((folder/"contact-sheet.jpg").exists())
            video = folder/"animation.mp4"
            video.write_bytes(video.read_bytes()[:64])
            with self.assertRaises(Exception):
                evaluate(folder,cfg)

    def test_interruption_resumes_and_reuses_completed_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config()
            cfg.update(width=640,height=360,output=tmp,max_runtime_seconds=120)
            controller = Controller(cfg)
            folder,a = controller.candidate(1,"baseline","cards",DEFAULTS,12)
            stamp = (folder/"animation.mp4").stat().st_mtime_ns
            restarted = Controller(cfg)
            with patch("motionlab.controller.render",side_effect=AssertionError("Should reuse render")):
                _,b = restarted.candidate(1,"baseline","cards",DEFAULTS,12)
            self.assertEqual(a,b)
            self.assertEqual(stamp,(folder/"animation.mp4").stat().st_mtime_ns)
            (Path(tmp)/"STOP").touch()
            with self.assertRaises(BudgetStop):
                restarted.candidate(1,"next","cards",DEFAULTS,12)

    def test_failed_render_preserves_skill_and_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config()
            cfg.update(output=tmp,retries=0)
            c = Controller(cfg)
            files,sha = c.store.load()
            with patch("motionlab.controller.render",side_effect=RuntimeError("Injected render failure")):
                with self.assertRaises(RuntimeError):
                    c.candidate(1,"broken","cards",DEFAULTS,12)
            self.assertEqual(c.store.load()[1],sha)
            self.assertEqual(c.database.db.execute("SELECT status FROM candidates").fetchone()[0],"failed")

    def test_interrupted_controller_resumes_round_then_loads_new_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config()
            cfg.update(output=tmp,width=640,height=360,candidates=1,retries=0,max_runtime_seconds=180)
            interrupted = Controller(cfg)
            original = interrupted.candidate
            def break_after_baseline(number,label,*args):
                if label != "baseline":
                    raise BudgetStop("Injected interruption between candidates")
                return original(number,label,*args)
            with patch.object(interrupted,"candidate",side_effect=break_after_baseline):
                self.assertIn("interruption",interrupted.run(1))
            first_sha = interrupted.store.load()[1]
            self.assertEqual(json.loads(interrupted.store.load()[0]["VERSION.json"])["round"],0)
            before = (Path(tmp)/"rounds/000001/baseline/animation.mp4").stat().st_mtime_ns
            resumed = Controller(cfg)
            self.assertEqual(resumed.run(2),"completed_budget")
            files,sha = resumed.store.load()
            records = json.loads(files["experiments/experiment-index.json"])
            self.assertEqual(len(records),2)
            self.assertEqual(records[0]["loaded_zip_sha256"],first_sha)
            from motionlab.util import digest
            self.assertEqual(records[1]["loaded_zip_sha256"],digest(resumed.store.archive_path(1)))
            self.assertEqual(before,(Path(tmp)/"rounds/000001/baseline/animation.mp4").stat().st_mtime_ns)
            self.assertEqual(len(list(resumed.store.archives.glob("*.zip"))),3)


class EvaluationTests(unittest.TestCase):
    def test_proxy_improvement_must_satisfy_both_metrics(self):
        def result(decoded,trajectory,hold=30):
            return {"integrity":{"passed":True},"objective":{"decoded_centroid_jerk_rms":decoded,
                "trajectory_jerk_rms":trajectory,"end_drift_pixels":0,"readable_hold_frames":hold}}
        self.assertFalse(compare(result(1,1),result(0.1,2),0.15)["supported"])
        self.assertFalse(compare(result(1,1),result(0.1,0.1,10),0.15)["supported"])
        self.assertTrue(compare(result(1,1),result(0.1,0.1),0.15)["supported"])

    def test_curves_are_bounded_and_endpoints_exact(self):
        for curve in ("linear","cubic","quintic","cosine"):
            self.assertEqual(easing(0,curve),0)
            self.assertEqual(easing(1,curve),1)
            self.assertTrue(all(0<=easing(i/100,curve)<=1 for i in range(101)))


class SourceControlTests(unittest.TestCase):
    def test_skill_and_code_are_versioned_without_duplicate_resume_commit(self):
        from motionlab.versioning import History
        with tempfile.TemporaryDirectory() as tmp:
            history = History(tmp)
            files = initial_files()
            first = history.snapshot(files)
            self.assertEqual(first,history.snapshot(files))
            self.assertEqual(history.command("rev-list","--count","HEAD").stdout.strip(),"1")
            self.assertIn("Render",history.command("show","HEAD:implementation/motionlab/render.py").stdout)
            self.assertIn("motion-design",history.command("show","HEAD:motion-design-skill/SKILL.md").stdout)


if __name__ == "__main__":
    unittest.main()
