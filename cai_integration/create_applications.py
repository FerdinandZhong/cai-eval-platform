#!/usr/bin/env python3
"""
Create or restart CML Applications for the CAI Eval Platform.

Creates two persistent CML Applications in order:
  1. Phoenix Tracing  — cai_integration/start_phoenix.py
  2. Eval Platform    — cai_integration/launch_app_job.py

After Phoenix starts, its internal endpoint is resolved and injected as
PHOENIX_COLLECTOR_ENDPOINT into the Eval API application so tracing is
wired up automatically without any manual step.

Usage:
    python cai_integration/create_applications.py --project-id <project_id>

Required env vars: CML_HOST, CML_API_KEY
Optional env vars: RUNTIME_IDENTIFIER
"""

import argparse
import os
import sys
import time
import requests
from typing import Optional


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
    "script": "cai_integration/launch_app_job.py",
    "subdomain": "eval",
    "cpu": 4,
    "memory": 16,
}


class ApplicationManager:

    def __init__(self):
        self.cml_host = os.environ.get("CML_HOST", "").rstrip("/")
        self.api_key = os.environ.get("CML_API_KEY")
        self.runtime_identifier = os.environ.get("RUNTIME_IDENTIFIER")

        if not all([self.cml_host, self.api_key]):
            print("Error: Missing required environment variables")
            print("   Required: CML_HOST, CML_API_KEY")
            sys.exit(1)

        self.api_url = f"{self.cml_host}/api/v2"
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

    def get_phoenix_collector_endpoint(self, project_id: str,
                                       app_id: str) -> str:
        """
        Try to get Phoenix's internal cluster URL so the Eval API can talk to
        it directly without going through the public load balancer.

        CML API v2 may return a 'local_url' field on the application object
        (internal pod/service URL, e.g. http://<pod-ip>:8080). Fall back to
        constructing the public URL from CML_HOST + subdomain if absent.
        """
        result = self.make_request("GET", f"projects/{project_id}/applications/{app_id}")
        if result:
            # Prefer internal cluster URL to avoid public TLS routing
            local_url = result.get("local_url") or result.get("app_url") or ""
            if local_url:
                endpoint = local_url.rstrip("/") + "/v1/traces"
                print(f"      Phoenix internal endpoint: {endpoint}")
                return endpoint

        # Fallback: public URL via subdomain
        endpoint = f"{self.cml_host}/ds/applications/phoenix/v1/traces"
        print(f"      Phoenix public endpoint (fallback): {endpoint}")
        return endpoint

    def deploy_phoenix(self, project_id: str, existing: dict) -> Optional[tuple]:
        """Create or restart Phoenix. Returns (app_id, collector_endpoint) or None."""
        name = PHOENIX_APP["name"]
        print(f"\n[{name}]")

        if name in existing:
            app_id = existing[name].get("id", "")
            ok = self.update_and_restart_application(project_id, app_id, PHOENIX_APP)
        else:
            app_id = self.create_application(project_id, PHOENIX_APP)
            ok = app_id is not None

        if not ok or not app_id:
            return None

        running = self.wait_for_app_running(project_id, app_id, name, timeout=120)
        if not running:
            print(f"      WARNING: Phoenix did not reach running state — "
                  "collector endpoint may not be reachable yet")

        endpoint = self.get_phoenix_collector_endpoint(project_id, app_id)
        return app_id, endpoint

    def deploy_eval_api(self, project_id: str, existing: dict,
                        collector_endpoint: str) -> bool:
        """Create or restart the Eval API, injecting the Phoenix endpoint."""
        name = EVAL_APP["name"]
        print(f"\n[{name}]")
        print(f"   PHOENIX_COLLECTOR_ENDPOINT: {collector_endpoint}")

        environment = {"PHOENIX_COLLECTOR_ENDPOINT": collector_endpoint}

        if name in existing:
            app_id = existing[name].get("id", "")
            return self.update_and_restart_application(
                project_id, app_id, EVAL_APP, environment=environment
            )
        else:
            app_id = self.create_application(project_id, EVAL_APP, environment=environment)
            return app_id is not None

    def run(self, project_id: str) -> bool:
        print("=" * 70)
        print("Create / Restart CML Applications — CAI Eval Platform")
        print("=" * 70)

        existing = self.list_applications(project_id)
        print(f"Found {len(existing)} existing application(s)\n")

        # Step 1: Phoenix — must come first so we can resolve its endpoint
        phoenix_result = self.deploy_phoenix(project_id, existing)
        if phoenix_result is None:
            print("\nFailed to deploy Phoenix application")
            return False
        _, collector_endpoint = phoenix_result

        # Step 2: Eval API — wired to Phoenix automatically
        eval_ok = self.deploy_eval_api(project_id, existing, collector_endpoint)

        print("\n" + "=" * 70)
        print("Applications Summary:")
        print(f"   [{'OK' if phoenix_result else 'FAILED'}] {PHOENIX_APP['name']}")
        print(f"   [{'OK' if eval_ok else 'FAILED'}] {EVAL_APP['name']}")
        if eval_ok:
            print(f"\n   PHOENIX_COLLECTOR_ENDPOINT auto-wired: {collector_endpoint}")
        print("=" * 70)
        return eval_ok


def main():
    parser = argparse.ArgumentParser(
        description="Create or restart CML Applications for the CAI Eval Platform"
    )
    parser.add_argument("--project-id", required=True, help="CML project ID")
    args = parser.parse_args()

    try:
        manager = ApplicationManager()
        sys.exit(0 if manager.run(args.project_id) else 1)
    except KeyboardInterrupt:
        print("\nCancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
