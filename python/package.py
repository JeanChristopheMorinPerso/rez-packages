name = "python"

version = "3.13.15"

authors = [
    "Python Software Foundation",
    "python-build-standalone contributors",
]

description = \
    """
    A relocatable CPython distribution provided by https://github.com/astral-sh/python-build-standalone
    """

tools = [
    "python",
]


@early()
def variants():
    from rez.system import system

    return [system.variant]

uuid = "eff7708f-4779-4a8d-af3f-3a60970138bf"

build_command = 'python {root}/build.py {install}'


def commands():
    if system.platform == "windows":
        env.PATH.prepend("{root}")
    else:
        env.PATH.prepend("{root}/bin")
