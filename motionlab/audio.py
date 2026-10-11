"""Original audio from the supplied library, plus explicitly labelled local draft speech."""
import ast
import ctypes
import json
import subprocess
import sys
import types
import wave
from pathlib import Path

import numpy as np

from .util import atomic_json, digest

SR=48000


def write_wave(path,samples):
    with wave.open(str(path),'wb') as f:
        f.setnchannels(2); f.setsampwidth(2); f.setframerate(SR)
        f.writeframes((np.clip(samples,-0.999,0.999)*32767).astype('<i2').tobytes())


def decode(path,timeout=60):
    raw=subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-ac','2','-ar',str(SR),
        '-f','f32le','pipe:1'],check=True,capture_output=True,timeout=timeout).stdout
    return np.frombuffer(raw,dtype='<f4').reshape(-1,2).astype(float)


def voice(text,rate,pitch):
    import espeakng_loader
    lib=espeakng_loader.load_library()
    if lib is None:
        raise RuntimeError('Local draft speech library unavailable')
    lib.espeak_Initialize.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_char_p,ctypes.c_int]
    lib.espeak_Initialize.restype=ctypes.c_int
    sample_rate=lib.espeak_Initialize(2,0,espeakng_loader.get_data_path().encode(),0)
    if sample_rate<=0:
        raise RuntimeError('Local speech initialization failed')
    chunks=[]
    callback_type=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.POINTER(ctypes.c_short),ctypes.c_int,ctypes.c_void_p)
    def receive(pointer,count,events):
        if pointer and count:
            chunks.append(ctypes.string_at(pointer,count*2))
        return 0
    callback=callback_type(receive)
    lib.espeak_SetSynthCallback(callback)
    lib.espeak_SetVoiceByName.argtypes=[ctypes.c_char_p]
    if lib.espeak_SetVoiceByName(b'en-us'):
        raise RuntimeError('Requested draft voice unavailable')
    lib.espeak_SetParameter(1,int(rate),0)
    lib.espeak_SetParameter(3,int(pitch),0)
    encoded=text.encode()+b'\0'
    lib.espeak_Synth.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint,ctypes.c_int,
        ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p,ctypes.c_void_p]
    buf=ctypes.create_string_buffer(encoded)
    if lib.espeak_Synth(buf,len(encoded),0,1,0,1,None,None):
        raise RuntimeError('Speech synthesis failed')
    lib.espeak_Synchronize()
    samples=np.frombuffer(b''.join(chunks),dtype='<i2').astype(float)/32768
    if len(samples)==0:
        raise ValueError('Speech synthesis produced no samples')
    return np.interp(np.arange(int(len(samples)*SR/sample_rate))*sample_rate/SR,
                     np.arange(len(samples)),samples)


def effect_module(path):
    # The supplied script has an unconditional main() that rewrites its whole sound
    # catalogue. Load reviewed function definitions while retaining original bytes.
    tree=ast.parse(Path(path).read_text(),filename=str(path))
    tree.body=[node for node in tree.body if not (isinstance(node,ast.Expr) and
        isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='main')]
    module=types.ModuleType('supplied_sfx')
    exec(compile(tree,str(path),'exec'),module.__dict__)
    return module


def normalized(samples,rms):
    return samples*(rms/max(float(np.sqrt(np.mean(samples*samples))),1e-9))


def make_audio(scene,folder,cfg,timeout=60):
    folder=Path(folder)
    p=scene['params']
    n=SR*3
    source=folder/'audio-source'
    source.mkdir(exist_ok=True)
    library=Path(cfg['skill_library'])/'scripts'
    for name in ['music_make.py','sfx_synth.py']:
        destination=source/name
        if not destination.exists():
            destination.write_bytes((library/name).read_bytes())
    brief={'bpm':p.get('music_bpm',120),'length':3.0,'key':['D','F','A'][scene['seed']%3],
        'mode':'major','vibe':p.get('music_vibe','tech-minimal'),'progression':['I','V','vi','IV'],
        'sections':[[0,1],[1,'end']]}
    atomic_json(folder/'music-brief.json',brief)
    subprocess.run([sys.executable,str(source/'music_make.py'),str(folder/'music-brief.json'),str(folder/'music.wav')],
        check=True,capture_output=True,timeout=timeout)
    music=decode(folder/'music.wav',timeout)
    music=np.pad(music[:n],((0,max(0,n-len(music))),(0,0)))
    music=normalized(music,0.027)
    spoken=voice('Find the clear path.',p.get('voice_rate',175),p.get('voice_pitch',50))
    if len(spoken)>int(2.8*SR):
        raise ValueError('Full spoken phrase does not fit; refusing to truncate voice-over')
    vo=np.zeros((n,2))
    onset=int(0.12*SR)
    vo[onset:onset+len(spoken)]=normalized(spoken[:,None]*np.ones((1,2)),0.14)
    write_wave(folder/'voice.wav',vo)
    # Duck music only where a smoothed local voice envelope is present.
    env=np.sqrt(np.mean(vo.reshape(300,480,2)**2,axis=(1,2)))
    duck=np.repeat(np.clip(env/0.05,0,1),480)
    duck=np.convolve(duck,np.ones(2400)/2400,mode='same')
    music*=10**(-p.get('duck_db',6)*duck[:,None]/20)
    music*=np.minimum(np.arange(n)/(0.1*SR),1)[:,None]
    music*=np.minimum(np.arange(n)[::-1]/(0.3*SR),1)[:,None]
    write_wave(folder/'music-bed.wav',music)
    synth=effect_module(source/'sfx_synth.py')
    # Original library impact with short internal-draft parameters; no borrowed samples.
    hit=synth.stereo(synth.impact,length=0.22,f0=110,f1=42,click=0.25)
    hit=normalized(hit,0.035)
    sync=int(np.argmax(np.max(np.abs(hit),axis=1)))
    fx=np.zeros((n,2))
    cues=[]
    # Only the dominant hero landing gets an impact, as the supplied sound grammar requires.
    event_frame=scene['objects'][1]['end']
    start=int((event_frame+p.get('sfx_offset_frames',5))/30*SR)-sync
    a,b=max(0,start),min(n,start+len(hit))
    fx[a:b]+=hit[a-start:b-start]
    write_wave(folder/'effects.wav',fx)
    actual_peak=int(np.argmax(np.max(np.abs(fx),axis=1)))
    cues.append({'visual_event_frame':event_frame,'target_sample':round(event_frame/30*SR),
        'effect_peak_sample':actual_peak,'sync_error_frames':abs(actual_peak/SR*30-event_frame),
        'source':'Supplied library/scripts/sfx_synth.py: impact, generated waveform'})
    mix=vo+music+fx
    if np.max(np.abs(mix))>0.82:
        mix*=0.82/np.max(np.abs(mix))
    write_wave(folder/'mix.wav',mix)
    result={'sample_rate':SR,'samples':n,'channels':2,'script':'Find the clear path.',
        'voice_source':'espeak-ng local synthetic draft; not professional voice quality',
        'voice_complete':True,'word_alignment':'not checked; synthesis onset is not forced word alignment',
        'music_source':'User-supplied library/scripts/music_make.py; original composition',
        'sfx_source':'User-supplied library/scripts/sfx_synth.py; original synthesis',
        'cues':cues,'worst_stem_sync_error_frames':max(c['sync_error_frames'] for c in cues),
        'library_sources':{name:digest(source/name) for name in ['music_make.py','sfx_synth.py']},
        'auditory_quality':'unevaluated','mix_sha256':digest(folder/'mix.wav')}
    atomic_json(folder/'audio-plan.json',result)
    return result


def evaluate_audio(folder,timeout=60):
    folder=Path(folder)
    metadata=json.loads((folder/'audio-plan.json').read_text())
    decoded=decode(folder/'animation.mp4',timeout)
    # AAC introduces encoder delay; FFmpeg can decode padding after the declared end.
    if len(decoded)<SR*3 or len(decoded)>SR*3+2048:
        raise ValueError('Encoded audio duration/samples failed')
    decoded=decoded[:SR*3]
    peak=float(np.max(np.abs(decoded)))
    rms=float(np.sqrt(np.mean(decoded**2)))
    if not 0<rms or peak>=0.99 or not np.isfinite(decoded).all():
        raise ValueError('Audio missing, invalid or clipping')
    stems=decode(folder/'effects.wav',timeout)
    measured_peak=int(np.argmax(np.max(np.abs(stems),axis=1)))
    expected=metadata['cues'][0]['visual_event_frame']
    error=abs(measured_peak/SR*30-expected)
    result={**metadata,'integrity_passed':True,'decoded_samples':len(decoded),'decoded_peak_dbfs':float(20*np.log10(peak)),
        'decoded_rms_dbfs':float(20*np.log10(rms)),'worst_stem_sync_error_frames':error,
        'evidence_scope':'Full mixed track decoded from actual MP4; precise transient location measured in decoded effect stem',
        'limitations':['Music taste, voice intelligibility and timbre are unevaluated',
                      'Stem timing does not prove every transient is perceptually audible in the encoded mix',
                      'LUFS normalization and forced word alignment have not been checked']}
    atomic_json(folder/'audio-evaluation.json',result)
    return result
