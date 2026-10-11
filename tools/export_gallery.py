"""Export completed experiment videos as a portable GitHub gallery."""
import json
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / 'examples' / 'gallery'
out.mkdir(parents=True, exist_ok=True)
base = 'https://github.com/WKConversions/MotionTraining/blob/main/examples/gallery'
lines = ['# Experiment video gallery', '',
         'Completed baseline and candidate videos. Click a video link; if GitHub does not display a player, choose **View raw** or download the MP4. This is a published snapshot; new local rounds appear after the next export and push.', '']
count = 0
for record in sorted((root / 'runtime' / 'rounds').glob('*/record.json'), reverse=True):
    r = json.loads(record.read_text())
    if r.get('classification') == 'imported':
        continue
    samples = [('Baseline', r['baseline_path'])] + [(c['label'], c['path']) for c in r['candidates'] if c.get('evaluation') is not None]
    links = []
    for label, relative in samples:
        source = root / 'runtime' / relative / 'animation.mp4'
        if not source.is_file():
            continue
        name = f"round-{r['round']:06d}-{Path(relative).name}.mp4"
        shutil.copyfile(source, out / name)
        links.append(f'[{label}]({base}/{name}) · [Download]({base.replace("/blob/", "/raw/")}/{name})')
        count += 1
    if links:
        lines += [f"## Round {r['round']} · {r.get('research_domain', 'motion')} · {r['classification']}", '', ' | '.join(links), '']
(out / 'README.md').write_text('\n'.join(lines))
print(f'Exported {count} videos to {out}')
