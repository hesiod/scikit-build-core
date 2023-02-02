from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import types
import warnings
from collections.abc import Generator
from pathlib import Path
from venv import EnvBuilder

if sys.version_info < (3, 8):
    import importlib_metadata as metadata
    from typing_extensions import Literal, overload
else:
    from importlib import metadata
    from typing import Literal, overload

import pytest

DIR = Path(__file__).parent.resolve()
BASE = DIR.parent


@pytest.fixture(scope="session")
def pep518_wheelhouse(tmp_path_factory: pytest.TempPathFactory) -> Path:
    wheelhouse = tmp_path_factory.mktemp("wheelhouse")

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--wheel-dir",
            str(wheelhouse),
            f"{BASE}[pyproject]",
        ],
        check=True,
    )
    packages = [
        "build",
        "pybind11",
        "rich",
        "setuptools",
        "virtualenv",
        "wheel",
    ]

    if importlib.util.find_spec("cmake") is not None:
        packages.append("cmake")

    if importlib.util.find_spec("ninja") is not None:
        packages.append("ninja")

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "-q",
            "-d",
            str(wheelhouse),
            *packages,
        ],
        check=True,
    )
    return wheelhouse


class VEnv(EnvBuilder):
    executable: Path
    env_dir: Path

    def __init__(self, env_dir: Path, *, wheelhouse: Path | None = None) -> None:
        super().__init__(with_pip=True)
        # This warning is mistakenly generated by CPython 3.11.0
        # https://github.com/python/cpython/pull/98743
        with warnings.catch_warnings():
            if sys.version_info[:3] == (3, 11, 0):
                warnings.filterwarnings(
                    "ignore",
                    "check_home argument is deprecated and ignored.",
                    DeprecationWarning,
                )
            self.create(env_dir)
        self.wheelhouse = wheelhouse

    def ensure_directories(
        self, env_dir: str | bytes | os.PathLike[str] | os.PathLike[bytes]
    ) -> types.SimpleNamespace:
        context = super().ensure_directories(env_dir)
        # Store the path to the venv Python interpreter.
        # See https://github.com/mesonbuild/meson-python/blob/8a180be7b4abd7e1939a63d5d59f63197ee27cc7/tests/conftest.py#LL79
        self.executable = Path(context.env_exe)
        self.env_dir = Path(context.env_dir)
        return context

    @overload
    def run(self, *args: str, capture: Literal[True]) -> str:
        ...

    @overload
    def run(self, *args: str, capture: Literal[False] = ...) -> None:
        ...

    def run(self, *args: str, capture: bool = False) -> str | None:
        env = os.environ.copy()
        env["PATH"] = f"{self.executable.parent}{os.pathsep}{env['PATH']}"
        env["VIRTUAL_ENV"] = str(self.env_dir)
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "ON"
        if self.wheelhouse is not None:
            env["PIP_NO_INDEX"] = "ON"
            env["PIP_FIND_LINKS"] = str(self.wheelhouse)

        if capture:
            return subprocess.run(
                [os.fspath(a) for a in args],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            ).stdout.strip()

        subprocess.run(
            [os.fspath(a) for a in args],
            check=True,
            env=env,
        )
        return None

    def execute(self, command: str) -> str:
        return self.run(str(self.executable), "-c", command, capture=True)

    def module(self, *args: str) -> None:
        return self.run(str(self.executable), "-m", *args)

    def install(self, *args: str) -> None:
        self.module("pip", "install", *args)


@pytest.fixture()
def isolated(tmp_path: Path, pep518_wheelhouse: Path) -> Generator[VEnv, None, None]:
    path = tmp_path / "venv"
    try:
        yield VEnv(path, wheelhouse=pep518_wheelhouse)
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture()
def virtualenv(tmp_path: Path) -> Generator[VEnv, None, None]:
    path = tmp_path / "venv"
    try:
        yield VEnv(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        # Ensure all tests using virtualenv are marked as such
        if "virtualenv" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.virtualenv)
        if "isolated" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.virtualenv)
            item.add_marker(pytest.mark.isolated)


def pytest_report_header() -> str:
    interesting_packages = {
        "build",
        "packaging",
        "pathspec",
        "pip",
        "pybind11",
        "pyproject_metadata",
        "rich",
        "setuptools",
        "virtualenv",
        "wheel",
    }
    valid = []
    for package in interesting_packages:
        try:
            version = metadata.version(package)  # type: ignore[no-untyped-call]
        except ModuleNotFoundError:
            continue
        valid.append(f"{package}=={version}")
    reqs = " ".join(sorted(valid))
    pkg_line = f"installed packages of interest: {reqs}"

    return "\n".join([pkg_line])
