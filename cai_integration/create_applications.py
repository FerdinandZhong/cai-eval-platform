#!/usr/bin/env python3
"""
Create or restart CML Applications for the CAI Eval Platform.

Creates two persistent CML Applications:
  1. Phoenix Tracing  — cai_integration/start_phoenix.py
  2. Eval Platform    — cai_integration/launch_app_job.py

Called by the GitHub Actions workflow after setup_eval_env completes.

Usage:
    python cai_integration/create_applications.py --project-id <project_id>

Required env vars: CML_HOST, CML_API_KEY
Optional env vars: RUNTIME_IDENTIFIER
"""

import argparse
import os
import sys
import requests
from typing import Optional


APPLICATIONS = [
    {
        "name": "CAI Eval Platform — Phoenix Tracing",
        "description": "Standalone Phoenix OTEL trace collector and UI",
        "script": "cai_integration/start_phoenix.py",
        "subdomain": "phoenix",
        "cpu": 2,
        "memory": 8,
    },
    {
        "name": "CAI Eval Platform — Eval API",
        "description": "FastAPI evaluation engine for LLMs and agent workflows",
        "script": "cai_integration/launch_app_job.py",
        "subdomain": "eval",
        "cpu": 4,
        "memory": 16,
    },
]


class ApplicationManager:

    def __init__(self):
        self.cml_host = os.environ.get("CML_HOST")
        self.api_key = os.environ.get("CML_API_KEY")
        self.runtime_identifier = os.environ.get("RUNTIME_IDENTIFIER")

        if not all([self.cml_host, self.api_key]):
            print("Error: Missing required environment variables")
            print("   Required: CML_HOST, CML_API_KEY")
            sys.exit(1)

        self.api_url = f"{self.cml_host.rstrip('/')}/api/v2"
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

    def create_application(self, project_id: str, app_config: dict) -> Optional[str]:
        print(f"   Creating application: {app_config['name']}")
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

        result = self.make_request("POST", f"projects/{project_id}/applications", data=data)
        if result:
            app_id = result.get("id")
            print(f"      Created: {app_id}")
            return app_id
        print("      Failed to create application")
        return None

    def restart_application(self, project_id: str, app_id: str, app_name: str) -> bool:
        print(f"   Restarting application: {app_name}")
        # PATCH with the same config restarts the app on CML
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

    def run(self, project_id: str) -> bool:
        print("=" * 70)
        print("Create / Restart CML Applications — CAI Eval Platform")
        print("=" * 70)

        existing = self.list_applications(project_id)
        print(f"Found {len(existing)} existing application(s)")

        results = []
        for app_config in APPLICATIONS:
            name = app_config["name"]
            print(f"\n[{name}]")

            if name in existing:
                app_id = existing[name].get("id", "")
                ok = self.restart_application(project_id, app_id, name)
            else:
                app_id = self.create_application(project_id, app_config)
                ok = app_id is not None

            results.append((name, ok))

        print("\n" + "=" * 70)
        print("Applications Summary:")
        all_ok = True
        for name, ok in results:
            status = "OK" if ok else "FAILED"
            print(f"   [{status}] {name}")
            if not ok:
                all_ok = False

        if not all_ok:
            print("\nNote: Set PHOENIX_COLLECTOR_ENDPOINT on the Eval API application")
            print("to <phoenix-app-url>/v1/traces to enable tracing.")
            return False

        print("\nNote: Set PHOENIX_COLLECTOR_ENDPOINT on the Eval API application")
        print("to <phoenix-app-url>/v1/traces to enable tracing.")
        print("=" * 70)
        return True


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
