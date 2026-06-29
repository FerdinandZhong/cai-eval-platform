#!/usr/bin/env python3
"""
Trigger the git_sync root job and monitor it to completion.

CML's parent-child job chain handles the rest autonomously:
  git_sync  →  (CML auto-triggers)  setup_eval_env

This script only triggers and waits for git_sync.  setup_eval_env fires
on its own when git_sync succeeds; there is no need to trigger or monitor
it from outside CML.

Usage:
    python cai_integration/trigger_jobs.py --project-id <project_id>

Required env vars: CML_HOST, CML_API_KEY
"""

import argparse
import os
import sys
import time
import requests
from typing import Optional

ROOT_JOB_NAME = "Git Repository Sync"
ROOT_JOB_TIMEOUT = 300   # git fetch + reset; should finish in < 2 min


class JobTrigger:

    def __init__(self):
        self.cml_host = os.environ.get("CML_HOST")
        self.api_key = os.environ.get("CML_API_KEY")

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
            print(f"API Error ({response.status_code}): {response.text[:200]}")
            return None
        except Exception as e:
            print(f"Request error: {e}")
            return None

    def find_job_id(self, project_id: str, job_name: str) -> Optional[str]:
        result = self.make_request("GET", f"projects/{project_id}/jobs")
        if result:
            for job in result.get("jobs", []):
                if job.get("name") == job_name:
                    return job.get("id")
        return None

    def trigger_job(self, project_id: str, job_id: str) -> Optional[str]:
        result = self.make_request("POST", f"projects/{project_id}/jobs/{job_id}/runs")
        return result.get("id") if result else None

    def wait_for_job_completion(self, project_id: str, job_id: str,
                                run_id: str, timeout: int) -> bool:
        print(f"   Waiting for job to complete (timeout: {timeout}s)...")
        start = time.time()
        last_status = None

        while time.time() - start < timeout:
            result = self.make_request(
                "GET", f"projects/{project_id}/jobs/{job_id}/runs/{run_id}"
            )
            if result:
                status = result.get("status", "unknown").lower()
                if status != last_status:
                    print(f"      [{int(time.time() - start)}s] Status: {status}")
                    last_status = status
                if status in ("succeeded", "success", "engine_succeeded"):
                    print("   Job completed successfully")
                    return True
                if status in ("failed", "error", "engine_failed", "killed", "stopped", "timedout"):
                    print(f"   Job failed with status: {status}")
                    return False
            time.sleep(10)

        print(f"   Job timeout ({int(time.time() - start)}s / {timeout}s)")
        return False

    def run(self, project_id: str) -> bool:
        print("=" * 70)
        print(f"Triggering root job: {ROOT_JOB_NAME}")
        print("(CML will auto-trigger Setup Eval Environment when this succeeds)")
        print("=" * 70)

        job_id = self.find_job_id(project_id, ROOT_JOB_NAME)
        if not job_id:
            print(f"Job not found: {ROOT_JOB_NAME}")
            print("   Run the create-jobs step first.")
            return False
        print(f"   Job ID: {job_id}")

        run_id = self.trigger_job(project_id, job_id)
        if not run_id:
            print("   Failed to trigger job")
            return False
        print(f"   Run ID: {run_id}\n")

        if not self.wait_for_job_completion(project_id, job_id, run_id, ROOT_JOB_TIMEOUT):
            print(f"{ROOT_JOB_NAME} failed")
            return False

        print("=" * 70)
        print(f"{ROOT_JOB_NAME} complete.")
        print("Setup Eval Environment is now running autonomously in CML.")
        print("=" * 70)
        return True


def main():
    parser = argparse.ArgumentParser(
        description="Trigger the git_sync root job; CML handles the rest"
    )
    parser.add_argument("--project-id", required=True, help="CML project ID")
    args = parser.parse_args()

    try:
        trigger = JobTrigger()
        sys.exit(0 if trigger.run(args.project_id) else 1)
    except KeyboardInterrupt:
        print("\nCancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
