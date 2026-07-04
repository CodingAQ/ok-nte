import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src import GAME_EXE
from src import audio_routing
from src.audio_routing import (
    CONF_ENABLE,
    CONF_SOUND_VOLUME_VIEW_PATH,
    DEFAULT_RENDER_DEVICE,
    _BackgroundAudioRouter,
    _RouteRequest,
    _background_audio_routing_validator,
    _resolve_sound_volume_view_device_id,
    audio_route_command,
    discover_output_devices,
    parse_app_output_device,
)


class AudioRoutingTests(unittest.TestCase):
    def test_discover_output_devices_uses_sounddevice_playback_devices(self):
        fake_sounddevice = SimpleNamespace(
            query_hostapis=lambda: [
                {"name": "MME"},
                {"name": "Windows WASAPI"},
                {"name": "Windows WDM-KS"},
            ],
            query_devices=lambda: [
                {"name": "Microsoft Sound Mapper - Output", "max_output_channels": 2, "hostapi": 0},
                {"name": "Speakers (Realtek(R) Audio)", "max_output_channels": 2, "hostapi": 1},
                {"name": "Speakers (Realtek(R) Audio)", "max_output_channels": 2, "hostapi": 1},
                {"name": "Microphone (Realtek(R) Audio)", "max_output_channels": 0, "hostapi": 1},
                {"name": "Speakers 1", "max_output_channels": 2, "hostapi": 2},
            ],
        )

        with patch.dict(sys.modules, {"sounddevice": fake_sounddevice}):
            devices = discover_output_devices()

        self.assertEqual(devices, [DEFAULT_RENDER_DEVICE, "Speakers (Realtek(R) Audio)"])

    def test_resolve_sound_volume_view_device_id_matches_sounddevice_name(self):
        data = {
            "Sound Items": [
                {
                    "Name": "Speakers",
                    "Command-Line Friendly ID": "Realtek Audio\\Device\\Speakers\\Render",
                    "Type": "Device",
                    "Direction": "Render",
                    "Device": "Realtek Audio",
                },
            ]
        }

        self.assertEqual(
            _resolve_sound_volume_view_device_id(data, "Speakers (Realtek(R) Audio)"),
            "Realtek Audio\\Device\\Speakers\\Render",
        )

    def test_resolve_sound_volume_view_device_id_ignores_non_render_records(self):
        data = {
            "Sound Items": [
                {
                    "Name": "Microphone",
                    "Command-Line Friendly ID": "Realtek Audio\\Device\\Microphone\\Capture",
                    "Type": "Device",
                    "Direction": "Capture",
                },
                {
                    "Name": "HTGame.exe",
                    "Command-Line Friendly ID": "HTGame.exe",
                    "Type": "Application",
                    "Direction": "Render",
                },
                {
                    "Name": "聲波音量",
                    "Command-Line Friendly ID": "VB-Audio VoiceMeeter VAIO\\Subunit\\聲波音量",
                    "Type": "Subunit",
                    "Direction": "Render",
                },
            ]
        }

        self.assertEqual(_resolve_sound_volume_view_device_id(data, "Microphone"), "")

    def test_audio_route_command_targets_game_process(self):
        self.assertEqual(
            audio_route_command("USB Audio\\Device\\Speakers\\Render"),
            [
                "/SetAppDefault",
                "USB Audio\\Device\\Speakers\\Render",
                "all",
                GAME_EXE,
            ],
        )

    def test_audio_route_command_can_restore_default_render_device(self):
        self.assertEqual(
            audio_route_command(DEFAULT_RENDER_DEVICE),
            [
                "/SetAppDefault",
                DEFAULT_RENDER_DEVICE,
                "all",
                GAME_EXE,
            ],
        )

    def test_parse_app_output_device_resolves_device_name_to_command_id(self):
        data = {
            "Sound Items": [
                {
                    "Name": "Speakers",
                    "Command-Line Friendly ID": "Realtek Audio\\Device\\Speakers\\Render",
                    "Type": "Device",
                    "Direction": "Render",
                },
                {
                    "Name": GAME_EXE,
                    "Command-Line Friendly ID": GAME_EXE,
                    "Type": "Application",
                    "Device Name": "Speakers",
                },
            ]
        }

        self.assertEqual(
            parse_app_output_device(data),
            "Realtek Audio\\Device\\Speakers\\Render",
        )

    def test_parse_app_output_device_falls_back_to_default_without_app_record(self):
        self.assertEqual(parse_app_output_device([]), DEFAULT_RENDER_DEVICE)

    def test_router_captures_original_app_output_device_before_background_route(self):
        router = _BackgroundAudioRouter()
        router._pending_route = _RouteRequest(
            "USB Audio\\Device\\Speakers\\Render",
            capture_original=True,
        )
        calls = []

        def route(_exe_path, device):
            calls.append(device)
            return True

        router._apply_route = route

        with patch.object(
            audio_routing,
            "discover_app_output_device",
            return_value="USB Audio\\Device\\Headphones\\Render",
        ):
            router._run_pending_routes("SoundVolumeView.exe")

        self.assertEqual(calls, ["USB Audio\\Device\\Speakers\\Render"])
        self.assertEqual(router._original_device, "USB Audio\\Device\\Headphones\\Render")

    def test_failed_route_does_not_mark_device_as_requested(self):
        router = _BackgroundAudioRouter()
        router._pending_route = _RouteRequest(
            "USB Audio\\Device\\Speakers\\Render",
            capture_original=True,
        )
        router._original_device = DEFAULT_RENDER_DEVICE
        calls = []

        def fail_route(_exe_path, device):
            calls.append(device)
            return False

        router._apply_route = fail_route

        router._run_pending_routes("SoundVolumeView.exe")

        self.assertEqual(calls, ["USB Audio\\Device\\Speakers\\Render"])
        self.assertIsNone(router._requested_device)

    def test_restore_route_uses_original_device(self):
        router = _BackgroundAudioRouter()
        router._pending_route = _RouteRequest(
            "USB Audio\\Device\\Headphones\\Render",
            capture_original=False,
        )
        router._original_device = "USB Audio\\Device\\Headphones\\Render"
        calls = []

        def route(_exe_path, device):
            calls.append(device)
            return True

        router._apply_route = route

        router._run_pending_routes("SoundVolumeView.exe")

        self.assertEqual(calls, ["USB Audio\\Device\\Headphones\\Render"])
        self.assertEqual(router._requested_device, "USB Audio\\Device\\Headphones\\Render")

    def test_restore_updates_requested_device_after_disable(self):
        router = _BackgroundAudioRouter()
        router._requested_device = "USB Audio\\Device\\Speakers\\Render"
        router._original_device = "USB Audio\\Device\\Headphones\\Render"
        router._restore_exe_path = "SoundVolumeView.exe"
        router._restore_needed = True
        calls = []

        def route(_exe_path, device):
            calls.append(device)
            return True

        router._apply_route = route

        with patch.object(audio_routing, "_is_sound_volume_view_path", return_value=True):
            router.restore_on_exit()

        self.assertEqual(calls, ["USB Audio\\Device\\Headphones\\Render"])
        self.assertEqual(router._requested_device, "USB Audio\\Device\\Headphones\\Render")
        self.assertFalse(router._restore_needed)

    def test_disabling_config_restores_audio_router(self):
        validator = _background_audio_routing_validator([DEFAULT_RENDER_DEVICE])

        with patch.object(audio_routing, "restore_background_audio_router") as restore:
            self.assertEqual(validator(CONF_ENABLE, False), (True, None))

        restore.assert_called_once_with()

    def test_enabling_config_routes_current_window_state(self):
        validator = _background_audio_routing_validator([DEFAULT_RENDER_DEVICE])

        with patch.object(audio_routing, "route_background_audio_for_current_window") as route:
            self.assertEqual(validator(CONF_ENABLE, True), (True, None))

        route.assert_called_once_with()

    def test_reset_to_default_restores_audio_when_enabled(self):
        class ResettableConfig(dict):
            def reset_to_default(self):
                self.clear()
                self.update({CONF_ENABLE: False})

        config = ResettableConfig({CONF_ENABLE: True})
        global_config = SimpleNamespace(get_config=lambda _name: config)

        with patch.object(audio_routing.og, "global_config", global_config, create=True):
            audio_routing._routing_config()
            audio_routing._routing_config()

        with patch.object(audio_routing, "restore_background_audio_router") as restore:
            config.reset_to_default()

        restore.assert_called_once_with()

    def test_reset_to_default_patch_preserves_original_arguments(self):
        class ResettableConfig(dict):
            def reset_to_default(self, enabled):
                self.clear()
                self.update({CONF_ENABLE: enabled})

        config = ResettableConfig({CONF_ENABLE: True})
        global_config = SimpleNamespace(get_config=lambda _name: config)

        with patch.object(audio_routing.og, "global_config", global_config, create=True):
            audio_routing._routing_config()

        with patch.object(audio_routing, "restore_background_audio_router") as restore:
            config.reset_to_default(False)

        restore.assert_called_once_with()

    def test_route_current_window_state_uses_last_window_signal(self):
        router = _BackgroundAudioRouter()
        router._last_visible = False
        calls = []

        router._request_route = lambda visible, enabled=None: calls.append((visible, enabled))

        router.route_current_window_state()

        self.assertEqual(calls, [(False, True)])

    def test_foreground_route_waits_for_original_device_capture(self):
        router = _BackgroundAudioRouter()
        router._pending_route = _RouteRequest(
            "USB Audio\\Device\\Speakers\\Render",
            capture_original=True,
        )
        router._requested_device = DEFAULT_RENDER_DEVICE
        router._worker = SimpleNamespace(is_alive=lambda: True)
        config = {CONF_SOUND_VOLUME_VIEW_PATH: "SoundVolumeView.exe"}

        with patch.object(audio_routing, "_routing_config", return_value=config):
            with patch.object(audio_routing, "_is_sound_volume_view_path", return_value=True):
                router._request_route(True, enabled=True)

        self.assertEqual(
            router._pending_route,
            _RouteRequest(DEFAULT_RENDER_DEVICE, capture_original=False, restore_original=True),
        )

        calls = []
        router._original_device = "USB Audio\\Device\\Headphones\\Render"
        router._apply_route = lambda _exe_path, device: calls.append(device) or True

        router._run_pending_routes("SoundVolumeView.exe")

        self.assertEqual(calls, ["USB Audio\\Device\\Headphones\\Render"])

    def test_router_binds_to_ok_exit_event_for_forced_terminal_exit(self):
        router = _BackgroundAudioRouter()
        bound = []
        exit_event = SimpleNamespace(bind_stop=lambda obj: bound.append(obj))

        with patch.object(audio_routing.og, "ok", SimpleNamespace(exit_event=exit_event), create=True):
            with patch.object(audio_routing.og, "exit_event", None, create=True):
                router._bind_exit_event()

        self.assertEqual(bound, [router])

    def test_router_stop_restores_audio(self):
        router = _BackgroundAudioRouter()

        with patch.object(router, "restore_on_exit") as restore:
            router.stop()

        restore.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
