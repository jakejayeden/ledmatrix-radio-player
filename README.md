# LEDMatrix Radio Player

Third-party internet-radio plugin for ChuckBuilds/LEDMatrix, initially developed for LEDMatrix 3.8.x and a 128x32 RGB matrix.

## Features

- Self-contained Python audio backend using `miniaudio`; no separate `mpv`, VLC or mpg123 installation.
- `miniaudio` is declared in `requirements.txt`, so LEDMatrix installs it with the plugin's Python dependencies.
- Plays direct internet-radio streams and reconnects after playback errors.
- Displays station name plus ICY `StreamTitle` metadata when supplied by the station.
- Compact layout for 128x32 while using the actual display dimensions.
- Stops audio cleanly when the plugin unloads or configuration changes.

## Installation

Install this repository through LEDMatrix's third-party **install from URL** feature:

```text
https://github.com/jakejayeden/ledmatrix-radio-player
```

There is no separate audio-player package to install. The plugin dependency is:

```text
miniaudio>=1.61
```

The test Pi is Debian 13 / LEDMatrix 3.8.7. Its C-Media USB Audio Device is currently ALSA card 0 and the system default output, so the first build lets miniaudio use the default output rather than relying on a numeric card index.

## Station page vs stream URL

A web-player page such as the Radio UK Heart 80s page is not necessarily the audio stream. The current build expects a direct internet-radio stream in `stream_url`. Heart 80s stream resolution and programme/show metadata are the next station-specific pieces to add.

## Display

On a 128x32 matrix the intended layout is approximately:

```text
          HEART 80s
     A-ha - Take On Me
```

Long metadata is currently shortened to fit. Smooth scrolling is planned.

## Metadata

The plugin requests standard ICY metadata (`Icy-MetaData: 1`) in a background thread. If the station supplies `icy-metaint` and `StreamTitle`, the title is displayed. If it does not, playback status is shown until a station-specific metadata provider is available.

## Troubleshooting

If the display says **Set stream URL**, configure a direct stream rather than the station's web page. Playback errors are exposed through the plugin's `get_info()` data and LEDMatrix logs.

For audio debugging on the test Pi, the useful ALSA commands remain:

```bash
aplay -l
aplay -L
```

## Roadmap

- Heart 80s / Global Player stream discovery.
- Programme/show metadata provider.
- Explicit miniaudio output-device selection when required.
- Software volume control.
- Smooth horizontal scrolling for long show/track names.
- Station presets and fallback streams.
- Tests against the LEDMatrix plugin safety harness.

## License

GPL-3.0. This plugin is designed to run with the GPL-3.0 LEDMatrix project.
