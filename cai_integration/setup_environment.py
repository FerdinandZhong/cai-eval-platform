#!/usr/bin/env python3
"""
Setup Python environment for the CAI Eval Platform on CML.

Adapted from ray-serve-cai/cai_integration/setup_environment.py.
Reuses install_nginx() / is_venv_ready() / run_command() verbatim.

Steps:
  1. Install / verify uv
  2. Create /home/cdsw/.venv (skip if already ready)
  3. Install eval platform deps via uv pip install
  4. Install no-root nginx (~/.local/bin/nginx)
  5. Download tau-bench retail dataset (idempotent)
"""

import fcntl
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

def _repo_root() -> Path:
    # CML runs job scripts in an IPython-style engine where __file__ is not
    # defined. CML clones the repo into /home/cdsw and runs jobs from there,
    # so resolve the working git repo rather than CDSW_PROJECT (which is the
    # project's display name, not a path).
    try:
        return Path(__file__).parent.parent.resolve()
    except NameError:
        for cand in ("/home/cdsw", os.getcwd()):
            if (Path(cand) / ".git").is_dir():
                return Path(cand).resolve()
        return Path("/home/cdsw")


REPO_ROOT = _repo_root()
VENV_DIR = Path(os.environ.get("EVAL_VENV", "/home/cdsw/.venv"))


# ---------------------------------------------------------------------------
# Shared helpers (kept identical to ray-serve-cai for consistency)
# ---------------------------------------------------------------------------

def run_command(cmd, cwd=None):
    print(f"Running: {cmd}")
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=cwd, check=True, capture_output=True, text=True
        )
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {e}")
        if e.stdout:
            print(f"Output: {e.stdout}")
        if e.stderr:
            print(f"Error output: {e.stderr}")
        return False


def is_venv_ready(venv_dir):
    venv_dir = str(venv_dir)
    if not os.path.exists(venv_dir):
        return False
    if not os.path.exists(os.path.join(venv_dir, "bin", "python")):
        return False
    if not os.path.exists(os.path.join(venv_dir, "pyvenv.cfg")):
        return False
    return True


def install_nginx():
    """
    Install nginx without requiring apt/sudo.

    Strategy (tried in order):
      1. Already installed at the expected path — use as-is.
      2. System nginx is on PATH — symlink it.
      3. Compile from source (nginx.org tar.gz, no SSL/PCRE/zlib needed).
    """
    print("\nSetting up Nginx (no-root install)...")

    home = Path.home()
    nginx_bin = str(home / ".local" / "bin" / "nginx")
    os.makedirs(str(home / ".local" / "bin"), exist_ok=True)

    # Step 1: already installed?
    if os.path.exists(nginx_bin):
        result = subprocess.run([nginx_bin, "-v"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  Nginx already installed: {result.stderr.strip()}")
            return True
        print("  Existing nginx binary is broken — reinstalling...")
        os.remove(nginx_bin)

    # Step 2: system nginx on PATH?
    result = subprocess.run(["which", "nginx"], capture_output=True, text=True)
    if result.returncode == 0:
        system_nginx = result.stdout.strip()
        print(f"  System nginx found: {system_nginx}")
        try:
            os.symlink(system_nginx, nginx_bin)
            print(f"  Symlinked to: {nginx_bin}")
            return True
        except OSError as e:
            print(f"  Could not create symlink: {e} — will compile from source")

    # Step 3: compile from source (no SSL, no PCRE, no zlib)
    nginx_version = os.environ.get("NGINX_VERSION", "1.29.7")
    nginx_url = os.environ.get(
        "NGINX_SOURCE_URL",
        f"https://nginx.org/download/nginx-{nginx_version}.tar.gz",
    )
    nginx_prefix = str(home / ".local" / "nginx")

    print(f"  No system nginx — compiling from source (nginx {nginx_version})...")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tar_path = os.path.join(tmpdir, "nginx.tar.gz")
            print(f"  Downloading {nginx_url} ...")
            if not run_command(f"curl -fsSL -o {tar_path} {nginx_url}", cwd=tmpdir):
                return False

            with tarfile.open(tar_path, "r:gz") as tar:
                tar.extractall(path=tmpdir)

            src_dir = os.path.join(tmpdir, f"nginx-{nginx_version}")
            if not os.path.isdir(src_dir):
                print(f"  Source directory not found: {src_dir}")
                return False

            configure_cmd = " ".join([
                "./configure",
                f"--prefix={nginx_prefix}",
                f"--sbin-path={nginx_bin}",
                f"--conf-path={nginx_prefix}/conf/nginx.conf",
                f"--pid-path={nginx_prefix}/run/nginx.pid",
                f"--error-log-path={nginx_prefix}/logs/error.log",
                f"--http-log-path={nginx_prefix}/logs/access.log",
                "--without-http_rewrite_module",
                "--without-http_gzip_module",
                "--without-mail_smtp_module",
                "--without-mail_imap_module",
                "--without-mail_pop3_module",
            ])
            if not run_command(configure_cmd, cwd=src_dir):
                return False
            num_cores = os.cpu_count() or 2
            if not run_command(f"make -j{num_cores}", cwd=src_dir):
                return False
            if not run_command("make install", cwd=src_dir):
                return False

        result = subprocess.run([nginx_bin, "-v"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  Nginx installed: {result.stderr.strip()}")
            return True
        return False
    except Exception as exc:
        import traceback
        print(f"  Exception during nginx compilation: {exc}")
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# Eval-platform-specific setup
# ---------------------------------------------------------------------------

EVAL_PACKAGES = [
    "arize-phoenix>=4.0",
    "opentelemetry-sdk>=1.20",
    "opentelemetry-exporter-otlp-proto-http>=1.20",
    "openinference-instrumentation-openai>=0.1",
    "openai>=1.0",
    "datasets>=2.14",
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "ragas>=0.2",
    "pydantic>=2.0",
    "requests>=2.31",
]


def ensure_uv() -> bool:
    result = subprocess.run(["which", "uv"], capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  uv found: {result.stdout.strip()}")
        return True
    print("  uv not found — installing via pip...")
    return run_command(f"{sys.executable} -m pip install uv --quiet")


def setup_eval_venv() -> bool:
    venv_dir = str(VENV_DIR)
    lock_path = f"{venv_dir}.lock"

    if is_venv_ready(venv_dir):
        print(f"  Venv already ready: {venv_dir}")
        return True

    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if is_venv_ready(venv_dir):
            print(f"  Venv created by another process: {venv_dir}")
            return True

        print(f"  Creating venv at {venv_dir} ...")
        if not run_command(f"uv venv {venv_dir}"):
            return False

        packages_str = " ".join(f'"{p}"' for p in EVAL_PACKAGES)
        print("  Installing eval platform deps ...")
        if not run_command(f"uv pip install --python {venv_dir}/bin/python {packages_str}"):
            return False

        return True
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def download_datasets() -> bool:
    script = REPO_ROOT / "scripts" / "download_tau_bench.py"
    if not script.exists():
        print(f"  WARNING: {script} not found — skipping dataset download")
        return True

    python = str(VENV_DIR / "bin" / "python")
    if not os.path.exists(python):
        python = sys.executable

    print("  Downloading tau-bench retail dataset ...")
    return run_command(f"{python} {script}")


def main() -> None:
    print("=" * 70)
    print("CAI Eval Platform — Environment Setup")
    print("=" * 70)

    steps = [
        ("uv installation",   ensure_uv),
        ("eval venv + deps",  setup_eval_venv),
        ("tau-bench dataset", download_datasets),
    ]

    failed = []
    for label, fn in steps:
        print(f"\n[{label}]")
        if not fn():
            print(f"  FAILED: {label}")
            failed.append(label)

    print("\n" + "=" * 70)
    if failed:
        # CML runs jobs in an IPython engine that treats any SystemExit (even
        # sys.exit(0)) as a job failure, so signal failure by raising and
        # success by returning normally.
        raise RuntimeError(f"Setup completed with failures: {', '.join(failed)}")
    print("Setup completed successfully.")


if __name__ == "__main__":
    main()
