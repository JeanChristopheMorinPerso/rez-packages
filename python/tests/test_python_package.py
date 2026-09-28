import hashlib
import importlib.util
import io
import os
import runpy
import sys
import tarfile
from types import SimpleNamespace

import pytest

from rez.cli import build as build_cli
from rez.cli._main import setup_parser
from rez.packages import get_developer_package
from rez.rex import Python, RexExecutor


PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_FILE = os.path.join(PACKAGE_ROOT, "build.py")


@pytest.fixture
def build_module():
    spec = importlib.util.spec_from_file_location("example_python_build", BUILD_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_archive(path, members=None):
    members = members or [("python/bin/python", b"interpreter")]
    with tarfile.open(path, "w:gz") as archive:
        root = tarfile.TarInfo("python")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)

        for name, contents in members:
            member = tarfile.TarInfo(name)
            member.size = len(contents)
            archive.addfile(member, io.BytesIO(contents))
    return path


def _configure_artifact(build_module, monkeypatch, archive_path):
    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    host = ("test-platform", "test-arch")
    monkeypatch.setattr(build_module, "_host", lambda: host)
    monkeypatch.setattr(
        build_module,
        "ARTIFACTS",
        {(build_module.RELEASE,) + host: ("test-target", checksum)},
    )
    monkeypatch.setenv("REZ_BUILD_PROJECT_VERSION", "1.2.3")
    monkeypatch.delenv("__PARSE_ARG_DOWNLOAD_ONLY", raising=False)
    monkeypatch.delenv("__PARSE_ARG_DOWNLOAD_UPSTREAM", raising=False)
    monkeypatch.delenv("__PARSE_ARG_ARCHIVE", raising=False)
    return checksum


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("Linux", "x86_64", ("linux", "x86_64")),
        ("Linux", "aarch64", ("linux", "aarch64")),
        ("Darwin", "x86_64", ("osx", "x86_64")),
        ("Darwin", "arm64", ("osx", "aarch64")),
        ("Windows", "AMD64", ("windows", "x86_64")),
        ("Windows", "ARM64", ("windows", "aarch64")),
    ],
)
def test_host_normalizes_supported_systems(
    build_module, monkeypatch, system, machine, expected
):
    monkeypatch.setattr(build_module.platform, "system", lambda: system)
    monkeypatch.setattr(build_module.platform, "machine", lambda: machine)

    assert build_module._host() == expected


@pytest.mark.parametrize(
    ("system", "machine"),
    [("Plan9", "x86_64"), ("Linux", "mips64")],
)
def test_host_rejects_unsupported_systems(
    build_module, monkeypatch, system, machine
):
    monkeypatch.setattr(build_module.platform, "system", lambda: system)
    monkeypatch.setattr(build_module.platform, "machine", lambda: machine)

    with pytest.raises(RuntimeError, match="Unsupported host: %s %s" % (system, machine)):
        build_module._host()


def test_sha256_reads_the_complete_file(build_module, tmp_path):
    contents = b"a" * (1024 * 1024) + b"tail"
    path = tmp_path / "archive"
    path.write_bytes(contents)

    assert build_module._sha256(path) == hashlib.sha256(contents).hexdigest()


def test_download_reuses_a_verified_cached_archive(
    build_module, monkeypatch, tmp_path
):
    contents = b"cached"
    destination = tmp_path / "archive.tar.gz"
    destination.write_bytes(contents)
    checksum = hashlib.sha256(contents).hexdigest()

    def fail_if_called(_url):
        raise AssertionError("urlopen should not be called")

    monkeypatch.setattr(build_module, "urlopen", fail_if_called)
    build_module._download("https://invalid.example", os.fspath(destination), checksum)

    assert destination.read_bytes() == contents


@pytest.mark.parametrize(
    ("existing_destination", "existing_partial"),
    [(False, False), (False, True), (True, False), (True, True)],
)
def test_download_replaces_incomplete_or_invalid_files(
    build_module, tmp_path, existing_destination, existing_partial
):
    contents = b"fresh archive"
    source = tmp_path / "source.tar.gz"
    source.write_bytes(contents)
    destination = tmp_path / "archive.tar.gz"
    partial = str(destination) + ".part"
    if existing_destination:
        destination.write_bytes(b"invalid cache")
    if existing_partial:
        with open(partial, "wb") as stream:
            stream.write(b"interrupted download")

    build_module._download(
        source.as_uri(), os.fspath(destination), hashlib.sha256(contents).hexdigest()
    )

    assert destination.read_bytes() == contents
    assert not os.path.exists(partial)


def test_download_removes_partial_file_after_checksum_failure(build_module, tmp_path):
    source = tmp_path / "source.tar.gz"
    source.write_bytes(b"wrong contents")
    destination = tmp_path / "archive.tar.gz"
    partial = str(destination) + ".part"

    with pytest.raises(RuntimeError, match="SHA-256 mismatch for archive.tar.gz"):
        build_module._download(source.as_uri(), os.fspath(destination), "0" * 64)

    assert not destination.exists()
    assert not os.path.exists(partial)


def test_download_cleans_up_after_open_failure(build_module, tmp_path):
    destination = tmp_path / "archive.tar.gz"
    partial = str(destination) + ".part"
    with open(partial, "wb") as stream:
        stream.write(b"leftover")

    with pytest.raises(Exception):
        build_module._download(
            (tmp_path / "missing.tar.gz").as_uri(),
            os.fspath(destination),
            "0" * 64,
        )

    assert not os.path.exists(partial)


@pytest.mark.parametrize("destination_exists", [False, True])
def test_extract_replaces_destination(
    build_module, tmp_path, destination_exists
):
    archive = _write_archive(tmp_path / "archive.tar.gz")
    destination = tmp_path / "python"
    if destination_exists:
        destination.mkdir()
        (destination / "stale").write_text("stale")

    build_module._extract(archive, destination)

    assert (destination / "bin" / "python").read_bytes() == b"interpreter"
    assert not (destination / "stale").exists()


def test_extract_rejects_members_outside_python_directory(build_module, tmp_path):
    archive = _write_archive(
        tmp_path / "archive.tar.gz", [("unexpected/file", b"contents")]
    )

    with pytest.raises(RuntimeError, match="Unexpected archive member"):
        build_module._extract(archive, tmp_path / "destination")


def test_extract_rejects_path_traversal(build_module, tmp_path):
    archive = _write_archive(
        tmp_path / "archive.tar.gz", [("python/../../escape", b"contents")]
    )

    with pytest.raises(RuntimeError, match="Unsafe archive member"):
        build_module._extract(archive, tmp_path / "destination")

    assert not (tmp_path / "escape").exists()


def test_build_rejects_download_only_install(build_module, monkeypatch, tmp_path):
    monkeypatch.setenv("__PARSE_ARG_DOWNLOAD_ONLY", "1")

    with pytest.raises(RuntimeError, match="cannot be combined"):
        build_module.build(tmp_path, tmp_path / "build", tmp_path / "install", ["install"])


def test_build_rejects_unconfigured_release(build_module, monkeypatch, tmp_path):
    monkeypatch.setattr(build_module, "_host", lambda: ("test", "arch"))
    monkeypatch.setattr(build_module, "ARTIFACTS", {})

    with pytest.raises(RuntimeError, match="No artifact configured for release"):
        build_module.build(tmp_path, tmp_path / "build", tmp_path / "install", [])


def test_build_requires_an_archive_source(build_module, monkeypatch, tmp_path):
    archive = _write_archive(tmp_path / "archive.tar.gz")
    _configure_artifact(build_module, monkeypatch, archive)

    with pytest.raises(RuntimeError, match="Choose --download-upstream or --archive"):
        build_module.build(tmp_path, tmp_path / "build", tmp_path / "install", [])


def test_build_rejects_a_missing_local_archive(build_module, monkeypatch, tmp_path):
    archive = _write_archive(tmp_path / "archive.tar.gz")
    _configure_artifact(build_module, monkeypatch, archive)
    monkeypatch.setenv("__PARSE_ARG_ARCHIVE", "missing.tar.gz")

    with pytest.raises(RuntimeError, match="Archive does not exist"):
        build_module.build(tmp_path, tmp_path / "build", tmp_path / "install", [])


def test_build_rejects_local_archive_with_wrong_checksum(
    build_module, monkeypatch, tmp_path
):
    expected_archive = _write_archive(tmp_path / "expected.tar.gz")
    supplied_archive = _write_archive(
        tmp_path / "supplied.tar.gz", [("python/bin/python", b"different")]
    )
    _configure_artifact(build_module, monkeypatch, expected_archive)
    monkeypatch.setenv("__PARSE_ARG_ARCHIVE", os.fspath(supplied_archive))

    with pytest.raises(RuntimeError, match="SHA-256 mismatch for supplied.tar.gz"):
        build_module.build(tmp_path, tmp_path / "build", tmp_path / "install", [])


def test_build_download_only_verifies_relative_local_archive(
    build_module, monkeypatch, tmp_path, capsys
):
    archive = _write_archive(tmp_path / "archive.tar.gz")
    _configure_artifact(build_module, monkeypatch, archive)
    monkeypatch.setenv("__PARSE_ARG_ARCHIVE", archive.name)
    monkeypatch.setenv("__PARSE_ARG_DOWNLOAD_ONLY", "1")

    build_module.build(tmp_path, tmp_path / "build", tmp_path / "install", [])

    assert "Archive ready: %s" % archive in capsys.readouterr().out
    assert not (tmp_path / "build" / "python").exists()


@pytest.mark.parametrize(
    ("install", "install_exists"),
    [(False, False), (True, False), (True, True)],
)
def test_build_extracts_and_optionally_installs_local_archive(
    build_module, monkeypatch, tmp_path, install, install_exists
):
    archive = _write_archive(tmp_path / "archive.tar.gz")
    _configure_artifact(build_module, monkeypatch, archive)
    monkeypatch.setenv("__PARSE_ARG_ARCHIVE", os.fspath(archive))
    build_path = tmp_path / "build"
    install_path = tmp_path / "install"
    if install_exists:
        install_path.mkdir()
        (install_path / "stale").write_text("stale")

    targets = ["install"] if install else []
    build_module.build(tmp_path, build_path, install_path, targets)

    assert (build_path / "python" / "bin" / "python").exists()
    if install:
        assert (install_path / "bin" / "python").exists()
        assert not (install_path / "stale").exists()
    else:
        assert not install_path.exists()


def test_build_uses_verified_upstream_cache(build_module, monkeypatch, tmp_path):
    archive = _write_archive(tmp_path / "source.tar.gz")
    checksum = _configure_artifact(build_module, monkeypatch, archive)
    monkeypatch.setenv("__PARSE_ARG_DOWNLOAD_UPSTREAM", "1")
    build_path = tmp_path / "build"
    build_path.mkdir()
    cached_archive = build_path / (
        "cpython-1.2.3+%s-test-target-install_only.tar.gz" % build_module.RELEASE
    )
    cached_archive.write_bytes(archive.read_bytes())
    assert build_module._sha256(cached_archive) == checksum

    def fail_if_called(_url):
        raise AssertionError("verified cache should avoid the network")

    monkeypatch.setattr(build_module, "urlopen", fail_if_called)
    build_module.build(tmp_path, build_path, tmp_path / "install", [])

    assert (build_path / "python" / "bin" / "python").exists()


def test_build_script_main_forwards_environment_and_targets(monkeypatch, tmp_path):
    monkeypatch.setenv("REZ_BUILD_SOURCE_PATH", os.fspath(tmp_path))
    monkeypatch.setenv("REZ_BUILD_PATH", os.fspath(tmp_path / "build"))
    monkeypatch.setenv("REZ_BUILD_INSTALL_PATH", os.fspath(tmp_path / "install"))
    monkeypatch.setenv("__PARSE_ARG_DOWNLOAD_ONLY", "1")
    monkeypatch.setattr(sys, "argv", [os.fspath(BUILD_FILE), "install"])

    with pytest.raises(RuntimeError, match="cannot be combined"):
        runpy.run_path(os.fspath(BUILD_FILE), run_name="__main__")


def _parse_rez_build(monkeypatch, arguments):
    monkeypatch.chdir(PACKAGE_ROOT)
    monkeypatch.setattr(build_cli, "_package", None)
    return setup_parser().parse_args(["build"] + arguments)


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["--download-upstream"], (True, None, False)),
        (["--archive", "archive.tar.gz"], (False, "archive.tar.gz", False)),
        (
            ["--archive", "archive.tar.gz", "--download-only"],
            (False, "archive.tar.gz", True),
        ),
    ],
)
def test_parse_build_args_accepts_one_source(monkeypatch, arguments, expected):
    result = _parse_rez_build(monkeypatch, arguments)

    assert (result.download_upstream, result.archive, result.download_only) == expected


@pytest.mark.parametrize(
    "arguments",
    [[], ["--download-upstream", "--archive", "archive.tar.gz"]],
)
def test_parse_build_args_requires_exactly_one_source(monkeypatch, arguments):
    with pytest.raises(SystemExit):
        _parse_rez_build(monkeypatch, arguments)


def test_package_definition_uses_the_current_system_variant():
    from rez.system import system

    package = get_developer_package(os.fspath(PACKAGE_ROOT))

    assert package.name == "python"
    assert str(package.version) == "3.13.15"
    assert package.tools == ["python"]
    assert [
        [str(requirement) for requirement in variant]
        for variant in package.variants
    ] == [system.variant]


@pytest.mark.parametrize(
    ("platform", "expected"),
    [("windows", "/package"), ("linux", "/package/bin")],
)
def test_package_commands_prepend_platform_executable_path(platform, expected):
    package = get_developer_package(os.fspath(PACKAGE_ROOT))
    executor = RexExecutor(
        interpreter=Python(target_environ={}, passive=True),
        parent_environ={},
        shebang=False,
    )
    executor.bind("system", SimpleNamespace(platform=platform))
    executor.bind("root", "/package")

    executor.execute_code(package.commands)

    assert executor.get_output()["PATH"] == expected
