"""Internet radio player plugin for LEDMatrix."""

import threading

import miniaudio

from src.plugin_system.base_plugin import BasePlugin


HEART_80S_STREAM = "https://media-ssl.musicradio.com/Heart80sMP3"


class RadioPlayerPlugin(BasePlugin):
    """Play an internet-radio stream and display ICY metadata."""

    STATION_FONT = ("press_start", 8)
    META_FONT = ("press_start", 6)

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
        self._load_config(config)
        self._register_fonts()

    def _load_config(self, config):
        self.station_name = str(config.get("station_name", "Heart 80s"))
        configured_url = str(config.get("stream_url", "")).strip()
        self.stream_url = configured_url or HEART_80S_STREAM
        self.autoplay = bool(config.get("autoplay", True))
        self.volume = max(0, min(100, int(config.get("volume", 70))))
        self.metadata_enabled = bool(config.get("metadata_enabled", True))
        self.station_color = tuple(config.get("station_color", [255, 80, 80]))
        self.metadata_color = tuple(config.get("metadata_color", [255, 255, 255]))

    def _register_fonts(self):
        fm = getattr(self.plugin_manager, "font_manager", None)
        if fm is None:
            return
        try:
            fm.register_manager_font(self.plugin_id, f"{self.plugin_id}.station", self.STATION_FONT[0], self.STATION_FONT[1], self.station_color)
            fm.register_manager_font(self.plugin_id, f"{self.plugin_id}.meta", self.META_FONT[0], self.META_FONT[1], self.metadata_color)
        except Exception as exc:
            self.logger.warning("Could not register radio fonts: %s", exc)

    def _font(self, key, spec):
        fm = getattr(self.plugin_manager, "font_manager", None)
        if fm is None:
            return None
        try:
            return fm.resolve_font(f"{self.plugin_id}.{key}", spec[0], spec[1], plugin_id=self.plugin_id)
        except Exception:
            return None

    def _title_changed(self, _client, title):
        if not self.metadata_enabled:
            return
        title = (title or "").strip()
        if title and title != self.now_playing:
            self.now_playing = title
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
                # PlaybackDevice.start() expects an already-primed generator.
                # This is required by both older and current pyminiaudio releases.
                next(stream)
                device = miniaudio.PlaybackDevice(
                    output_format=miniaudio.SampleFormat.SIGNED16,
                    nchannels=2,
                    sample_rate=44100,
                    app_name="LEDMatrix Radio",
                )
                # set_master_volume() was added to newer pyminiaudio versions.
                # Do not make playback depend on it: older installations should
                # still play at the system/device volume rather than fail.
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

    @staticmethod
    def _ellipsize(text, limit):
        if len(text) <= limit:
            return text
        return text[:max(1, limit - 3)] + "..."

    def display(self, force_clear=False):
        if force_clear:
            self.display_manager.clear()
        width, height = self.display_manager.width, self.display_manager.height
        station_font = self._font("station", self.STATION_FONT)
        meta_font = self._font("meta", self.META_FONT)
        chars = max(8, width // 5)
        station = self._ellipsize(self.station_name, chars)
        detail = self._ellipsize(self.now_playing or self.status, chars + 4)
        self.display_manager.draw_text(station, x=width // 2, y=max(1, height // 4), color=self.station_color, font=station_font, centered=True)
        self.display_manager.draw_text(detail, x=width // 2, y=max(12, (height * 2) // 3), color=self.metadata_color, font=meta_font, centered=True)
        self.display_manager.update_display()

    def on_config_change(self, new_config):
        old_stream = self.stream_url
        old_volume = self.volume
        super().on_config_change(new_config)
        self._load_config(self.config)
        self._register_fonts()
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
        self._stop_player()
        super().cleanup()
