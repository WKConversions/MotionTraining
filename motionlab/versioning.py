"""Local source control for learning artifacts without staging user checkout changes."""
import json
import shutil
import subprocess
from pathlib import Path

from .util import atomic_bytes, atomic_json


class History:
    def __init__(self, root):
        self.root = Path(root)
        self.git = self.root/"history.git"
        self.work = self.root/"history-content"
        self.work.mkdir(parents=True,exist_ok=True)
        if not self.git.exists():
            subprocess.run(["git","init","--bare","--quiet",str(self.git)],check=True,capture_output=True)

    def command(self, *args, check=True):
        return subprocess.run(["git",f"--git-dir={self.git.resolve()}",f"--work-tree={self.work.resolve()}",
            "-c","user.name=Motion Training Controller","-c","user.email=motiontraining@localhost",
            *args],check=check,capture_output=True,text=True)

    def snapshot(self, files, source=None):
        number = json.loads(files["VERSION.json"])["round"]
        tag = f"round-{number:06d}"
        existing = self.command("rev-parse","--verify",f"refs/tags/{tag}",check=False)
        if existing.returncode == 0:
            return existing.stdout.strip()
        skill = self.work/"motion-design-skill"
        # This work tree is exclusively generated history; preserve original user checkout.
        if skill.exists():
            shutil.rmtree(skill)
        for name,body in files.items():
            atomic_bytes(skill/name,body)
        implementation = self.work/"implementation"
        if implementation.exists():
            shutil.rmtree(implementation)
        if source and Path(source).exists():
            shutil.copytree(source,implementation,ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copytree(Path(__file__).parent,implementation/"motionlab",ignore=shutil.ignore_patterns("__pycache__"))
        self.command("add","--all")
        self.command("commit","--quiet","--allow-empty","-m",f"Skill and original implementation after round {number}")
        self.command("tag",tag)
        commit = self.command("rev-parse","HEAD").stdout.strip()
        atomic_json(self.root/"source-control-receipt.json",{"round":number,"tag":tag,"commit":commit,
                                                              "repository":str(self.git)})
        return commit
