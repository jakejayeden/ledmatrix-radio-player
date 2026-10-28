# LEDMatrix Radio Player

Third-party internet-radio plugin for [ChuckBuilds/LEDMatrix](https://github.com/ChuckBuilds/LEDMatrix), initially developed for LEDMatrix 3.8.x and a 128x32 RGB matrix.

## Features

- Plays direct HTTP/HTTPS MP3, AAC and HLS radio streams through `mpv`.
- Configurable ALSA output device and volume.
- Defaults to the test Pi's C-Media USB adapter: `alsa/plughw:CARD=Device,DEV=0`.
- Displays station name plus ICY `StreamTitle` metadata when the stream supplies it.
- Compact layout intended for 128x32, while using the live display dimensions.
- Restarts playback if `mpv` exits.
- Stops the player when the plugin unloads.

## Important: station page vs stream URL

A web-player page such as `https://www.radio-uk.co.uk/heart-80s` is not necessarily the audio stream. Version 0.1.0 expects a **direct stream URL** in `stream_url`. Resolving station web pages is planned separately so that fragile/private player URLs are not hard-coded into the plugin.

## Pi prerequisite

`mpv` is not installed on the initial test Pi. Install it with:

```bash
sudo apt update
sudo apt install -y mpv
```

Confirm the USB device is visible:

```bash
aplay -l
aplay -L
```

For the test hardware, ALSA reports the playback adapter as `Device`, therefore the plugin default is:

```text
alsa/plughw:CARD=Device,DEV=0
```

Using the ALSA card name is more robust than relying on it always being numeric card 0.

## Install into LEDMatrix

The LEDMatrix third-party plugin API accepts a GitHub repository URL. From the Pi, with LEDMatrix's web service running, it can be installed through the Plugin Store's install-from-URL feature using:

```text
https://github.com/jakejayeden/ledmatrix-radio-player
```

Then open the plugin settings, enable it, enter a direct radio `stream_url`, select volume/audio device, and save.

## First audio test

Before blaming the plugin for an audio problem, test a known direct stream with mpv itself:

```bash
mpv --no-video --audio-device='alsa/plughw:CARD=Device,DEV=0' 'DIRECT_STREAM_URL'
```

If that plays through the speakers, the plugin uses the same playback path.

## Display

On a 128x32 matrix the intended layout is approximately:

```text
          HEART 80s
     A-ha - Take On Me
```

0.1.0 truncates unusually long metadata to keep it inside the panel. Smooth scrolling and programme/show metadata are planned follow-ups.

## Metadata

The plugin requests standard ICY metadata (`Icy-MetaData: 1`) independently from mpv. If the station sends an `icy-metaint` header and `StreamTitle`, the title appears on the second line. Stations that do not expose ICY metadata simply show playback status until another metadata provider is added.

## Troubleshooting

If the display says **mpv missing**, install the Debian `mpv` package. If it says **Set stream URL**, configure a direct stream URL rather than a station webpage. If mpv runs but no sound is heard, verify the configured `audio_device` against `aplay -L` and test that exact device with mpv from the shell.

## Roadmap

- Heart 80s / Global Player stream discovery or documented direct-stream configuration.
- Programme/show metadata provider.
- Smooth horizontal scrolling for long show/track names.
- Play/stop controls exposed through the LEDMatrix web UI where supported.
- Optional station presets and fallback streams.
- Tests against the LEDMatrix plugin safety harness.

## License

GPL-3.0. This plugin is designed to run with the GPL-3.0 LEDMatrix project.
