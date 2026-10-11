from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from .design import frame_image, plan
from .util import atomic_json, digest


def render(scene, folder, cfg, timeout=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / "render.partial.mp4"
    video = folder / "animation.mp4"
    atomic_json(folder / "scene.json", scene)
    # A runnable source accompanies every render, referencing a preserved renderer snapshot.
    (folder / "source.py").write_text(
        'import json\nfrom pathlib import Path\nfrom motionlab.render import render\n'
        'from motionlab.util import load_config\n'
        'scene = json.loads(Path(__file__).with_name("scene.json").read_text())\n'
        'render(scene, Path(__file__).parent / "replay", load_config())\n')
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-threads", str(cfg["threads"]),
           "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f'{cfg["width"]}x{cfg["height"]}',
           "-framerate", str(cfg["fps"]), "-i", "pipe:0", "-an", "-c:v", "libx264",
           "-threads", str(cfg["threads"]), "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", str(tmp)]
    rows = []
    # A watchdog kills a stuck encoder even while a pipe write is blocked.
    import threading
    with open(folder / "render.log", "wb") as log:
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
        timer = threading.Timer(timeout or cfg["render_timeout_seconds"], process.kill)
        timer.start()
        try:
            for frame in range(cfg["fps"] * cfg["duration"]):
                if scene['params'].get('library_backend')=='supersampled':
                    from PIL import Image
                    im, metadata=frame_image(scene,frame,{**cfg,'width':cfg['width']*2,'height':cfg['height']*2})
                    im=im.resize((cfg['width'],cfg['height']),Image.Resampling.LANCZOS)
                    for key in ['text_bounds','shape_bounds']:
                        metadata[key]=[[v/2 for v in bounds] for bounds in metadata[key]]
                else:
                    im, metadata = frame_image(scene, frame, cfg)
                process.stdin.write(im.tobytes())
                rows.append(metadata)
            process.stdin.close()
            code = process.wait()
            if code:
                raise RuntimeError(f"Render failed ({code}); see {folder / 'render.log'}")
        except BaseException:
            process.kill()
            process.wait()
            tmp.unlink(missing_ok=True)
            raise
        finally:
            timer.cancel()
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
    os.replace(tmp, video)
    if scene.get('profile')=='senior':
        from .audio import make_audio
        make_audio(scene,folder,cfg,timeout or cfg['render_timeout_seconds'])
        mux=folder/'audio-mux.partial.mp4'
        subprocess.run(['ffmpeg','-y','-v','error','-i',str(video),'-i',str(folder/'mix.wav'),
            '-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-ar','48000',
            '-af','loudnorm=I=-15:TP=-1.5:LRA=7,aresample=48000','-t','3','-movflags','+faststart',str(mux)],
            check=True,timeout=timeout or cfg['render_timeout_seconds'])
        os.replace(mux,video)
    atomic_json(folder / "motion.json", rows)
    atomic_json(folder / "render.json", {"video_sha256": digest(video), "scene": scene,
                                       "width": cfg["width"], "height": cfg["height"], "fps": cfg["fps"]})
    return video
