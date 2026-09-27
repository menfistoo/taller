> A Python program frozen by PyInstaller into one executable that runs without Python installed.

## Runtime shape

Source is an ordinary Python package with one entry module. The shipped artefact is
a single executable produced by PyInstaller, run from a shell or by a scheduler on a
machine that has no interpreter, no virtual environment and no network install path.
There is no user interface: input arrives as arguments, configuration files or
standard input, and results leave as files, exit codes and text.

## What "no interpreter on the target" changes

Everything that normally resolves at install time has to resolve at build time.

**Nothing may be installed at runtime.** No `pip`, no download of a missing wheel,
no "first run sets itself up". The target may have no network and no write access to
the program's own directory, so a dependency that is not frozen in is a dependency
that does not exist.

**Imports must be static.** PyInstaller discovers dependencies by analysing import
statements, so a module imported through `importlib` by a name built at runtime is
invisible to it and the frozen program fails with `ModuleNotFoundError` on the one
path the test suite did not take. If dynamic loading is unavoidable, declare the
module as a hidden import in the spec file and say in a comment why.

**Data files are not beside `__file__`.** A frozen program unpacks into a temporary
directory, so a path built from `__file__` points into that directory and vanishes.
Resolve bundled resources through the runtime's own base directory, and resolve
writable paths from an explicit argument or the user's own directories instead.

## Working directory and exit codes

The working directory is whatever the caller had; it is not the program's location.
Every path the program reads or writes is either absolute or resolved against a
directory it was told about. A scheduler is often the only caller, and a scheduler
reads nothing but the exit code, so return zero only on success, return a non-zero
code on failure, and write the reason to stderr before exiting.

## Build and verification

The build is a checked-in script or spec file, never a command someone remembers.
The only meaningful check is running the built executable: the import graph, the
data files and the path handling all differ between the source tree and the frozen
artefact, so a green test suite against source says nothing about the thing you
ship. Build it and run it before calling the work done.
