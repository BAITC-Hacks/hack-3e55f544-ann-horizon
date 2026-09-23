"""Create or repair the local Python environment without shell activation."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
ENV_DIR = ROOT / ".venv"
ENV_PYTHON = ENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run_command(*args: str | Path) -> None:
    command = [str(arg) for arg in args]
    print("+ " + subprocess.list2cmdline(command), flush=True)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def check_environment() -> None:
    run_command(ENV_PYTHON, "-m", "pip", "--version")
    run_command(ENV_PYTHON, "-m", "pip", "check")
    run_command(
        ENV_PYTHON,
        "-c",
        "import sys; import numpy; import pandas; import sklearn; "
        "from zoneinfo import ZoneInfo; ZoneInfo('Asia/Almaty'); "
        "print('Python:', sys.version.split()[0]); "
        "print('numpy:', numpy.__version__); "
        "print('pandas:', pandas.__version__); "
        "print('scikit-learn:', sklearn.__version__); "
        "print('Timezone: Asia/Almaty OK')",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Check the existing environment without installing packages"
    )
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required.", file=sys.stderr)
        return 1

    try:
        if not ENV_PYTHON.is_file():
            if args.check:
                raise RuntimeError("Local environment is missing. Run setup.cmd first.")
            if ENV_DIR.exists():
                raise RuntimeError(
                    f"Incomplete environment at {ENV_DIR}. Rename it and run setup again."
                )
            # Separate environment creation from pip bootstrapping so a failed
            # pip installation can be retried without replacing the interpreter.
            run_command(sys.executable, "-m", "venv", "--without-pip", ENV_DIR)

        run_command(
            ENV_PYTHON,
            "-c",
            "import sys; from pathlib import Path; "
            "assert sys.version_info >= (3, 10), 'Python 3.10+ required'; "
            "assert sys.prefix != sys.base_prefix, 'Expected a virtual environment'; "
            "assert Path(sys.prefix).resolve() == Path(sys.argv[1]).resolve(), "
            "'Unexpected virtual environment'",
            ENV_DIR,
        )
        if not args.check:
            pip_probe = subprocess.run(
                [str(ENV_PYTHON), "-m", "pip", "--version"], capture_output=True, cwd=ROOT
            )
            if pip_probe.returncode:
                run_command(ENV_PYTHON, "-m", "ensurepip", "--upgrade", "--default-pip")
            run_command(
                ENV_PYTHON, "-m", "pip", "install", "--disable-pip-version-check",
                "-r", ROOT / "requirements.txt",
            )
        check_environment()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        print(
            "Resolve the error above and rerun setup.cmd. If access is denied to a temporary "
            "directory, run setup in a terminal with permission to use it. "
            "Installing missing packages requires internet access.",
            file=sys.stderr,
        )
        return 1
    print("Environment ready. Run start.cmd (Windows) or .venv/bin/python run.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
