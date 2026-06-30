#!/usr/bin/env python3
"""
Co-located CML Application entry point for the CAI Eval Platform.

Runs the full stack inside ONE CML Application:

    nginx (CDSW_APP_PORT)
      ├── /      -> Phoenix UI / REST  (127.0.0.1:6006)
      └── /app/  -> FastAPI eval API   (127.0.0.1:9000)

CML routes external traffic to a single port per Application (CDSW_APP_PORT),
so nginx multiplexes the two components behind it. Phoenix and the eval API
both bind to localhost only; only nginx is publicly reachable.

The backend talks to Phoenix over localhost (PHOENIX_BASE_URL), which is where
backend/tracing.py and backend/phoenix_client.py expect it by default.

Ported from docker/entrypoint.sh, adapted for the CML IPython engine:
  - __file__ is not defined          -> resolve repo root from cwd
  - __name__ is never "__main__"     -> call main() unconditionally
  - process replacement (os.execv)   -> blocking subprocess.run (stays alive)
  - SystemExit is treated as a crash -> raise on failure, never sys.exit()

Env vars:
  CDSW_APP_PORT  external port CML assigns                  (default: 8080)
  PHOENIX_PORT   internal Phoenix port                      (default: 6006)
  MANAGER_PORT   internal FastAPI port                      (default: 9000)
  DATA_DIR       persistent storage root                    (default: /home/cdsw/cai-eval-data)
"""

import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

APP_PORT = int(os.environ.get("CDSW_APP_PORT", 8080))
PHOENIX_PORT = int(os.environ.get("PHOENIX_PORT", 6006))
MANAGER_PORT = int(os.environ.get("MANAGER_PORT", 9000))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/home/cdsw/cai-eval-data"))
NGINX_RUNTIME_DIR = Path("/tmp/nginx")


def _repo_root() -> Path:
    # CML runs application scripts in an IPython engine where __file__ is not
    # defined. CML clones the repo into /home/cdsw and runs from there.
    try:
        return Path(__file__).parent.parent.resolve()
    except NameError:
        for cand in ("/home/cdsw", os.getcwd()):
            if (Path(cand) / ".git").is_dir():
                return Path(cand).resolve()
        return Path("/home/cdsw")


REPO_ROOT = _repo_root()


def find_phoenix() -> str:
    venv_phoenix = Path("/home/cdsw/.venv/bin/phoenix")
    if venv_phoenix.is_file() and os.access(str(venv_phoenix), os.X_OK):
        return str(venv_phoenix)
    found = shutil.which("phoenix")
    if found:
        return found
    raise RuntimeError(
        "phoenix binary not found. Run cai_integration/setup_environment.py first."
    )


def find_nginx() -> str:
    # Verify candidates by actually running nginx -v, not just checking the path.
    # The home nginx may be a symlink created by setup_environment.install_nginx()
    # that points to a system path not present in this container image.
    candidates = [
        str(Path.home() / ".local" / "bin" / "nginx"),
        "/usr/sbin/nginx",
        "/usr/bin/nginx",
        "/usr/local/sbin/nginx",
    ]
    found = shutil.which("nginx")
    if found and found not in candidates:
        candidates.append(found)
    for cand in candidates:
        try:
            r = subprocess.run([cand, "-v"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return cand
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError(
        "nginx not found. Run cai_integration/setup_environment.py first."
    )


def venv_python() -> str:
    venv_python = Path("/home/cdsw/.venv/bin/python")
    return str(venv_python) if venv_python.exists() else "python3"


def _wait_ready(url: str, name: str, attempts: int, delay: float) -> bool:
    for i in range(attempts):
        try:
            urllib.request.urlopen(url, timeout=2)
            print(f"   {name} ready ({int(i * delay)}s)")
            return True
        except Exception:
            time.sleep(delay)
    print(f"   WARNING: {name} not ready after {int(attempts * delay)}s — continuing")
    return False


def _mime_types() -> str:
    for cand in ("/etc/nginx/mime.types", "/usr/share/nginx/mime.types"):
        if os.path.isfile(cand):
            return cand
    # Compiled-from-source nginx (setup_environment.py) keeps conf under ~/.local/nginx
    home_mime = Path.home() / ".local" / "nginx" / "conf" / "mime.types"
    if home_mime.is_file():
        return str(home_mime)
    return ""


def write_nginx_conf() -> Path:
    (NGINX_RUNTIME_DIR / "logs").mkdir(parents=True, exist_ok=True)
    (NGINX_RUNTIME_DIR / "run").mkdir(parents=True, exist_ok=True)

    mime = _mime_types()
    mime_line = f"    include      {mime};\n" if mime else ""

    conf = f"""worker_processes auto;
error_log  {NGINX_RUNTIME_DIR}/logs/error.log warn;
pid        {NGINX_RUNTIME_DIR}/run/nginx.pid;

events {{ worker_connections 1024; }}

http {{
{mime_line}    default_type application/octet-stream;
    sendfile          on;
    keepalive_timeout 65;
    proxy_read_timeout    600;
    proxy_send_timeout    600;
    proxy_connect_timeout  10;

    server {{
        listen      127.0.0.1:{APP_PORT};
        server_name _;

        location /app/ {{
            proxy_pass         http://127.0.0.1:{MANAGER_PORT}/;
            proxy_set_header   Host $host;
            proxy_set_header   X-Real-IP $remote_addr;
            proxy_buffering    off;
            proxy_cache        off;
        }}

        location / {{
            proxy_pass         http://127.0.0.1:{PHOENIX_PORT};
            proxy_set_header   Host $host;
            proxy_set_header   X-Real-IP $remote_addr;
            proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header   Upgrade $http_upgrade;
            proxy_set_header   Connection "upgrade";
            proxy_buffering    off;
            proxy_cache        off;
        }}
    }}
}}
"""
    conf_path = NGINX_RUNTIME_DIR / "nginx.conf"
    conf_path.write_text(conf)
    return conf_path


def main() -> None:
    print("=" * 70)
    print("CAI Eval Platform — Co-located Application")
    print(f"  CDSW_APP_PORT : {APP_PORT}  (nginx, public)")
    print(f"  PHOENIX_PORT  : {PHOENIX_PORT}  (127.0.0.1, internal)")
    print(f"  MANAGER_PORT  : {MANAGER_PORT}  (127.0.0.1, internal)")
    print(f"  DATA_DIR      : {DATA_DIR}")
    print(f"  REPO_ROOT     : {REPO_ROOT}")
    print("=" * 70)

    backend_dir = REPO_ROOT / "backend"
    if not (backend_dir / "main.py").exists():
        raise RuntimeError(f"backend/main.py not found at {backend_dir}")

    phoenix_working_dir = DATA_DIR / "phoenix"
    phoenix_working_dir.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Phoenix on localhost
    phoenix_bin = find_phoenix()
    phoenix_env = dict(os.environ)
    phoenix_env["PHOENIX_WORKING_DIR"] = str(phoenix_working_dir)
    print(f"\n[1/3] starting Phoenix: {phoenix_bin} serve --port {PHOENIX_PORT} --host 127.0.0.1")
    phoenix_proc = subprocess.Popen(
        [phoenix_bin, "serve", "--port", str(PHOENIX_PORT), "--host", "127.0.0.1"],
        env=phoenix_env,
    )
    _wait_ready(f"http://127.0.0.1:{PHOENIX_PORT}/healthz", "Phoenix", attempts=120, delay=0.5)

    # 2. FastAPI eval API on localhost — talks to Phoenix over localhost.
    api_env = dict(os.environ)
    api_env["PHOENIX_BASE_URL"] = f"http://127.0.0.1:{PHOENIX_PORT}"
    api_env["DATA_DIR"] = str(DATA_DIR)
    api_env["DATASETS_DIR"] = str(REPO_ROOT / "backend" / "datasets")
    print(f"\n[2/3] starting eval API: uvicorn main:app on 127.0.0.1:{MANAGER_PORT}")
    api_proc = subprocess.Popen(
        [venv_python(), "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", str(MANAGER_PORT)],
        cwd=str(backend_dir),
        env=api_env,
    )
    _wait_ready(f"http://127.0.0.1:{MANAGER_PORT}/api/health", "eval API", attempts=60, delay=0.5)

    # 3. nginx in the foreground — keeps the Application alive; CML's health
    #    check on CDSW_APP_PORT hits nginx.
    nginx_bin = find_nginx()
    conf_path = write_nginx_conf()
    print(f"\n[3/3] starting nginx: {nginx_bin} -c {conf_path} (foreground)")
    print(f"\n  Phoenix : <app-url>/")
    print(f"  Eval App: <app-url>/app/")
    print(f"  Health  : <app-url>/app/api/health")
    print("=" * 70)

    try:
        result = subprocess.run(
            [nginx_bin, "-c", str(conf_path), "-g", "daemon off;"],
        )
        if result.returncode != 0:
            raise RuntimeError(f"nginx exited with code {result.returncode}")
    finally:
        for proc in (api_proc, phoenix_proc):
            try:
                proc.terminate()
            except Exception:
                pass


# CML runs application scripts in an IPython engine where __name__ is NOT
# "__main__", so call unconditionally.
main()
