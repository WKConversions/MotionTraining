import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .controller import Controller
from .util import atomic_bytes, load_config


def main():
    parser = argparse.ArgumentParser(description="Original autonomous motion experiments; bounded and resumable")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[1]/"config.json"))
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run","start","resume"):
        command = commands.add_parser(name)
        command.add_argument("--rounds",type=int,help="Additional rounds; defaults to configured round budget")
    for name in ("stop","status","report","verify","recover"):
        commands.add_parser(name)
    args = parser.parse_args()
    cfg = load_config(args.config)
    root = Path(cfg["output"])
    root.mkdir(parents=True,exist_ok=True)
    if args.command in ("run","resume","start"):
        if args.rounds is not None and args.rounds < 1:
            parser.error("--rounds must be positive")
        if args.command == "start":
            cmd = [sys.executable,"-m","motionlab","--config",str(Path(args.config).resolve()),"resume"]
            if args.rounds:
                cmd += ["--rounds",str(args.rounds)]
            with open(root/"controller.log","ab") as log:
                process = subprocess.Popen(cmd,stdout=log,stderr=log,start_new_session=True,cwd=Path(__file__).resolve().parents[1])
            print(json.dumps({"launched_pid":process.pid,"log":str(root/"controller.log"),
                "note":"Launch is not readiness; inspect status. Process requires this machine to remain running."}))
            return
        (root/"STOP").unlink(missing_ok=True)
        print(Controller(cfg).run(args.rounds))
    elif args.command == "stop":
        atomic_bytes(root/"STOP",b"Graceful stop at the next safe checkpoint\n")
        print("Stop requested; the active render may finish before checkpoint exit.")
    elif args.command in ("verify","recover"):
        from .skill import SkillStore, verify_bytes
        from .util import digest
        store = SkillStore(root)
        if args.command == "recover":
            files,checksum = store.load()
        else:
            files = verify_bytes(store.current.read_bytes())
            checksum = digest(store.current)
            if store.current.with_suffix(".zip.sha256").read_text().strip()!=checksum:
                raise ValueError("Current ZIP SHA256 mismatch")
        print(json.dumps({"verified":True,"checksum":checksum,"version":json.loads(files["VERSION.json"])}))
    else:
        from .report import write_report
        from .storage import Database
        Database(root)
        summary = write_report(root,cfg)
        # A process can die abruptly leaving stale persisted running state. Never infer liveness from PID alone.
        import fcntl
        with open(root/"controller.lock","a+") as lock:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                summary["process_active"] = False
                fcntl.flock(lock,fcntl.LOCK_UN)
            except BlockingIOError:
                summary["process_active"] = True
        print(json.dumps(summary,indent=2))


if __name__ == "__main__":
    main()
