"""Compatibility layer for running ok-script TaskTestCase suites together.

Why this exists:
    ok.test.TaskTestCase was designed around ok.test.init_ok() keeping a
    module-level OK singleton. That is fine when test files are executed one at
    a time, but a single unittest discovery run keeps the Python process alive
    across many TaskTestCase classes. Without resetting ok-script's shared
    runtime state, later tests can inherit a finished executor/exit_event and
    fail with FinishedException when they call TaskTestCase.set_image().

    The TaskTestCase suites exercise task logic only, but the stock
    ok.test.init_ok() helper touches ok.app explicitly. That creates a GUI
    App/QApplication and leaves queued Qt cleanup work behind despite the test
    runner never entering Qt's event loop. Run these suites with ok's existing
    HeadlessApp instead. UI tests should create and own their QApplication
    explicitly instead of inheriting this process-wide runtime.

Future maintenance checklist:
    - If ok.test.TaskTestCase gains a real headless mode, remove the
      init_ok/destroy_ok patches below.
    - If ok.OK adds or removes class-level runtime attributes, update
      _OK_CLASS_STATE_ATTRS so no stale executor/device/feature state survives.
    - If ok.og gains new process-global runtime references, update
      _OK_GLOBAL_STATE_ATTRS for the same reason.

This module is imported by tests.__init__, so unittest discovery must run with
``--top-level-directory .``. Short ``-t .`` is intentionally avoided because
ok-script also parses ``-t`` as its task argument.
"""

from __future__ import annotations

import threading

import ok as _ok
import ok.test as _ok_test
import ok.test.TaskTestCase as _ok_task_test_case
from ok.gui.Communicate import communicate
from ok.task.TaskExecutor import TaskExecutor
from ok.util.handler import ExitEvent

_ORIGINALS_ATTR = "_ok_nte_runtime_isolation_originals"

_OK_CLASS_STATE_ATTRS = (
    "executor",
    "feature_set",
    "device_manager",
    "ocr",
    "overlay_window",
    "screenshot",
    "init_error",
)

_OK_GLOBAL_STATE_ATTRS = (
    "app",
    "executor",
    "device_manager",
    "handler",
    "my_app",
    "ok",
    "config",
    "task_manager",
    "global_config",
)


def install_ok_test_runtime_isolation() -> None:
    """Patch ok.test helpers so each TaskTestCase class starts from clean state."""
    if not hasattr(_ok_test, _ORIGINALS_ATTR):
        setattr(_ok_test, _ORIGINALS_ATTR, True)

        def init_ok_with_fresh_runtime(config):
            _ok_test.ok = None
            reset_ok_runtime_state()

            test_config = dict(config)
            test_config["analytics"] = None
            test_config["check_mutex"] = False
            test_config["debug"] = True
            test_config["use_gui"] = False
            test_config["my_app"] = None
            test_config["blur_area"] = None

            runtime = _ok.OK(test_config)
            _ok_test.ok = runtime
            runtime.task_executor.debug_mode = True
            runtime.device_manager.capture_method = _ok.ImageCaptureMethod(
                runtime.device_manager.exit_event, []
            )
            runtime.device_manager.device_dict["image"] = {
                "address": "",
                "imei": "image",
                "device": "image",
                "nick": "Image",
                "width": 0,
                "height": 0,
                "capture": "image",
                "connected": True,
            }
            runtime.device_manager.config["preferred"] = "image"
            runtime.device_manager.interaction = _ok.DoNothingInteraction(
                runtime.device_manager.capture_method
            )
            if scene_config := test_config.get("scene"):
                runtime.task_executor.scene = _ok.init_class_by_name(
                    scene_config[0], scene_config[1]
                )
            runtime.task_executor.start()

        def destroy_ok_and_clear_singleton():
            runtime = _ok_test.ok
            try:
                if runtime is not None:
                    runtime.quit()
                    executor_thread = runtime.task_executor.thread
                    if executor_thread and executor_thread is not threading.current_thread():
                        executor_thread.join(timeout=2.0)
                    if runtime._headless_app is not None:
                        try:
                            communicate.quit.disconnect(runtime._headless_app.quit)
                        except RuntimeError:
                            pass
            finally:
                _ok_test.ok = None
                reset_ok_runtime_state()

        def init_default_ocr_on_demand(_executor):
            """Avoid native OCR initialization racing interpreter shutdown in tests."""

        TaskExecutor.init_default_ocr = init_default_ocr_on_demand
        _ok_test.init_ok = init_ok_with_fresh_runtime
        _ok_test.destroy_ok = destroy_ok_and_clear_singleton

    # TaskTestCase imports these helpers directly.  Updating ok.test alone does
    # not affect a TaskTestCase module that was imported before this installer.
    _ok_task_test_case.init_ok = _ok_test.init_ok
    _ok_task_test_case.destroy_ok = _ok_test.destroy_ok


def reset_ok_runtime_state() -> None:
    """Clear ok-script process globals that leak between TaskTestCase classes."""
    ExitEvent.queues = set()
    ExitEvent.to_stops = set()
    _ok.OK.exit_event = ExitEvent()

    for attr in _OK_CLASS_STATE_ATTRS:
        setattr(_ok.OK, attr, None)

    for attr in _OK_GLOBAL_STATE_ATTRS:
        setattr(_ok.og, attr, None)
