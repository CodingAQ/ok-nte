"""Compatibility layer for running ok-script TaskTestCase suites together.

Why this exists:
    ok.test.TaskTestCase was designed around ok.test.init_ok() keeping a
    module-level OK singleton. That is fine when test files are executed one at
    a time, but a single unittest discovery run keeps the Python process alive
    across many TaskTestCase classes. Without resetting ok-script's shared
    runtime state, later tests can inherit a finished executor/exit_event and
    fail with FinishedException when they call TaskTestCase.set_image().

    ok-script also has a headless entry point (ok.run_task(use_gui=False)), but
    the current ok.test.init_ok() helper still touches ok.app explicitly. That
    forces a GUI App/QApplication even for tests. Some ok-nte tests instantiate
    QWidget-based tabs directly, so this layer reuses one QApplication instead
    of trying to remove Qt from the test process.

Future maintenance checklist:
    - If ok.test.init_ok() starts creating a fresh OK runtime for every
      TaskTestCase class, remove the init_ok/destroy_ok patches below.
    - If ok.test.TaskTestCase gains a real headless mode, prefer that and keep
      only a small QApplication fixture for UI tests that instantiate widgets.
    - If ok.OK adds or removes class-level runtime attributes, update
      _OK_CLASS_STATE_ATTRS so no stale executor/device/feature state survives.
    - If ok.og gains new process-global runtime references, update
      _OK_GLOBAL_STATE_ATTRS for the same reason.

This module is imported by tests.__init__, so unittest discovery must run with
``--top-level-directory .``. Short ``-t .`` is intentionally avoided because
ok-script also parses ``-t`` as its task argument.
"""

from __future__ import annotations

from typing import Any, Callable, TypedDict

import ok as _ok
import ok.gui.util.app as _ok_app_util
import ok.test as _ok_test
from ok.gui.common.config import cfg
from ok.util.handler import ExitEvent
from PySide6.QtWidgets import QApplication

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


class _Originals(TypedDict):
    init_app_config: Callable[[], tuple[Any, Any]]
    init_ok: Callable[[dict[str, Any]], Any]
    destroy_ok: Callable[[], Any]


def install_ok_test_runtime_isolation() -> None:
    """Patch ok.test helpers so each TaskTestCase class starts from clean state."""
    if hasattr(_ok_test, _ORIGINALS_ATTR):
        return

    originals: _Originals = {
        "init_app_config": _ok_app_util.init_app_config,
        "init_ok": _ok_test.init_ok,
        "destroy_ok": _ok_test.destroy_ok,
    }
    setattr(_ok_test, _ORIGINALS_ATTR, originals)

    def init_app_config_reusing_qapplication():
        app = QApplication.instance()
        if app is None:
            return originals["init_app_config"]()
        return app, cfg.get(cfg.language).value

    def init_ok_with_fresh_runtime(config):
        _ok_test.ok = None
        reset_ok_runtime_state()
        return originals["init_ok"](config)

    def destroy_ok_and_clear_singleton():
        try:
            return originals["destroy_ok"]()
        finally:
            _ok_test.ok = None
            reset_ok_runtime_state()

    _ok_app_util.init_app_config = init_app_config_reusing_qapplication
    _ok_test.init_ok = init_ok_with_fresh_runtime
    _ok_test.destroy_ok = destroy_ok_and_clear_singleton


def reset_ok_runtime_state() -> None:
    """Clear ok-script process globals that leak between TaskTestCase classes."""
    ExitEvent.queues = set()
    ExitEvent.to_stops = set()
    _ok.OK.exit_event = ExitEvent()

    for attr in _OK_CLASS_STATE_ATTRS:
        setattr(_ok.OK, attr, None)

    for attr in _OK_GLOBAL_STATE_ATTRS:
        setattr(_ok.og, attr, None)
