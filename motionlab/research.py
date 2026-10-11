"""Declared hypotheses and evidence gates across the senior skill's capabilities."""
DOMAINS = [
    ("sound_effects","sfx_offset_frames",[0,2],"Align synthesized impact peaks with the picture event", "audio_sync"),
    ("visuals","palette",["sky","coral"],"Compare color hierarchy and clarity against the bright baseline", "subjective"),
    ("materials","material",["paper","glass"],"Test restrained material cues without reducing text clarity", "subjective"),
    ("smoothness","curve",["quintic","septic","sine-quintic","move"],"Test smoother endpoint behavior under the original motion identity", "motion"),
    ("originality","visual_strategy",["connected_route","constellation","fold"],"Connect the thread to its objects; compare meaning and structural diversity", "subjective"),
    ("music","music_vibe",["cinematic-warm","calm-optimistic","playful"],"Compare original composed music against the visual thesis", "subjective"),
    ("voice_over","voice_rate",[155,195,175],"Compare draft speaking pace while preserving the complete script", "subjective"),
    ("timing","travel_frames",[18,30,36,24],"Balance arrival timing, motion continuity and readability", "motion"),
    ("transitions","transition",["grow","ribbon"],"Make a transformation emerge from the thread object", "subjective"),
    ("typography","font_scale",[1.15,1.25,1.0],"Test type hierarchy and readable size without viewport overflow", "subjective"),
    ("libraries","library_backend",["supersampled","pillow"],"Compare raster pipelines for edge stability and render cost", "subjective"),
    ("sound_picture_timing","sfx_offset_frames",[0,-2,2],"Test audio transients on the exact visual landing frame", "audio_sync"),
    ("audio_mix","duck_db",[10,14,6],"Test music ducking beneath the voice without masking effects", "subjective"),
]


def select(number,profile,defaults,limit):
    index=(number-profile["import_round"]-1)%len(DOMAINS)
    domain,variable,values,hypothesis,gate=DOMAINS[index]
    options=[v for v in values if v!=defaults.get(variable)][:limit]
    scenario=("cards","orbit","morph","type","wave","mask")[index%6]
    return {"domain":domain,"variable":variable,"values":options,"hypothesis":hypothesis,"gate":gate,"scenario":scenario}


def compare_audio(base,candidate,threshold):
    a=base["audio"]["worst_stem_sync_error_frames"]
    b=candidate["audio"]["worst_stem_sync_error_frames"]
    gain=(a-b)/max(a,1e-9)
    return {"supported":gain>=threshold and b<=1 and candidate["audio"]["integrity_passed"],
            "relative_gains":{"audio_sync":gain},"scope":"Measured synthesized-effect timing, not auditory taste"}


def experimental_comparison(base,candidate):
    return {"supported":False,"relative_gains":{},"scope":"Subjective design/audio hypothesis requires capable independent assessment",
            "objective_integrity_passed":candidate["integrity"]["passed"],"status":"experimental"}
