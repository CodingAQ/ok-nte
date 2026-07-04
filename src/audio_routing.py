import atexit
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ok import ConfigOption, og
from ok.gui.Communicate import communicate
from ok.util.logger import Logger

from src import GAME_EXE

logger = Logger.get_logger(__name__)

SOUND_VOLUME_VIEW_URL = "https://www.nirsoft.net/utils/sound_volume_view.html"
CONFIG_NAME = "Background Audio Routing"
CONF_ENABLE = "Enable Background Audio Routing"
CONF_SOUND_VOLUME_VIEW_PATH = "SoundVolumeView Path"
CONF_BACKGROUND_DEVICE = "Background Output Device"
CONF_OPEN_DOWNLOAD_PAGE = "Open SoundVolumeView Download Page"
DEFAULT_RENDER_DEVICE = "DefaultRenderDevice"
DEFAULT_DEVICE_OPTIONS = [DEFAULT_RENDER_DEVICE]
_COMMAND_TIMEOUT_SECONDS = 5
_WINDOW_ROUTE_CHECK_INTERVAL_SECONDS = 2
_IGNORED_SOUNDDEVICE_HOST_APIS = {"MME", "Windows WDM-KS"}
_SOUND_ITEM_COLUMNS = (
    "Name,Command-Line Friendly ID,Item ID,Type,Direction,Device Name,Device,"
    "Default Device,Default Render Device,Output Device,Device State,Process ID,Window Title"
)
_APP_DEVICE_COLUMNS = (
    "Device Name",
    "Device",
    "Default Device",
    "Default Render Device",
    "Output Device",
)
_COMMAND_ID_KEY = "Command-Line Friendly ID"
_RESET_PATCH_ATTR = "_background_audio_routing_reset_patched"


def create_background_audio_routing_config_option() -> ConfigOption:
    device_options = _initial_device_options()
    connect_background_audio_router()
    return ConfigOption(
        CONFIG_NAME,
        {
            CONF_ENABLE: False,
            CONF_SOUND_VOLUME_VIEW_PATH: "",
            CONF_BACKGROUND_DEVICE: device_options[0],
            CONF_OPEN_DOWNLOAD_PAGE: CONF_OPEN_DOWNLOAD_PAGE,
        },
        description=(
            "Optionally route the game to a selected Windows output device while it is in "
            "the background. SoundVolumeView is not bundled; select your own downloaded copy."
        ),
        config_description={
            CONF_ENABLE: "Switch game audio output when the game window leaves the foreground",
            CONF_SOUND_VOLUME_VIEW_PATH: "Select SoundVolumeView.exe downloaded from NirSoft",
            CONF_BACKGROUND_DEVICE: "Output device used while the game is in the background",
            CONF_OPEN_DOWNLOAD_PAGE: "Open the official NirSoft SoundVolumeView page",
        },
        config_type={
            CONF_SOUND_VOLUME_VIEW_PATH: {
                "type": "file_selector",
                "filter": (
                    "SoundVolumeView.exe (SoundVolumeView.exe);;"
                    "Executable Files (*.exe);;All Files (*)"
                ),
                "dialog_title": "Select SoundVolumeView.exe",
            },
            CONF_BACKGROUND_DEVICE: {
                "type": "drop_down",
                "options": device_options,
            },
            CONF_OPEN_DOWNLOAD_PAGE: {
                "type": "button",
                "text": "Open Download Page",
                "callback": open_sound_volume_view_download_page,
            },
        },
        validator=_background_audio_routing_validator(device_options),
    )


def open_sound_volume_view_download_page(*_args, **_kwargs) -> None:
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(SOUND_VOLUME_VIEW_URL))
    except Exception as exc:
        logger.error("failed to open SoundVolumeView download page", exc)
        _alert_error("Failed to open SoundVolumeView download page")


def discover_output_devices() -> list[str]:
    import sounddevice as sd

    devices = list(DEFAULT_DEVICE_OPTIONS)
    seen = {DEFAULT_RENDER_DEVICE.casefold()}
    try:
        sound_devices = list(sd.query_devices())
        ignored_hostapi_indexes = _ignored_hostapi_indexes(sd.query_hostapis())
        _extend_output_devices(devices, seen, sound_devices, ignored_hostapi_indexes)

        if len(devices) == 1:
            _extend_output_devices(devices, seen, sound_devices)
    except Exception as exc:
        logger.error(f"failed to query output devices using sounddevice: {exc}")
    return devices


def _ignored_hostapi_indexes(hostapis: Any) -> set[int]:
    return {
        i for i, api in enumerate(hostapis) if api.get("name") in _IGNORED_SOUNDDEVICE_HOST_APIS
    }


def _extend_output_devices(
    devices: list[str],
    seen: set[str],
    sound_devices: list[Any],
    ignored_hostapi_indexes: set[int] | None = None,
) -> None:
    for device in sound_devices:
        if not _is_output_sound_device(device, ignored_hostapi_indexes):
            continue
        _append_unique_device(devices, seen, device["name"])


def _is_output_sound_device(device: Any, ignored_hostapi_indexes: set[int] | None) -> bool:
    if device["max_output_channels"] <= 0:
        return False
    return ignored_hostapi_indexes is None or device["hostapi"] not in ignored_hostapi_indexes


def _append_unique_device(devices: list[str], seen: set[str], name: str) -> None:
    key = name.casefold()
    if key in seen:
        return
    seen.add(key)
    devices.append(name)


def discover_app_output_device(exe_path: str, process_name: str = GAME_EXE) -> str:
    return parse_app_output_device(
        _export_sound_items(exe_path),
        process_name=process_name,
    )


def parse_app_output_device(data: Any, process_name: str = GAME_EXE) -> str:
    device_aliases = _device_aliases(data)
    for record in _iter_records(data):
        if not _is_app_record(record, process_name):
            continue
        device_id = _app_output_device_id(record, device_aliases)
        if device_id:
            return device_id
    return DEFAULT_RENDER_DEVICE


def _is_app_record(record: dict[str, Any], process_name: str) -> bool:
    item_type = _first_text(record, "Type").casefold()
    if item_type and item_type != "application":
        return False
    app_names = (
        _first_text(record, "Name"),
        _first_text(record, _COMMAND_ID_KEY),
        _first_text(record, "Item ID"),
    )
    return any(_is_process_name(value, process_name) for value in app_names)


def _app_output_device_id(record: dict[str, Any], device_aliases: dict[str, str]) -> str:
    for key in _APP_DEVICE_COLUMNS:
        candidate = _first_text(record, key)
        if not candidate:
            continue
        if _is_sound_volume_view_device_id(candidate):
            return candidate
        device_id = device_aliases.get(_device_match_key(candidate))
        if device_id:
            return device_id
    return ""


def audio_route_command(device: str, process_name: str = GAME_EXE) -> list[str]:
    return ["/SetAppDefault", device, "all", process_name]


def connect_background_audio_router() -> None:
    _router.connect_window_signal()


def restore_background_audio_router() -> None:
    _router.restore_on_exit()


def route_background_audio_for_current_window() -> None:
    _router.route_current_window_state()


@dataclass(frozen=True)
class _RouteRequest:
    device: str
    capture_original: bool
    restore_original: bool = False


class _BackgroundAudioRouter:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending_route: _RouteRequest | None = None
        self._requested_device: str | None = None
        self._original_device: str | None = None
        self._restore_exe_path: str | None = None
        self._restore_needed = False
        self._worker: threading.Thread | None = None
        self._connected = False
        self._bound_exit_event = None
        self._last_visible: bool | None = None
        self.last_mute_check = 0

    def on_window(self, visible: bool, *_args) -> None:
        now = time.time()
        visible_changed = visible != self._last_visible
        recently_checked = now - self.last_mute_check <= _WINDOW_ROUTE_CHECK_INTERVAL_SECONDS
        if not visible_changed and recently_checked:
            return
        self._last_visible = visible
        self.last_mute_check = now
        self.request_route(visible)

    def connect_window_signal(self) -> None:
        self._bind_exit_event()
        with self._lock:
            if self._connected:
                return
            communicate.window.connect(self.on_window)
            self._connected = True

    def request_route(self, visible: bool) -> None:
        self._request_route(visible)

    def route_current_window_state(self) -> None:
        self._bind_exit_event()
        visible = self._current_window_visible()
        if visible is not None:
            self._request_route(visible, enabled=True)

    def _request_route(self, visible: bool, enabled: bool | None = None) -> None:
        self._bind_exit_event()
        config = _routing_config()
        if config is None or not (config.get(CONF_ENABLE, False) if enabled is None else enabled):
            return
        exe_path = config.get(CONF_SOUND_VOLUME_VIEW_PATH, "")
        if not _is_sound_volume_view_path(exe_path):
            logger.warning(
                "background audio routing skipped: SoundVolumeView.exe is not configured"
            )
            return

        device = self._route_device(visible, config)
        if device is None:
            return
        if not device:
            logger.warning("background audio routing skipped: target output device is empty")
            return

        route = _RouteRequest(
            device=device,
            capture_original=not visible,
            restore_original=visible,
        )
        with self._lock:
            worker_running = self._worker is not None and self._worker.is_alive()
            restore_in_flight = (
                route.restore_original
                and (self._pending_route is not None or worker_running or self._restore_needed)
            )
            if route == self._pending_route or (
                device == self._requested_device and not restore_in_flight
            ):
                return
            self._pending_route = route
            self._restore_exe_path = exe_path
            if worker_running:
                return
            self._worker = threading.Thread(
                target=self._run_pending_routes,
                args=(exe_path,),
                name="background_audio_router",
                daemon=True,
            )
            self._worker.start()

    def _bind_exit_event(self) -> None:
        exit_event = _ok_exit_event()
        if exit_event is None:
            return
        with self._lock:
            if self._bound_exit_event is exit_event:
                return
            exit_event.bind_stop(self)
            self._bound_exit_event = exit_event

    def stop(self) -> None:
        self.restore_on_exit()

    def _current_window_visible(self) -> bool | None:
        with self._lock:
            if self._last_visible is not None:
                return self._last_visible
        hwnd_window = getattr(getattr(og, "device_manager", None), "hwnd_window", None)
        visible = getattr(hwnd_window, "visible", None)
        return visible if isinstance(visible, bool) else None

    def _run_pending_routes(self, exe_path: str) -> None:
        while True:
            with self._lock:
                route = self._pending_route
                self._pending_route = None
                if route is None:
                    self._worker = None
                    return
            if route.capture_original:
                self._ensure_original_device(exe_path)
            device = self._route_request_device(route)
            if not device:
                continue
            routed = self._apply_route(exe_path, device)
            if routed:
                with self._lock:
                    self._requested_device = device
                    original_device = self._original_device or DEFAULT_RENDER_DEVICE
                    self._restore_needed = device != original_device

    def _ensure_original_device(self, exe_path: str) -> None:
        with self._lock:
            if self._original_device is not None:
                return
        try:
            original_device = discover_app_output_device(exe_path)
        except Exception as exc:
            logger.warning(f"failed to capture original game audio output device: {exc}")
            original_device = DEFAULT_RENDER_DEVICE
        with self._lock:
            if self._original_device is None:
                self._original_device = original_device

    def _route_device(self, visible: bool, config) -> str | None:
        if not visible:
            return config.get(CONF_BACKGROUND_DEVICE)
        with self._lock:
            if self._original_device is not None:
                return self._original_device
            worker_running = self._worker is not None and self._worker.is_alive()
            if self._pending_route is not None or worker_running or self._restore_needed:
                return DEFAULT_RENDER_DEVICE
            return None

    def _route_request_device(self, route: _RouteRequest) -> str:
        if not route.restore_original:
            return route.device
        with self._lock:
            if self._original_device is not None:
                return self._original_device
            if self._restore_needed or self._requested_device is not None:
                return route.device
        return ""

    def _apply_route(self, exe_path: str, device: str) -> bool:
        route_device = _resolve_sound_volume_view_device(exe_path, device)
        if not route_device:
            return False
        command = [exe_path, *audio_route_command(route_device)]
        logger.info(
            f"route game audio output: tool={Path(exe_path).name} "
            f"device={route_device} process={GAME_EXE}"
        )
        try:
            result = subprocess.run(  # NOSONAR
                command,
                capture_output=True,
                text=True,
                timeout=_COMMAND_TIMEOUT_SECONDS,
                check=False,
                shell=False,
            )
        except Exception as exc:
            logger.error("failed to route game audio with SoundVolumeView", exc)
            return False
        if result.returncode != 0:
            logger.warning(f"SoundVolumeView audio route failed with exit code {result.returncode}")
            return False
        return True

    def restore_on_exit(self) -> None:
        with self._lock:
            worker = self._worker
            self._pending_route = None
        if worker is not None and worker is not threading.current_thread() and worker.is_alive():
            worker.join(timeout=_COMMAND_TIMEOUT_SECONDS + 0.5)

        with self._lock:
            exe_path = self._restore_exe_path or _configured_sound_volume_view_path()
            restore_needed = self._restore_needed
            restore_device = self._original_device or DEFAULT_RENDER_DEVICE
        if not restore_needed or not _is_sound_volume_view_path(exe_path):
            return
        logger.info(f"restore game audio output on exit: device={restore_device}")
        if self._apply_route(exe_path, restore_device):
            with self._lock:
                self._requested_device = restore_device
                self._restore_needed = False


def _routing_config():
    global_config = getattr(og, "global_config", None)
    if global_config is None:
        return None
    try:
        config = global_config.get_config(CONFIG_NAME)
    except Exception as exc:
        logger.debug(f"background audio routing config unavailable: {exc}")
        return None
    _patch_reset_to_restore_audio(config)
    return config


def _patch_reset_to_restore_audio(config) -> None:
    if getattr(config, _RESET_PATCH_ATTR, False):
        return
    reset_to_default = getattr(config, "reset_to_default", None)
    if reset_to_default is None:
        return

    def reset_to_default_with_audio_restore(*args, **kwargs):
        was_enabled = bool(config.get(CONF_ENABLE, False))
        reset_to_default(*args, **kwargs)
        if was_enabled and not bool(config.get(CONF_ENABLE, False)):
            restore_background_audio_router()

    config.reset_to_default = reset_to_default_with_audio_restore
    setattr(config, _RESET_PATCH_ATTR, True)


def _ok_exit_event():
    exit_event = getattr(og, "exit_event", None)
    if exit_event is not None:
        return exit_event
    ok_instance = getattr(og, "ok", None)
    return getattr(ok_instance, "exit_event", None)


def _configured_sound_volume_view_path() -> str:
    config = _routing_config()
    if not config:
        return ""
    value = config.get(CONF_SOUND_VOLUME_VIEW_PATH, "")
    return value if isinstance(value, str) else ""


def _initial_device_options() -> list[str]:
    return discover_output_devices()


def _background_audio_routing_validator(device_options: list[str]):
    def validator(key, value):
        if key == CONF_ENABLE:
            if value:
                route_background_audio_for_current_window()
            else:
                restore_background_audio_router()
        if key == CONF_BACKGROUND_DEVICE and value not in device_options:
            return False, "Selected background output device is unavailable"
        if key == CONF_SOUND_VOLUME_VIEW_PATH:
            if value and not _is_sound_volume_view_path(value):
                return False, "Please select SoundVolumeView.exe"
        return True, None

    return validator


def _is_sound_volume_view_path(exe_path: str) -> bool:
    if not exe_path:
        return False
    path = Path(exe_path)
    return path.is_file() and path.name.lower() == "soundvolumeview.exe"  # NOSONAR


def _export_sound_items(exe_path: str):
    if not exe_path:
        raise RuntimeError("Please select SoundVolumeView.exe first")
    if not _is_sound_volume_view_path(exe_path):
        raise RuntimeError("Please select a valid SoundVolumeView.exe file")

    fd, export_path = tempfile.mkstemp(prefix="nte_sound_devices_", suffix=".json")
    os.close(fd)
    try:
        command = [
            exe_path,
            "/SaveFileEncoding",
            "3",
            "/sjson",
            export_path,
            "/Columns",
            _SOUND_ITEM_COLUMNS,
        ]
        result = subprocess.run(  # NOSONAR
            command,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"SoundVolumeView failed to export devices, exit code {result.returncode}"
            )
        return _read_json(export_path)
    finally:
        try:
            os.remove(export_path)
        except OSError:
            pass


def _resolve_sound_volume_view_device(exe_path: str, device: str) -> str | None:
    if device == DEFAULT_RENDER_DEVICE or _is_sound_volume_view_device_id(device):
        return device
    try:
        device_id = _resolve_sound_volume_view_device_id(_export_sound_items(exe_path), device)
    except Exception as exc:
        logger.warning(f"failed to resolve output device for SoundVolumeView: {exc}")
        return None
    if not device_id:
        logger.warning(f"failed to resolve output device for SoundVolumeView: {device}")
        return None
    return device_id


def _resolve_sound_volume_view_device_id(data: Any, device: str) -> str:
    return _device_aliases(data).get(_device_match_key(device), "")


def _read_json(path: str):
    with open(path, "r", encoding="utf-8-sig") as file:
        return json.load(file)


def _iter_records(data: Any):
    if isinstance(data, list):
        yield from (item for item in data if isinstance(item, dict))
    elif isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                yield from (item for item in value if isinstance(item, dict))


def _is_render_endpoint(record: dict[str, Any], device_id: str) -> bool:
    record_text = " ".join(str(value) for value in record.values()).lower()
    device_id_lower = device_id.lower()
    if not _is_sound_volume_view_device_id(device_id):
        return False
    if "\\subunit\\" in device_id_lower or " subunit" in record_text:
        return False
    return "\\capture" not in device_id_lower and "application" not in record_text


def _device_aliases(data: Any) -> dict[str, str]:
    aliases: dict[str, str] = {}
    ambiguous = set()
    for record in _iter_records(data):
        device_id = _first_text(record, _COMMAND_ID_KEY, "Name")
        if not _is_render_endpoint(record, device_id):
            continue
        for alias in _device_alias_candidates(record, device_id):
            key = _device_match_key(alias)
            if not key:
                continue
            if key in aliases and aliases[key] != device_id:
                ambiguous.add(key)
            else:
                aliases[key] = device_id
    for key in ambiguous:
        aliases.pop(key, None)
    return aliases


def _device_alias_candidates(record: dict[str, Any], device_id: str) -> list[str]:
    name = _first_text(record, "Device Name", "Name")
    controller = _first_text(record, "Device")
    endpoint = ""
    device_id_lower = device_id.lower()
    if "\\device\\" in device_id_lower and device_id_lower.endswith("\\render"):
        parts = device_id.split("\\")
        if len(parts) >= 4 and parts[-3].casefold() == "device":
            controller = controller or parts[-4]
            endpoint = parts[-2]
    aliases = [device_id, name, controller, endpoint]
    if name and controller:
        aliases.append(f"{name} ({controller})")
    if endpoint and controller:
        aliases.append(f"{endpoint} ({controller})")
    return aliases


def _is_process_name(value: str, process_name: str) -> bool:
    value = value.casefold()
    process_name = process_name.casefold()
    return value == process_name or value.endswith(f"\\{process_name}")


def _is_sound_volume_view_device_id(device: str) -> bool:
    device_lower = device.lower()
    return "\\device\\" in device_lower and "\\render" in device_lower


def _first_text(record: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _device_match_key(device: str) -> str:
    if not isinstance(device, str):
        return ""
    device = device.casefold()
    device = device.replace("®", "").replace("™", "").replace("©", "")
    device = re.sub(r"\((?:r|tm|c)\)", "", device)
    return "".join(character for character in device if character.isalnum())


def _alert_error(message: str) -> None:
    try:
        from ok.gui.util.Alert import alert_error

        alert_error(message)
    except Exception:
        logger.error(message)


_router = _BackgroundAudioRouter()
atexit.register(restore_background_audio_router)
