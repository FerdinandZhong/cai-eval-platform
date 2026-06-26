#!/usr/bin/env python3
"""
Create/update CML jobs from cai_integration/jobs_config.yaml.

Adapted from ray-serve-cai/cai_integration/create_jobs.py.
No project-specific changes needed — reads jobs_config.yaml from
the same directory as this script.

Usage:
    python cai_integration/create_jobs.py --project-id <project_id>

Required env vars: CML_HOST, CML_API_KEY
Optional env vars: RUNTIME_IDENTIFIER (overrides config lookup)
"""

import argparse
import json
import os
import sys
import yaml
import requests
from pathlib import Path
from typing import Dict, Optional, Any


class JobManager:

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
            else:
                print(f"API Error ({response.status_code}): {response.text[:200]}")
                return None
        except Exception as e:
            print(f"Request error: {e}")
            return None

    def load_jobs_config(self) -> Dict[str, Any]:
        config_path = Path(__file__).parent / "jobs_config.yaml"
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
            print(f"Loaded jobs config from {config_path}")
            return config
        except Exception as e:
            print(f"Failed to load jobs config: {e}")
            return {}

    def get_runtime_identifier(self) -> Optional[str]:
        runtime_id = os.environ.get("RUNTIME_IDENTIFIER")
        if runtime_id:
            print(f"Using runtime from environment: {runtime_id[:80]}...")
            return runtime_id
        print("No RUNTIME_IDENTIFIER set — jobs may fail to create on ML Runtime projects")
        return None

    def list_jobs(self, project_id: str) -> Dict[str, str]:
        print("Listing existing jobs...")
        result = self.make_request("GET", f"projects/{project_id}/jobs")
        if result:
            jobs = {job.get("name", ""): job.get("id", "") for job in result.get("jobs", [])}
            print(f"   Found {len(jobs)} existing jobs")
            return jobs
        print("   No existing jobs found")
        return {}

    def create_job(self, project_id, job_config, parent_job_id=None, runtime_identifier=None) -> Optional[str]:
        print(f"   Creating job: {job_config['name']}")
        job_data = {
            "name": job_config["name"],
            "script": job_config["script"],
            "cpu": job_config.get("cpu", 4),
            "memory": job_config.get("memory", 16),
            "timeout": job_config.get("timeout", 600),
        }
        if runtime_identifier:
            job_data["runtime_identifier"] = runtime_identifier
        if parent_job_id:
            job_data["parent_job_id"] = parent_job_id

        result = self.make_request("POST", f"projects/{project_id}/jobs", data=job_data)
        if result:
            job_id = result.get("id")
            print(f"      Created: {job_id}")
            return job_id
        print("      Failed to create job")
        return None

    def update_job(self, project_id, job_id, job_config, runtime_identifier=None,
                   parent_job_id=None) -> bool:
        print(f"   Updating job: {job_config['name']}")
        job_data = {
            "name": job_config["name"],
            "script": job_config["script"],
            "cpu": job_config.get("cpu", 4),
            "memory": job_config.get("memory", 16),
            "timeout": job_config.get("timeout", 600),
        }
        if runtime_identifier:
            job_data["runtime_identifier"] = runtime_identifier
        if parent_job_id:
            job_data["parent_job_id"] = parent_job_id

        result = self.make_request("PATCH", f"projects/{project_id}/jobs/{job_id}", data=job_data)
        if result is not None:
            print(f"      Updated: {job_id}")
            return True
        print("      Failed to update job")
        return False

    def create_or_update_jobs(self, project_id, jobs_config) -> Dict[str, str]:
        print("\nCreating/Updating Jobs")
        print("-" * 70)

        runtime_identifier = self.get_runtime_identifier()
        job_ids = {}
        self.failed_jobs = []
        existing_jobs = self.list_jobs(project_id)

        for job_key, job_config in jobs_config.get("jobs", {}).items():
            job_name = job_config["name"]
            parent_job_id = None
            parent_key = job_config.get("parent_job_key")
            if parent_key and parent_key in job_ids:
                parent_job_id = job_ids[parent_key]

            if job_name in existing_jobs:
                job_id = existing_jobs[job_name]
                if self.update_job(project_id, job_id, job_config, runtime_identifier, parent_job_id):
                    job_ids[job_key] = job_id
                else:
                    self.failed_jobs.append(job_name)
            else:
                job_id = self.create_job(project_id, job_config, parent_job_id, runtime_identifier)
                if job_id:
                    job_ids[job_key] = job_id
                else:
                    self.failed_jobs.append(job_name)

        return job_ids

    def run(self, project_id: str) -> bool:
        print("=" * 70)
        print("Create CML Jobs — CAI Eval Platform")
        print("=" * 70)

        jobs_config = self.load_jobs_config()
        if not jobs_config:
            print("Failed to load jobs configuration")
            return False

        configured_count = len(jobs_config.get("jobs", {}))
        job_ids = self.create_or_update_jobs(project_id, jobs_config)
        if not job_ids:
            print("Failed to create jobs")
            return False

        failed = getattr(self, "failed_jobs", [])
        if failed:
            print("=" * 70)
            print(f"Failed to create/update {len(failed)} of {configured_count} configured jobs:")
            for name in failed:
                print(f"   {name}")
            print("=" * 70)
            return False

        print("=" * 70)
        print("Job Creation Complete!")
        print(f"Project ID: {project_id}")
        print(f"Jobs created/updated: {len(job_ids)} of {configured_count}")
        for job_key, job_id in job_ids.items():
            print(f"   {job_key}: {job_id}")
        print("=" * 70)
        return True


def main():
    parser = argparse.ArgumentParser(description="Create or update CML jobs from configuration")
    parser.add_argument("--project-id", required=True, help="CML project ID")
    args = parser.parse_args()

    try:
        manager = JobManager()
        sys.exit(0 if manager.run(args.project_id) else 1)
    except KeyboardInterrupt:
        print("\nJob creation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
