# Actual initial experiment outputs

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
