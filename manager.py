"""Internet radio player plugin for LEDMatrix."""

import threading
import time

import miniaudio
from PIL import Image, ImageDraw, ImageFont

from src.plugin_system.base_plugin import BasePlugin


HEART_80S_STREAM = "https://media-ssl.musicradio.com/Heart80sMP3"


class RadioPlayerPlugin(BasePlugin):
    """Play an internet-radio stream and display ICY metadata."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self._lock = threading.RLock()
        self._audio_thread = None
        self._audio_stop = threading.Event()
        self._device = None
        self._radio = None
        self.now_playing = ""
        self.status = "Stopped"
        self.last_error = ""
        self._scroll_started = time.monotonic()
        self.enable_scrolling = True
        # Match the Apple Calendar plugin: Pillow's built-in default font,
        # rendered directly onto an RGB image rather than LEDMatrix TTF/BDF fonts.
        self.font = ImageFont.load_default()
        self._load_config(config)

    def _load_config(self, config):
        self.station_name = str(config.get("station_name", "Heart 80s"))
        configured_url = str(config.get("stream_url", "")).strip()
        self.stream_url = configured_url or HEART_80S_STREAM
        self.autoplay = bool(config.get("autoplay", True))
        self.volume = max(0, min(100, int(config.get("volume", 70))))
        self.metadata_enabled = bool(config.get("metadata_enabled", True))
        self.scroll_speed = max(5.0, min(100.0, float(config.get("scroll_speed", 30))))
        self.station_color = tuple(config.get("station_color", [255, 80, 80]))
        self.metadata_color = tuple(config.get("metadata_color", [255, 255, 255]))

    def _title_changed(self, _client, title):
        if not self.metadata_enabled:
            return
        title = (title or "").strip()
        if title and title != self.now_playing:
            self.now_playing = title
            self._scroll_started = time.monotonic()
            self.logger.info("Now playing: %s", title)

    def _audio_worker(self):
        """Decode and play the station using the pip-installed miniaudio library."""
        while not self._audio_stop.is_set():
            radio = None
            device = None
            try:
                self.status = "Connecting"
                self.last_error = ""
                radio = miniaudio.IceCastClient(
                    self.stream_url,
                    update_stream_title=self._title_changed if self.metadata_enabled else None,
                )
                stream = miniaudio.stream_any(
                    radio,
                    output_format=miniaudio.SampleFormat.SIGNED16,
                    nchannels=2,
                    sample_rate=44100,
                )
                next(stream)
                device = miniaudio.PlaybackDevice(
                    output_format=miniaudio.SampleFormat.SIGNED16,
                    nchannels=2,
                    sample_rate=44100,
                    app_name="LEDMatrix Radio",
                )
                set_volume = getattr(device, "set_master_volume", None)
                if callable(set_volume):
                    set_volume(self.volume / 100.0)
                device.start(stream)
                with self._lock:
                    self._radio = radio
                    self._device = device
                self.status = "Playing"
                self.logger.info(
                    "Radio playback started (miniaudio %s, backend=%s)",
                    getattr(miniaudio, "__version__", "unknown"),
                    getattr(device, "backend", "unknown"),
                )
                while not self._audio_stop.wait(0.5):
                    pass
                break
            except Exception as exc:
                self.status = "Playback error"
                self.last_error = str(exc)
                self.logger.error("Radio playback error: %s", exc)
                if self._audio_stop.wait(5):
                    break
            finally:
                with self._lock:
                    if self._device is device:
                        self._device = None
                    if self._radio is radio:
                        self._radio = None
                if device is not None:
                    try:
                        device.close()
                    except Exception:
                        pass
                if radio is not None:
                    try:
                        radio.close()
                    except Exception:
                        pass
        if self._audio_stop.is_set():
            self.status = "Stopped"

    def _start_player(self):
        if self._audio_thread and self._audio_thread.is_alive():
            return
        self._audio_stop.clear()
        self._audio_thread = threading.Thread(target=self._audio_worker, name="ledmatrix-radio-audio", daemon=True)
        self._audio_thread.start()

    def _stop_player(self):
        self._audio_stop.set()
        with self._lock:
            device = self._device
            radio = self._radio
        if device is not None:
            try:
                device.close()
            except Exception:
                pass
        if radio is not None:
            try:
                radio.close()
            except Exception:
                pass
        thread = self._audio_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._audio_thread = None
        self.status = "Stopped"

    def update(self):
        if self.autoplay:
            if self._audio_thread is None or not self._audio_thread.is_alive():
                self._start_player()
        elif self._audio_thread and self._audio_thread.is_alive():
            self._stop_player()

    def _text_width(self, draw, text):
        bbox = draw.textbbox((0, 0), text, font=self.font)
        return bbox[2] - bbox[0]

    def _draw_centered(self, draw, text, y, width, fill):
        text_width = self._text_width(draw, text)
        draw.text(((width - text_width) // 2, y), text, font=self.font, fill=fill)

    def _draw_metadata(self, draw, text, width, y):
        """Draw short metadata centered; smoothly marquee long metadata."""
        text_width = self._text_width(draw, text)
        if text_width <= width - 4:
            self._draw_centered(draw, text, y, width, self.metadata_color)
            return

        gap = 24
        travel = width + text_width + gap
        elapsed = max(0.0, time.monotonic() - self._scroll_started)
        x = width - int((elapsed * self.scroll_speed) % travel)
        draw.text((x, y), text, font=self.font, fill=self.metadata_color)

    def display(self, force_clear=False):
        # Render the complete 128x32-style frame in Pillow, matching Apple Calendar.
        width, height = self.display_manager.width, self.display_manager.height
        image = Image.new("RGB", (width, height), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        detail = self.now_playing or self.status

        set_scrolling = getattr(self.display_manager, "set_scrolling_state", None)
        if callable(set_scrolling):
            set_scrolling(True)

        # Two compact rows for a 32px-high panel. Pillow's default font keeps
        # the typography identical to the Apple Calendar rendering path.
        self._draw_centered(draw, self.station_name, 5, width, self.station_color)
        self._draw_metadata(draw, detail, width, 18)

        self.display_manager.image = image
        self.display_manager.update_display()

    def on_config_change(self, new_config):
        old_stream = self.stream_url
        old_volume = self.volume
        super().on_config_change(new_config)
        self._load_config(self.config)
        self._scroll_started = time.monotonic()
        if (old_stream, old_volume) != (self.stream_url, self.volume):
            self._stop_player()
            self.now_playing = ""
        if self.autoplay:
            self._start_player()

    def validate_config(self):
        if not super().validate_config():
            return False
        if not 0 <= self.volume <= 100:
            self.logger.error("volume must be between 0 and 100")
            return False
        if self.stream_url and not self.stream_url.startswith(("http://", "https://")):
            self.logger.error("stream_url must be an HTTP(S) URL")
            return False
        return True

    def get_info(self):
        info = super().get_info()
        info.update({"station": self.station_name, "stream_url": self.stream_url, "now_playing": self.now_playing, "playback_status": self.status, "last_error": self.last_error, "audio_backend": "miniaudio"})
        return info

    def cleanup(self):
        set_scrolling = getattr(self.display_manager, "set_scrolling_state", None)
        if callable(set_scrolling):
            set_scrolling(False)
        self._stop_player()
        super().cleanup()
