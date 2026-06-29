#!/usr/bin/env python3
"""
Trigger and monitor CML jobs for CAI Eval Platform deployment.

Adapted from ray-serve-cai/cai_integration/trigger_jobs.py.
No project-specific changes — fully generic; reads jobs_config.yaml
to determine execution order and job names.

Usage:
    python cai_integration/trigger_jobs.py \
        --project-id <project_id> \
        --jobs-config cai_integration/jobs_config.yaml

Required env vars: CML_HOST, CML_API_KEY
Optional env vars: FORCE_REBUILD=true (rerun all jobs regardless of prior success)
"""

import argparse
import json
import os
import sys
import time
import requests
from typing import Dict, List, Optional


class JobTrigger:

    def __init__(self):
        self.cml_host = os.environ.get("CML_HOST")
        self.api_key = os.environ.get("CML_API_KEY")
        self.force_rebuild = os.environ.get("FORCE_REBUILD", "").lower() == "true"

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
                print(f"API Error ({response.status_code}): {response.text[:200]}")
                return None
        except Exception as e:
            print(f"Request error: {e}")
            return None

    def get_job_ids_by_name(self, project_id: str, job_names: dict) -> Dict[str, str]:
        print("Looking up job IDs from CML...")
        result = self.make_request("GET", f"projects/{project_id}/jobs")
        if not result:
            print("Failed to list jobs")
            return {}

        job_id_map = {
            job.get("name", ""): job.get("id", "")
            for job in result.get("jobs", [])
            if job.get("name") and job.get("id")
        }

        job_ids = {}
        for key, name in job_names.items():
            if name in job_id_map:
                job_ids[key] = job_id_map[name]
                print(f"   Found {key}: {job_id_map[name]}")
            else:
                print(f"   Not found: {name}")

        return job_ids

    def job_succeeded_recently(self, project_id: str, job_id: str) -> bool:
        result = self.make_request(
            "GET", f"projects/{project_id}/jobs/{job_id}/runs", params={"page_size": 5}
        )
        if result:
            runs = result.get("runs", [])
            if runs and runs[0].get("status", "").lower() in ["succeeded", "success"]:
                return True
        return False

    def trigger_job(self, project_id: str, job_id: str) -> Optional[str]:
        result = self.make_request("POST", f"projects/{project_id}/jobs/{job_id}/runs")
        return result.get("id") if result else None

    def get_latest_run(self, project_id: str, job_id: str,
                       retries: int = 6, delay: float = 5.0) -> Optional[dict]:
        """Return the most recent run record regardless of status.

        CML marks a job "already active" before the run record is visible in
        the runs list API.  Retry a few times to let the record appear.
        """
        for attempt in range(retries):
            result = self.make_request(
                "GET", f"projects/{project_id}/jobs/{job_id}/runs", params={"page_size": 5}
            )
            if result:
                runs = result.get("runs", [])
                if runs:
                    return runs[0]
            if attempt < retries - 1:
                print(f"   Run record not yet visible — retrying in {delay:.0f}s "
                      f"({attempt + 1}/{retries - 1})")
                time.sleep(delay)
        return None

    def trigger_or_attach(self, project_id: str, job_id: str) -> Optional[str]:
        """Trigger a new run, or attach to an already-running/completed run.

        When a job has parent_job_id set, CML auto-triggers it the moment the
        parent succeeds. We may arrive here before OR after that happens:
          - Before: explicit trigger succeeds normally.
          - During: 400 "already active" → find and monitor the running run.
          - After:  400 "already active" AND no active run found (finished very
                    fast) → return the latest run_id so wait_for_job_completion
                    can confirm it succeeded.
        """
        url = f"{self.api_url}/projects/{project_id}/jobs/{job_id}/runs"
        try:
            response = requests.post(url, headers=self.headers, json={}, timeout=30)
            if 200 <= response.status_code < 300:
                return response.json().get("id")
            if response.status_code == 400 and "already active" in response.text:
                print("   Job already running (CML auto-triggered) — attaching to active run")
                run = self.get_latest_run(project_id, job_id)
                if run:
                    run_id = run.get("id")
                    status = run.get("status", "").lower()
                    print(f"   Attached to run: {run_id} (status: {status})")
                    return run_id
                print("   No run found for already-active job")
                return None
            print(f"   API Error ({response.status_code}): {response.text[:200]}")
            return None
        except Exception as e:
            print(f"   Request error: {e}")
            return None

    def wait_for_job_completion(self, project_id, job_id, run_id, timeout=1800) -> bool:
        print(f"   Waiting for job to complete (timeout: {timeout}s)...")
        start_time = time.time()
        last_status = None

        while time.time() - start_time < timeout:
            result = self.make_request(
                "GET", f"projects/{project_id}/jobs/{job_id}/runs/{run_id}"
            )
            if result:
                status = result.get("status", "unknown").lower()
                if status != last_status:
                    print(f"      [{int(time.time() - start_time)}s] Status: {status}")
                    last_status = status
                if status in ["succeeded", "success", "engine_succeeded"]:
                    print("   Job completed successfully")
                    return True
                elif status in ["failed", "error", "engine_failed", "killed", "stopped", "timedout"]:
                    print(f"   Job failed with status: {status}")
                    return False
            time.sleep(10)

        print(f"   Job timeout ({int(time.time() - start_time)}s / {timeout}s)")
        return False

    def _topological_order(self, job_configs: Dict) -> List[str]:
        jobs = job_configs.get("jobs", {})
        order: List[str] = []
        remaining = set(jobs.keys())

        while remaining:
            ready = sorted(
                k for k in remaining
                if jobs[k].get("parent_job_key") is None
                or jobs[k].get("parent_job_key") not in remaining
            )
            if not ready:
                order.extend(sorted(remaining))
                break
            order.extend(ready)
            remaining -= set(ready)

        return order

    def run(self, project_id: str, job_ids: Dict[str, str], job_configs: Dict) -> bool:
        print("=" * 70)
        print("Trigger CAI Eval Platform Deployment")
        print("=" * 70)
        print(f"   Force rebuild: {'ENABLED' if self.force_rebuild else 'DISABLED'}\n")

        ordered_keys = self._topological_order(job_configs)
        jobs = job_configs.get("jobs", {})

        root_job_key = ordered_keys[0] if ordered_keys else None
        if not root_job_key or root_job_key not in job_ids:
            print("Root job not found")
            return False

        root_job_id = job_ids[root_job_key]
        root_job_config = jobs.get(root_job_key, {})
        root_job_name = root_job_config.get("name", root_job_key)
        trigger_epoch = time.time()

        # Always trigger the root job — skipping it leaves trigger_epoch in the
        # past and _wait_for_new_run hangs waiting for a child run that was
        # never spawned (CML only auto-triggers children when parent actually runs).
        print(f"Triggering root job: {root_job_name}")
        run_id = self.trigger_job(project_id, root_job_id)
        if not run_id:
            print("   Failed to trigger root job")
            return False
        print(f"   Root job triggered: {run_id}\n")
        trigger_epoch = time.time()
        timeout = root_job_config.get("timeout", 600)
        if not self.wait_for_job_completion(project_id, root_job_id, run_id, timeout):
            print(f"Root job failed: {root_job_name}")
            return False
        print(f"{root_job_name} complete\n")

        for job_key in ordered_keys[1:]:
            job_id = job_ids.get(job_key)
            if not job_id:
                print(f"No job_id for '{job_key}' — skipping")
                continue

            job_config = jobs.get(job_key, {})
            job_name = job_config.get("name", job_key)
            timeout = job_config.get("timeout", 1800)
            has_parent = bool(job_config.get("parent_job_key"))

            if has_parent:
                # CML auto-triggers this job when its parent succeeds.
                # Don't try to trigger it explicitly — just wait for the
                # run that CML is already starting (or has just started).
                print(f"Waiting for CML-auto-triggered: {job_name}")
                run_id = self.get_latest_run(project_id, job_id)
                if not run_id:
                    print(f"   No run found for {job_name} after retries")
                    return False
                run_id = run_id.get("id") if isinstance(run_id, dict) else run_id
            else:
                print(f"Triggering: {job_name}")
                run_id = self.trigger_or_attach(project_id, job_id)
                if not run_id:
                    print(f"   Failed to trigger {job_name}")
                    return False

            print(f"   Monitoring run: {run_id}")
            if not self.wait_for_job_completion(project_id, job_id, run_id, timeout):
                print(f"{job_name} failed")
                return False
            print(f"{job_name} complete\n")

        print("=" * 70)
        print("Full deployment chain complete!")
        print("=" * 70)
        return True


def main():
    parser = argparse.ArgumentParser(description="Trigger and monitor CML jobs")
    parser.add_argument("--project-id", required=True, help="CML project ID")
    parser.add_argument(
        "--jobs-config",
        default="cai_integration/jobs_config.yaml",
        help="Path to jobs config YAML",
    )
    args = parser.parse_args()

    try:
        import yaml
        with open(args.jobs_config) as f:
            job_configs = yaml.safe_load(f)

        trigger = JobTrigger()
        job_names = {
            key: config["name"]
            for key, config in job_configs.get("jobs", {}).items()
        }
        job_ids = trigger.get_job_ids_by_name(args.project_id, job_names)
        if not job_ids:
            print("No jobs found in project")
            sys.exit(1)

        sys.exit(0 if trigger.run(args.project_id, job_ids, job_configs) else 1)
    except KeyboardInterrupt:
        print("\nJob execution cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
