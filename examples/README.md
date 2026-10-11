[Open the full experiment video gallery](gallery/README.md)

# Actual initial experiment outputs

## Senior skill baseline

`senior-baseline.mp4` and `senior-improved.mp4` are the first controlled experiment
after adopting the supplied senior-motion-designer skill. Both contain original
music composed by its music_make.py, generated impacts from its sfx_synth.py and
an explicitly synthetic local eSpeak draft voice. The improved variant places
the effect stem's peak on the dominant object's arrival rather than five frames late.
That technical timing change passed two held-out scene tests. Perceptual audibility,
music taste and voice intelligibility remain unverified. `senior-preview.jpg` contains
frames decoded from the MP4. The original skill's 105 member files remain unchanged.

The files below are earlier bootstrap studies, preserved for history.

`baseline.mp4` uses linear easing; `arrival.mp4` uses quintic easing. All other primary
experiment settings are identical: 24 travel frames, no stagger or overshoot, seed
20261012, original orbit scene, 1920×1080, 30 FPS, 90 frames / three seconds.
`arrival.jpg` contains nine frames decoded from the candidate MP4.

In this experiment, decoded centroid jerk RMS decreased by 54.9% and exact trajectory
jerk RMS by 89.3%. The technical improvement passed transfer checks on cards and morph
scenes and fixed cards/mask/wave regressions. These metrics establish a limited technical
continuity finding; they do not prove greater artistic quality. No independent subjective
scores were assigned.

The static ZIP under `skills/` is the fully verified snapshot after round three, version
0.1.1. It includes one scoped validated technical finding and two rejected experiments.
Current runtime records and later ZIP archives remain in `runtime/`, outside the Git
checkout's tracked artifacts. The controller separately maintains local Git history for
every round's skill and implementation under `runtime/history.git`.
