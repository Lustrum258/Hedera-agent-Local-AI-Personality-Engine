"""
MIDI -> WAV renderer (FluidSynth-based)
Uses pyfluidsynth for synthesis, mido for MIDI parsing.
Replaces the previous custom voice-based renderer.
"""
import wave
import threading
import mido
import fluidsynth

_render_progress = {}
_progress_lock = threading.Lock()

OUTPUT_SR = 44100
CHUNK_FRAMES = 4096  # frames per processing chunk (FluidSynth works in frames, not samples)


def set_render_progress(render_id, phase, pct, detail=""):
    with _progress_lock:
        _render_progress[render_id] = {"phase": phase, "pct": pct, "detail": detail}


def get_render_progress(render_id):
    with _progress_lock:
        return _render_progress.get(render_id, {"phase": "unknown", "pct": 0})


def clear_render_progress(render_id):
    with _progress_lock:
        _render_progress.pop(render_id, None)


def _build_event_list(midi_path):
    """Parse MIDI file with mido, return sorted list of (abs_time_sec, type, data) and total duration."""
    mid = mido.MidiFile(midi_path)
    ticks_per_beat = mid.ticks_per_beat
    events = []
    tempo = 500000  # default 120 BPM

    for track in mid.tracks:
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == 'set_tempo':
                tempo = msg.tempo
                events.append((abs_tick, 'tempo', {'tempo': tempo}))
            elif msg.type == 'note_on':
                if msg.velocity > 0:
                    time_sec = mido.tick2second(abs_tick, ticks_per_beat, tempo)
                    events.append((abs_tick, 'note_on', {
                        'channel': msg.channel,
                        'note': msg.note,
                        'velocity': msg.velocity,
                        'time': time_sec,
                    }))
                else:
                    time_sec = mido.tick2second(abs_tick, ticks_per_beat, tempo)
                    events.append((abs_tick, 'note_off', {
                        'channel': msg.channel,
                        'note': msg.note,
                        'time': time_sec,
                    }))
            elif msg.type == 'note_off':
                time_sec = mido.tick2second(abs_tick, ticks_per_beat, tempo)
                events.append((abs_tick, 'note_off', {
                    'channel': msg.channel,
                    'note': msg.note,
                    'time': time_sec,
                }))
            elif msg.type == 'program_change':
                time_sec = mido.tick2second(abs_tick, ticks_per_beat, tempo)
                events.append((abs_tick, 'program_change', {
                    'channel': msg.channel,
                    'program': msg.program,
                    'time': time_sec,
                }))
            elif msg.type == 'control_change':
                time_sec = mido.tick2second(abs_tick, ticks_per_beat, tempo)
                events.append((abs_tick, 'cc', {
                    'channel': msg.channel,
                    'cc': msg.control,
                    'value': msg.value,
                    'time': time_sec,
                }))
            elif msg.type == 'pitchwheel':
                time_sec = mido.tick2second(abs_tick, ticks_per_beat, tempo)
                events.append((abs_tick, 'pitchwheel', {
                    'channel': msg.channel,
                    'value': msg.pitch,
                    'time': time_sec,
                }))

    # Sort by absolute tick, then by event type priority (tempo first)
    events.sort(key=lambda e: (e[0], 0 if e[1] == 'tempo' else 1))

    # Recalculate time_sec after sorting (tempo changes affect subsequent events)
    tempo = 500000
    last_tempo_tick = 0
    for i, (tick, etype, data) in enumerate(events):
        if etype == 'tempo':
            tempo = data['tempo']
            last_tempo_tick = tick
        else:
            data['time'] = mido.tick2second(tick, ticks_per_beat, tempo)

    # Get duration
    duration = mid.length
    return events, duration, ticks_per_beat


def render_midi_to_wav(midi_path, sf2_path, output_path=None, render_id=None):
    """Render MIDI file to WAV using FluidSynth."""
    if output_path is None:
        output_path = midi_path.rsplit('.', 1)[0] + '.wav'

    if render_id:
        set_render_progress(render_id, "parsing", 5)

    # Parse MIDI
    events, duration, tpb = _build_event_list(midi_path)

    if render_id:
        set_render_progress(render_id, "loading", 10)

    # Create FluidSynth (settings must be passed at init)
    fs = fluidsynth.Synth(samplerate=OUTPUT_SR, gain=0.4)
    sfid = fs.sfload(sf2_path)

    # reverb: 适度，不要糊
    fs.set_reverb(0.4, 0.3, 0.5, 0.5)
    fs.set_chorus(0, 0, 0.3, 8.0, 0)  # nr=0 disables chorus

    # Program defaults: channel 9 = drums (bank 128), others = bank 0
    for ch in range(16):
        if ch == 9:
            fs.program_select(ch, sfid, 128, 0)
        else:
            fs.program_select(ch, sfid, 0, 0)

    if render_id:
        set_render_progress(render_id, "rendering", 15)

    # Sort audio events (skip tempo markers)
    audio_events = [(e[2]['time'], e[1], e[2]) for e in events if e[1] != 'tempo']
    audio_events.sort(key=lambda x: x[0])

    total_frames = int(duration * OUTPUT_SR) + OUTPUT_SR * 2  # +2s padding
    total_chunks = (total_frames + CHUNK_FRAMES - 1) // CHUNK_FRAMES

    # Open WAV writer
    wav_file = wave.open(output_path, 'wb')
    wav_file.setnchannels(2)
    wav_file.setsampwidth(2)  # 16-bit
    wav_file.setframerate(OUTPUT_SR)

    event_idx = 0
    total_events = len(audio_events)
    frames_written = 0

    for ci in range(total_chunks):
        if render_id and ci % 50 == 0 and ci > 0:
            pct = 15 + int(80 * ci / total_chunks)
            set_render_progress(render_id, "rendering", pct, f"{ci}/{total_chunks}")

        chunk_start_time = frames_written / OUTPUT_SR
        chunk_end_time = (frames_written + CHUNK_FRAMES) / OUTPUT_SR

        # Process all events in this time window
        while event_idx < total_events and audio_events[event_idx][0] < chunk_end_time:
            _, etype, data = audio_events[event_idx]
            event_idx += 1
            ch = data['channel']

            if etype == 'note_on':
                fs.noteon(ch, data['note'], data['velocity'])
            elif etype == 'note_off':
                fs.noteoff(ch, data['note'])
            elif etype == 'program_change':
                fs.program_change(ch, data['program'])
            elif etype == 'cc':
                fs.cc(ch, data['cc'], data['value'])
            elif etype == 'pitchwheel':
                fs.pitch_bend(ch, data['value'] + 8192)  # mido uses -8192..8163, fluidsynth uses 0..16383

        # Render audio chunk
        audio_data = fs.get_samples(CHUNK_FRAMES)
        # fluidsynth returns interleaved stereo int16 as a bytes-like object
        wav_file.writeframes(audio_data)
        frames_written += CHUNK_FRAMES

    wav_file.close()
    fs.delete()

    if render_id:
        set_render_progress(render_id, "done", 100, output_path)

    return output_path
