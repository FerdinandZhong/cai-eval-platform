#!/usr/bin/env python3
"""
Create or restart the CML Application(s) for the CAI Eval Platform.

Default (recommended): ONE co-located Application running
cai_integration/start_platform.py — Phoenix + FastAPI behind nginx, with the
backend talking to Phoenix over localhost. No cross-app wiring needed.

Opt-in (--standalone-phoenix): TWO Applications — a standalone Phoenix
(reusable as a shared tracing backend) plus an eval-API-only app, with
PHOENIX_BASE_URL injected into the eval app to point at the Phoenix app.
NOTE: the backend's Phoenix REST calls send no auth headers, so cross-app
REST traffic assumes the Phoenix app is reachable without CML auth.

Usage:
    # External (CI): CML_HOST + CML_API_KEY in env
    python cai_integration/create_applications.py --project-id <project_id>

    # In-project (CML Session/Job): uses workspace creds automatically
    python cai_integration/create_applications.py

    # Standalone Phoenix mode
    python cai_integration/create_applications.py --standalone-phoenix

Credentials (first match wins):
    CML_HOST / CML_API_KEY            — external, e.g. from GitHub Actions
    CDSW_API_URL / CDSW_APIV2_KEY     — injected inside a CML Session/Job
Project id: --project-id, else CDSW_PROJECT_ID (injected in-project).
Optional: RUNTIME_IDENTIFIER
"""

import argparse
import os
import sys
import time
import requests
from typing import Optional


PLATFORM_APP = {
    "name": "CAI Eval Platform",
    "description": "Co-located Phoenix tracing + FastAPI eval API behind nginx",
    "script": "cai_integration/start_platform.py",
    "subdomain": "cai-eval",
    "cpu": 4,
    "memory": 16,
}

PHOENIX_APP = {
    "name": "CAI Eval Platform — Phoenix Tracing",
    "description": "Standalone Phoenix OTEL trace collector and UI",
    "script": "cai_integration/start_phoenix.py",
    "subdomain": "phoenix",
    "cpu": 2,
    "memory": 8,
}

EVAL_APP = {
    "name": "CAI Eval Platform — Eval API",
    "description": "FastAPI evaluation engine for LLMs and agent workflows",
    "script": "cai_integration/start_app.py",
    "subdomain": "eval",
    "cpu": 4,
    "memory": 16,
}


class ApplicationManager:

    def __init__(self):
        # External creds take precedence; fall back to CML workspace-injected
        # creds so the same script runs unchanged inside a CML Session/Job.
        host = (os.environ.get("CML_HOST") or os.environ.get("CDSW_API_URL") or "").rstrip("/")
        self.api_key = (
            os.environ.get("CML_API_KEY") or os.environ.get("CDSW_APIV2_KEY")
        )
        self.runtime_identifier = os.environ.get("RUNTIME_IDENTIFIER")

        if not host or not self.api_key:
            print("Error: Missing CML credentials.")
            print("   Provide CML_HOST + CML_API_KEY (external), or run inside a")
            print("   CML Session/Job where CDSW_API_URL + CDSW_APIV2_KEY are set.")
            sys.exit(1)

        # Normalize to the v2 API base regardless of which var supplied the host.
        for suffix in ("/api/v2", "/api/v1"):
            if host.endswith(suffix):
                host = host[: -len(suffix)]
                break
        self.cml_host = host
        self.api_url = f"{host}/api/v2"
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key.strip()}",
        }

    def make_request(self, method, endpoint, data=None, params=None) -> Optional[dict]:
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        try:
            response = requests.request(
                method=method, url=url, headers=self.headers,
                json=data, params=params, timeout=30,
            )
            if 200 <= response.status_code < 300:
                return response.json() if response.text else {}
            else:
                print(f"   API Error ({response.status_code}): {response.text[:200]}")
                return None
        except Exception as e:
            print(f"   Request error: {e}")
            return None

    def list_applications(self, project_id: str) -> dict:
        result = self.make_request("GET", f"projects/{project_id}/applications")
        if result:
            return {app.get("name", ""): app for app in result.get("applications", [])}
        return {}

    def _app_data(self, app_config: dict, environment: dict = None) -> dict:
        data = {
            "name": app_config["name"],
            "description": app_config.get("description", ""),
            "script": app_config["script"],
            "cpu": app_config.get("cpu", 2),
            "memory": app_config.get("memory", 8),
            "bypass_authentication": False,
        }
        if self.runtime_identifier:
            data["runtime_identifier"] = self.runtime_identifier
        if app_config.get("subdomain"):
            data["subdomain"] = app_config["subdomain"]
        if environment:
            data["environment"] = environment
        return data

    def create_application(self, project_id: str, app_config: dict,
                           environment: dict = None) -> Optional[str]:
        print(f"   Creating application: {app_config['name']}")
        data = self._app_data(app_config, environment)
        result = self.make_request("POST", f"projects/{project_id}/applications", data=data)
        if result:
            app_id = result.get("id")
            print(f"      Created: {app_id}")
            return app_id
        print("      Failed to create application")
        return None

    def update_and_restart_application(self, project_id: str, app_id: str,
                                       app_config: dict,
                                       environment: dict = None) -> bool:
        name = app_config["name"]
        print(f"   Updating application: {name}")
        patch_data = {}
        if environment:
            patch_data["environment"] = environment
        if patch_data:
            result = self.make_request(
                "PATCH", f"projects/{project_id}/applications/{app_id}", data=patch_data
            )
            if result is None:
                print(f"      Failed to patch environment — proceeding to restart anyway")

        print(f"   Restarting application: {name}")
        result = self.make_request(
            "POST", f"projects/{project_id}/applications/{app_id}/restart"
        )
        if result is not None:
            print(f"      Restarted: {app_id}")
            return True
        # Fallback: some CML versions use PATCH to trigger restart
        result = self.make_request(
            "PATCH", f"projects/{project_id}/applications/{app_id}",
            data={"bypass_authentication": False},
        )
        if result is not None:
            print(f"      Restarted via PATCH: {app_id}")
            return True
        print(f"      Failed to restart application")
        return False

    def wait_for_app_running(self, project_id: str, app_id: str,
                             app_name: str, timeout: int = 120) -> bool:
        print(f"   Waiting for {app_name} to reach running status (timeout: {timeout}s)...")
        start = time.time()
        last_status = None
        while time.time() - start < timeout:
            result = self.make_request("GET", f"projects/{project_id}/applications/{app_id}")
            if result:
                status = result.get("status", "unknown").lower()
                if status != last_status:
                    print(f"      [{int(time.time()-start)}s] status: {status}")
                    last_status = status
                if status == "running":
                    return True
                if status in ("failed", "stopped", "error"):
                    print(f"      Application reached terminal status: {status}")
                    return False
            time.sleep(10)
        print(f"      Timed out waiting for {app_name} ({timeout}s)")
        return False

    def deploy_app(self, project_id: str, existing: dict, app_config: dict,
                   environment: dict = None) -> Optional[str]:
        """Create or restart a single application. Returns app_id or None."""
        name = app_config["name"]
        print(f"\n[{name}]")
        if name in existing:
            app_id = existing[name].get("id", "")
            ok = self.update_and_restart_application(
                project_id, app_id, app_config, environment=environment
            )
            return app_id if ok else None
        app_id = self.create_application(project_id, app_config, environment=environment)
        return app_id

    def get_phoenix_base_url(self, project_id: str, app_id: str) -> str:
        """Resolve the Phoenix app's base URL for the eval app to talk to.

        Prefer the internal cluster URL (local_url) to avoid public TLS
        routing; fall back to the public subdomain URL.
        """
        result = self.make_request("GET", f"projects/{project_id}/applications/{app_id}")
        if result:
            local_url = result.get("local_url") or result.get("app_url") or ""
            if local_url:
                print(f"      Phoenix internal base: {local_url.rstrip('/')}")
                return local_url.rstrip("/")
        endpoint = f"{self.cml_host}/ds/applications/{PHOENIX_APP['subdomain']}"
        print(f"      Phoenix public base (fallback): {endpoint}")
        return endpoint

    def run(self, project_id: str, standalone_phoenix: bool = False) -> bool:
        print("=" * 70)
        mode = "standalone Phoenix + eval API" if standalone_phoenix else "co-located (one app)"
        print(f"Create / Restart CML Applications — {mode}")
        print("=" * 70)

        existing = self.list_applications(project_id)
        print(f"Found {len(existing)} existing application(s)")

        if not standalone_phoenix:
            app_id = self.deploy_app(project_id, existing, PLATFORM_APP)
            ok = app_id is not None
            print("\n" + "=" * 70)
            print(f"   [{'OK' if ok else 'FAILED'}] {PLATFORM_APP['name']}")
            print("   Phoenix UI: <app-url>/   |   Eval API: <app-url>/app/")
            print("=" * 70)
            return ok

        # Standalone mode: Phoenix first, then eval API pointed at it.
        phoenix_id = self.deploy_app(project_id, existing, PHOENIX_APP)
        if not phoenix_id:
            print("\nFailed to deploy Phoenix application")
            return False
        if PHOENIX_APP["name"] not in existing:
            self.wait_for_app_running(project_id, phoenix_id, PHOENIX_APP["name"], timeout=120)

        phoenix_base = self.get_phoenix_base_url(project_id, phoenix_id)
        eval_id = self.deploy_app(
            project_id, existing, EVAL_APP,
            environment={"PHOENIX_BASE_URL": phoenix_base},
        )
        eval_ok = eval_id is not None

        print("\n" + "=" * 70)
        print(f"   [OK] {PHOENIX_APP['name']}")
        print(f"   [{'OK' if eval_ok else 'FAILED'}] {EVAL_APP['name']}")
        if eval_ok:
            print(f"   PHOENIX_BASE_URL wired: {phoenix_base}")
            print("   NOTE: backend Phoenix REST calls send no auth — the eval app must")
            print("   be able to reach the Phoenix app without CML auth for this to work.")
        print("=" * 70)
        return eval_ok


def main():
    parser = argparse.ArgumentParser(
        description="Create or restart CML Application(s) for the CAI Eval Platform"
    )
    parser.add_argument(
        "--project-id",
        default=os.environ.get("CDSW_PROJECT_ID"),
        help="CML project ID (defaults to CDSW_PROJECT_ID when run in-project)",
    )
    parser.add_argument(
        "--standalone-phoenix",
        action="store_true",
        help="Deploy Phoenix and the eval API as two separate apps instead of one",
    )
    args = parser.parse_args()

    if not args.project_id:
        print("Error: project id not provided and CDSW_PROJECT_ID not set.")
        print("   Pass --project-id <id>, or run inside a CML Session/Job.")
        sys.exit(1)

    try:
        manager = ApplicationManager()
        ok = manager.run(args.project_id, standalone_phoenix=args.standalone_phoenix)
        sys.exit(0 if ok else 1)
    except KeyboardInterrupt:
        print("\nCancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
