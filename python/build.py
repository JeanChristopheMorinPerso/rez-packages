#!/usr/bin/env python

import hashlib
import os
import platform
import shutil
import sys
import tarfile
from urllib.request import urlopen


RELEASE = "20260901"

ARTIFACTS = {
    ("linux", "x86_64"): (
        "x86_64-unknown-linux-gnu",
        "0651dd7157d3debf769e15a52c1de9de7fbcdc36ba72faf79fde3c44f14d9461",
    ),
    ("linux", "aarch64"): (
        "aarch64-unknown-linux-gnu",
        "76ed18125286d7dc96ce24023d1e319dbd55a89a767102411b1ea23846113f69",
    ),
    ("osx", "x86_64"): (
        "x86_64-apple-darwin",
        "49f0d97f506b855eed60b74a8ac138595c5b39799a6aa5e0d7ca8abe1019a4d4",
    ),
    ("osx", "aarch64"): (
        "aarch64-apple-darwin",
        "b9054a9d3d54f4cb5573d44907fddb29874b08909bde73f29f2868cf872223ee",
    ),
    ("windows", "x86_64"): (
        "x86_64-pc-windows-msvc",
        "9bcc038a0bf180612ed56dec93d4977d035e80b8d9320ef51a38c287baf134b7",
    ),
    ("windows", "aarch64"): (
        "aarch64-pc-windows-msvc",
        "ce87247378f43f88e0202a0fa6d3cdb5f5fb246a3bc61b2fb604bd49b7862508",
    ),
}


def _host():
    platforms = {
        "darwin": "osx",
        "linux": "linux",
        "windows": "windows",
    }
    architectures = {
        "aarch64": "aarch64",
        "amd64": "x86_64",
        "arm64": "aarch64",
        "x86_64": "x86_64",
    }
    try:
        return (
            platforms[platform.system().lower()],
            architectures[platform.machine().lower()],
        )
    except KeyError:
        raise RuntimeError(
            "Unsupported host: %s %s" % (platform.system(), platform.machine())
        )


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url, path, expected_sha256):
    if os.path.isfile(path) and _sha256(path) == expected_sha256:
        return

    partial_path = path + ".part"
    if os.path.exists(partial_path):
        os.remove(partial_path)

    print("Downloading %s" % url)
    try:
        with urlopen(url) as response, open(partial_path, "wb") as stream:
            shutil.copyfileobj(response, stream)

        actual_sha256 = _sha256(partial_path)
        if actual_sha256 != expected_sha256:
            raise RuntimeError(
                "SHA-256 mismatch for %s: expected %s, got %s"
                % (os.path.basename(path), expected_sha256, actual_sha256)
            )
        os.replace(partial_path, path)
    finally:
        if os.path.exists(partial_path):
            os.remove(partial_path)


def _extract(archive_path, destination):
    if os.path.isdir(destination):
        shutil.rmtree(destination)
    os.makedirs(destination)

    destination = os.path.realpath(destination)
    with tarfile.open(archive_path, "r:gz") as archive:
        members = []
        for member in archive.getmembers():
            if member.name == "python":
                continue
            if not member.name.startswith("python/"):
                raise RuntimeError("Unexpected archive member: %s" % member.name)

            member.name = member.name[len("python/"):]
            member_path = os.path.realpath(os.path.join(destination, member.name))
            if os.path.commonpath((destination, member_path)) != destination:
                raise RuntimeError("Unsafe archive member: %s" % member.name)
            members.append(member)

        archive.extractall(destination, members=members)


def build(source_path, build_path, install_path, targets):
    del source_path

    target, expected_sha256 = ARTIFACTS[_host()]
    version = os.environ["REZ_BUILD_PROJECT_VERSION"]
    filename = "cpython-%s+%s-%s-install_only.tar.gz" % (
        version, RELEASE, target
    )
    url = (
        "https://github.com/astral-sh/python-build-standalone/"
        "releases/download/%s/%s" % (RELEASE, filename)
    )
    archive_path = os.path.join(build_path, filename)
    python_path = os.path.join(build_path, "python")

    _download(url, archive_path, expected_sha256)
    _extract(archive_path, python_path)

    if "install" in (targets or []):
        if os.path.isdir(install_path):
            shutil.rmtree(install_path)
        shutil.copytree(python_path, install_path, symlinks=True)


if __name__ == "__main__":
    build(
        source_path=os.environ["REZ_BUILD_SOURCE_PATH"],
        build_path=os.environ["REZ_BUILD_PATH"],
        install_path=os.environ["REZ_BUILD_INSTALL_PATH"],
        targets=sys.argv[1:],
    )
