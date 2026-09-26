"""Keep bundled application libraries out of the worker's Python search path."""
from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile


@contextmanager
def isolated_command(python, source):
    # _MEIPASS contains the desktop NumPy and its dist-info, built for Python
    # 3.14. Adding it to a Python 3.11 worker's sys.path contaminates imports
    # and even importlib.metadata. Stage ONLY our small source package.
    # The parent owns this directory, including cleanup after cancellation.
    with tempfile.TemporaryDirectory(prefix="sihyx_chip_code_") as directory:
        package = Path(directory) / "chiptune"
        package.mkdir()
        for file in Path(source).parent.glob("*.py"):
            shutil.copyfile(file, package / file.name)
        yield [str(python), "-I", str(package / "worker.py")]
