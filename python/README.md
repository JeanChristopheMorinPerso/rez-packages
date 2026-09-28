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
rez-build --install
```

Then verify the package with:

```console
rez-env python -- python --version
```

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
