# Python from python-build-standalone

This example packages a prebuilt, relocatable CPython from
[python-build-standalone](https://github.com/astral-sh/python-build-standalone).
It supports the common 64-bit targets on Linux, macOS, and Windows:

| Platform | Architectures |
| --- | --- |
| Linux (glibc) | x86-64, ARM64 |
| macOS | Intel, Apple Silicon |
| Windows | x86-64, ARM64 |

The build pins both Python and the python-build-standalone release. Each archive
is checked against its pinned SHA-256 digest before extraction.

The package definition uses `rez.system.system.variant` to dynamically create a
single variant from Rez's detected platform, architecture, and operating system.
Build and install it with:

```console
rez-build --download-upstream --install
```

Then verify the package with:

```console
rez-env python -- python --version
```

## Offline builds

While online, download and verify the archive without extracting it:

```console
rez-build --clean --download-upstream --download-only
```

This caches the archive in the variant's directory under `build`. Preserve that
directory when transferring the source tree to an offline machine. On the
offline machine, build and install without `--clean` so the cached archive is
retained and reused:

```console
rez-build --download-upstream --install
```

The target machine must match the platform and architecture used for the
download, and its Rez package path must already provide the corresponding
`platform`, `arch`, and `os` packages. The checksum is verified again before the
cached archive is used. Do not combine `--download-only` with `--install`.

Alternatively, provide an archive from an internal mirror, shared drive, or
other trusted transfer mechanism. This mode never accesses the network:

```console
rez-build --archive /path/to/cpython-install_only.tar.gz --install
```

Relative archive paths are resolved from the directory containing `package.py`.
The provided archive must match the configured Python version, standalone
release, platform, and architecture; its pinned checksum is always verified.
Exactly one of `--download-upstream` and `--archive PATH` is required for every
normal build, local install, or release.

Run the build on each target platform and architecture that you want to publish;
this recipe downloads native binaries and does not cross-compile. The Linux
archives target glibc and therefore do not support musl-only distributions such
as Alpine Linux. Artifact selection uses the native host values independently
of Rez's mapped architecture and operating-system package names.

Only `python` is declared as a common tool because executable names differ by
platform. Portable invocations of bundled utilities can use `python -m pip`,
`python -m idlelib`, and similar module forms.

The Rez package version matches CPython's three-part version so tools such as
rez-pip2 can pass it to pip's `--python-version` option. To update Python, change
`version` in `package.py`, then update `RELEASE` and the checksums in `ARTIFACTS`
from the upstream release's `SHA256SUMS` or GitHub release metadata.

## Tests

From this directory, in an environment containing Rez, pytest, and pytest-cov,
run the suite with 100% statement and branch coverage enforced for the build
logic. The suite also exercises the custom arguments and package definition
through Rez's public APIs:

```console
python -m pytest --cov=. --cov-config=.coveragerc \
    --cov-report=term-missing --cov-fail-under=100 tests
```
