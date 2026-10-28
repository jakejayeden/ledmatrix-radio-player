"""Internet radio player plugin for LEDMatrix."""

import shutil
import subprocess
import threading
import time
import urllib.request

from src.plugin_system.base_plugin import BasePlugin


class RadioPlayerPlugin(BasePlugin):
    """Play a direct internet-radio stream and display its metadata."""

    STATION_FONT = ("press_start", 8)
    META_FONT = ("press_start", 6)

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self._lock = threading.RLock()
        self._player = None
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
        self.volume = int(config.get("volume", 70))
        self.audio_device = str(config.get("audio_device", "alsa/plughw:CARD=Device,DEV=0")).strip()
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

    def _mpv_command(self):
        cmd = [
            "mpv", "--no-video", "--really-quiet", "--no-terminal",
            "--audio-client-name=LEDMatrix Radio", f"--volume={self.volume}",
            "--cache=yes", "--cache-secs=10", "--demuxer-readahead-secs=10",
        ]
        if self.audio_device:
            cmd.append(f"--audio-device={self.audio_device}")
        cmd.append(self.stream_url)
        return cmd

    def _start_player(self):
        with self._lock:
            if self._player and self._player.poll() is None:
                return
            if not self.stream_url:
                self.status = "Set stream URL"
                return
            if shutil.which("mpv") is None:
                self.status = "mpv missing"
                self.last_error = "Install mpv: sudo apt install mpv"
                return
            try:
                self._player = subprocess.Popen(
                    self._mpv_command(), stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                self.status = "Playing"
                self.last_error = ""
                self._ensure_metadata_thread()
            except Exception as exc:
                self.status = "Playback error"
                self.last_error = str(exc)
                self.logger.error("Unable to start radio: %s", exc)

    def _stop_player(self):
        with self._lock:
            player, self._player = self._player, None
        if player and player.poll() is None:
            try:
                player.terminate()
                player.wait(timeout=3)
            except Exception:
                try:
                    player.kill()
                except Exception:
                    pass
        self.status = "Stopped"

    def _ensure_metadata_thread(self):
        if not self.metadata_enabled or not self.stream_url:
            return
        if self._metadata_thread and self._metadata_thread.is_alive():
            return
        self._metadata_stop.clear()
        self._metadata_thread = threading.Thread(target=self._metadata_worker, name="ledmatrix-radio-metadata", daemon=True)
        self._metadata_thread.start()

    def _metadata_worker(self):
        """Read ICY metadata without putting network I/O on the render thread."""
        while not self._metadata_stop.is_set():
            try:
                request = urllib.request.Request(self.stream_url, headers={"Icy-MetaData": "1", "User-Agent": "LEDMatrix-Radio/0.1"})
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
                        metadata = response.read(length_byte[0] * 16).rstrip(b"\0").decode("utf-8", "replace")
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
            if self._player is None or self._player.poll() is not None:
                self._start_player()
        elif self._player and self._player.poll() is None:
            self._stop_player()

    @staticmethod
    def _ellipsize(text, limit):
        if len(text) <= limit:
            return text
        return text[: max(1, limit - 3)] + "..."

    def display(self, force_clear=False):
        if force_clear:
            self.display_manager.clear()
        width, height = self.display_manager.width, self.display_manager.height
        station_font = self._font("station", self.STATION_FONT)
        meta_font = self._font("meta", self.META_FONT)
        chars = max(8, width // 5)
        station = self._ellipsize(self.station_name, chars)
        detail = self.now_playing or self.status
        detail = self._ellipsize(detail, chars + 4)
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
        info.update({"station": self.station_name, "now_playing": self.now_playing, "playback_status": self.status, "last_error": self.last_error})
        return info

    def cleanup(self):
        self._metadata_stop.set()
        self._stop_player()
        thread = self._metadata_thread
        if thread and thread.is_alive():
            thread.join(timeout=1)
        super().cleanup()
