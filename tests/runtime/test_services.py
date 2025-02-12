################################################################################
# © Copyright 2022-2023 Zapata Computing Inc.
################################################################################
"""
Unit tests for orquestra.sdk._base._services.
"""

import builtins
import subprocess
import sys
import typing as t
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, create_autospec

import pytest

from orquestra.sdk._base import _services

from ..reloaders import restore_loaded_modules


def _fake_run_for_ray(
    ray_start_retcode: t.Optional[int] = None,
    ray_status_retcode: t.Optional[int] = None,
    ray_stop_retcode: t.Optional[int] = None,
) -> t.Callable:
    """
    Prepares a mock for ``subprocess.run``.

    If a given ``*_retcode`` arg is not ``None``, and the corresponding Ray command is
    called, the result will mimic getting the subprocess retcode.

    If a given ``*_retcode`` arg is ``None``, and the corresponding Ray command is
    called, an ``AssertionError`` will be raised.
    """

    def _fake_run(cmd, *args, **kwargs):
        for cmd_head, retcode_spec in [
            (["ray", "start"], ray_start_retcode),
            (["ray", "status"], ray_status_retcode),
            (["ray", "stop"], ray_stop_retcode),
        ]:
            if cmd[:2] == cmd_head:
                if (retcode := retcode_spec) is not None:
                    proc_mock = Mock()
                    proc_mock.returncode = retcode
                    return proc_mock
                else:
                    pytest.fail()

    return _fake_run


def _mock_subprocess_module(monkeypatch):
    mock_subprocess = Mock()
    monkeypatch.setattr(
        _services,
        "subprocess",
        mock_subprocess,
    )
    return mock_subprocess


def _mock_subprocess_for_ray(
    monkeypatch,
    ray_start_retcode: t.Optional[int] = None,
    ray_status_retcode: t.Optional[int] = None,
    ray_stop_retcode: t.Optional[int] = None,
):
    """
    See docstring for ``_fake_run_for_ray``.
    """
    mock_subprocess = _mock_subprocess_module(monkeypatch)
    mock_subprocess.run = _fake_run_for_ray(
        ray_start_retcode=ray_start_retcode,
        ray_status_retcode=ray_status_retcode,
        ray_stop_retcode=ray_stop_retcode,
    )


@pytest.fixture
def monkeypatch_import(monkeypatch):
    original_import = builtins.__import__

    def _import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in ("python_on_whales"):
            raise ModuleNotFoundError(f"Mocked module not found {name}")
        return original_import(
            name, globals=globals, locals=locals, fromlist=fromlist, level=level
        )

    monkeypatch.setattr(builtins, "__import__", _import)


@contextmanager
def unload_module(module_name: str):
    for module in tuple(sys.modules.keys()):
        if module.startswith(module_name):
            del sys.modules[module]

    with restore_loaded_modules():
        yield


class TestRayManager:
    """
    Tests' boundaries::

        [RayManager]─────[subprocess]
    """

    def test_name(self):
        # Given
        sm = _services.RayManager()

        # When
        name = sm.name

        # Then
        assert name == "Ray"

    class TestUp:
        def test_ray_not_running(self, monkeypatch):
            # Given
            sm = _services.RayManager()
            # Mimic 'ray' CLI behavior.
            _mock_subprocess_for_ray(
                monkeypatch,
                ray_start_retcode=0,
                ray_status_retcode=0,
            )

            # When
            sm.up()

            # Then
            # [Expect no exception]

        def test_ray_already_running(self, monkeypatch):
            # Given
            sm = _services.RayManager()
            # Mimic 'ray' CLI behavior.
            _mock_subprocess_for_ray(
                monkeypatch,
                ray_start_retcode=1,
                ray_status_retcode=0,
            )

            # When
            sm.up()

            # Then
            # [Expect no exception]

        def test_ray_failed_to_start(self, monkeypatch):
            """
            ``ray start`` failed and ``ray status`` reports the cluster isn't running.
            """
            # Given
            sm = _services.RayManager()
            _subprocess = _mock_subprocess_module(monkeypatch)
            proc = create_autospec(subprocess.CompletedProcess)
            proc.check_returncode.side_effect = subprocess.CalledProcessError(
                returncode=1,
                cmd=["ray", "start", "--something"],
                output="some stdout".encode(),
                stderr="some stderr".encode(),
            )
            _subprocess.run.return_value = proc
            monkeypatch.setattr(sm, "is_running", lambda: False)

            # Then
            with pytest.raises(subprocess.CalledProcessError):
                # When
                sm.up()

    class TestDown:
        def test_no_services_running(self, monkeypatch):
            # Given
            sm = _services.RayManager()

            # Mimic 'ray' CLI behavior.
            _mock_subprocess_for_ray(monkeypatch, ray_stop_retcode=0)

            # When
            sm.down()

            # Then
            # [Expect no exception]

        def test_ray_already_running(self, monkeypatch):
            # Given
            sm = _services.RayManager()

            # Mimic 'ray' CLI behavior.
            _mock_subprocess_for_ray(monkeypatch, ray_stop_retcode=0)

            # When
            sm.down()

            # Then
            # [Expect no exception]

    class TestIsRunning:
        def test_no_services_running(self, monkeypatch):
            # Given
            sm = _services.RayManager()

            # Mimic 'ray' CLI behavior.
            _mock_subprocess_for_ray(monkeypatch, ray_status_retcode=1)

            # When
            is_running = sm.is_running()

            # Then
            assert not is_running

        def test_ray_already_running(self, monkeypatch):
            # Given
            sm = _services.RayManager()

            # Mimic 'ray' CLI behavior.
            _mock_subprocess_for_ray(monkeypatch, ray_status_retcode=0)

            # When
            is_running = sm.is_running()

            # Then
            assert is_running


class TestRayLocation:
    class TestRayTemp:
        def test_with_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
            # Given
            monkeypatch.setenv("ORQ_RAY_TEMP_PATH", str(tmp_path))

            # When
            location = _services.ray_temp_path()

            # Then
            assert location == tmp_path

        def test_without_env(self):
            # Given
            # Nothing

            # When
            location = _services.ray_temp_path()

            # Then
            assert location == Path.home() / ".orquestra" / "ray"

    class TestRayStorage:
        def test_with_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
            # Given
            monkeypatch.setenv("ORQ_RAY_STORAGE_PATH", str(tmp_path))

            # When
            location = _services.ray_storage_path()

            # Then
            assert location == tmp_path

        def test_without_env(self):
            # Given
            # Nothing

            # When
            location = _services.ray_storage_path()

            # Then
            assert location == Path.home() / ".orquestra" / "ray_storage"

    class TestRayPlasma:
        def test_with_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
            # Given
            monkeypatch.setenv("ORQ_RAY_PLASMA_PATH", str(tmp_path))

            # When
            location = _services.ray_plasma_path()

            # Then
            assert location == tmp_path

        def test_without_env(self):
            # Given
            # Nothing

            # When
            location = _services.ray_plasma_path()

            # Then
            assert location == Path.home() / ".orquestra" / "ray_plasma"
