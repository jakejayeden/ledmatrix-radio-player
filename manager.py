"""Internet radio player plugin for LEDMatrix."""

import threading
import time
import urllib.request

import miniaudio

from src.plugin_system.base_plugin import BasePlugin


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
        self._stream = None
        self._metadata_thread = None
        self._metadata_stop = threading.Event()
        self.now_playing = ""
        self.status = "Stopped"
        self.last_error = ""
        self._load_config(config)
        self._register_fonts()

    def _load_config(self, config):
        self.station_name = str(config.get("station_name", "Heart 80s"))
        self.stream_url = str(config.get("stream_url", "")).strip()
        self.autoplay = bool(config.get("autoplay", True))
        self.volume = max(0, min(100, int(config.get("volume", 70))))
        self.audio_device = str(config.get("audio_device", "")).strip()
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

    def _audio_worker(self):
        """Decode and play the station using the pip-installed miniaudio library."""
        while not self._audio_stop.is_set():
            try:
                self.status = "Connecting"
                self.last_error = ""
                radio = miniaudio.IceCastClient(self.stream_url)
                stream = miniaudio.stream_any(radio, sample_format=miniaudio.SampleFormat.SIGNED16)
                device = miniaudio.PlaybackDevice(
                    output_format=miniaudio.SampleFormat.SIGNED16,
                    nchannels=radio.nchannels,
                    sample_rate=radio.sample_rate,
                )
                device.start(stream)
                with self._lock:
                    self._stream = stream
                    self._device = device
                self.status = "Playing"
                while not self._audio_stop.wait(0.5):
                    # Playback runs in miniaudio's callback thread. Keep this
                    # worker alive so a stop/config change can close it cleanly.
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
                    device, self._device = self._device, None
                    self._stream = None
                if device is not None:
                    try:
                        device.close()
                    except Exception:
                        pass
        if self._audio_stop.is_set():
            self.status = "Stopped"

    def _start_player(self):
        if not self.stream_url:
            self.status = "Set stream URL"
            return
        if self._audio_thread and self._audio_thread.is_alive():
            return
        self._audio_stop.clear()
        self._audio_thread = threading.Thread(
            target=self._audio_worker,
            name="ledmatrix-radio-audio",
            daemon=True,
        )
        self._audio_thread.start()
        self._ensure_metadata_thread()

    def _stop_player(self):
        self._audio_stop.set()
        with self._lock:
            device = self._device
        if device is not None:
            try:
                device.close()
            except Exception:
                pass
        thread = self._audio_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._audio_thread = None
        self.status = "Stopped"

    def _ensure_metadata_thread(self):
        if not self.metadata_enabled or not self.stream_url:
            return
        if self._metadata_thread and self._metadata_thread.is_alive():
            return
        self._metadata_stop.clear()
        self._metadata_thread = threading.Thread(
            target=self._metadata_worker,
            name="ledmatrix-radio-metadata",
            daemon=True,
        )
        self._metadata_thread.start()

    def _metadata_worker(self):
        """Read ICY StreamTitle without network I/O on the display thread."""
        while not self._metadata_stop.is_set():
            try:
                request = urllib.request.Request(
                    self.stream_url,
                    headers={"Icy-MetaData": "1", "User-Agent": "LEDMatrix-Radio/0.2"},
                )
                with urllib.request.urlopen(request, timeout=15) as response:
                    metaint = response.headers.get("icy-metaint")
                    if not metaint:
                        return
                    interval = int(metaint)
                    while not self._metadata_stop.is_set():
                        audio = response.read(interval)
                        if len(audio) < interval:
                            break
                        length_byte = response.read(1)
                        if not length_byte:
                            break
                        raw = response.read(length_byte[0] * 16)
                        metadata = raw.rstrip(b"\0").decode("utf-8", "replace")
                        marker = "StreamTitle='"
                        if marker in metadata:
                            title = metadata.split(marker, 1)[1].split("';", 1)[0].strip()
                            if title:
                                self.now_playing = title
            except Exception as exc:
                self.logger.debug("ICY metadata unavailable: %s", exc)
            self._metadata_stop.wait(15)

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
        old_device = self.audio_device
        old_volume = self.volume
        super().on_config_change(new_config)
        self._load_config(self.config)
        self._register_fonts()
        if (old_stream, old_device, old_volume) != (self.stream_url, self.audio_device, self.volume):
            self._metadata_stop.set()
            self._stop_player()
            self.now_playing = ""
            self._metadata_thread = None
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
        info.update({
            "station": self.station_name,
            "now_playing": self.now_playing,
            "playback_status": self.status,
            "last_error": self.last_error,
            "audio_backend": "miniaudio",
        })
        return info

    def cleanup(self):
        self._metadata_stop.set()
        self._stop_player()
        thread = self._metadata_thread
        if thread and thread.is_alive():
            thread.join(timeout=1)
        super().cleanup()
