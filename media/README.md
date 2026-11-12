Put your adhan and Quran audio files here.

Anything the profile's `events:` block names goes in this directory, e.g.
`fajr.mp3`, `dua.mp3`. MP3, M4A, WAV, OGG and FLAC all work; MP3 is the safest
choice for network speakers. `muezzin init` creates this directory for you.

This directory is served over HTTP (port 8010 by default) so that Cast devices
and `muezzin box` machines fetch the files themselves instead of receiving an
upload through the daemon.

## The two test tones

`test-tone.wav` (one second, 440 Hz) and `test-chime.wav` (three rising notes,
each with a short fade) are checked in on purpose. They are sine waves written out
by this project, not recordings: no voice, no recitation, nothing that could be
somebody else's work. They exist so the first thing a new install does is make a
sound — the README's "play this through the speaker and listen" step needs a file
that a fresh clone actually has.

Delete them if you like; anything equivalent works. This reproduces
`test-tone.wav` sample for sample, with nothing installed:

```python
import math, wave

with wave.open("media/test-tone.wav", "wb") as f:
    f.setnchannels(1)
    f.setsampwidth(2)
    f.setframerate(44100)
    f.writeframes(b"".join(
        int(12000 * math.sin(2 * math.pi * 440 * n / 44100)).to_bytes(2, "little", True)
        for n in range(44100)
    ))
```

