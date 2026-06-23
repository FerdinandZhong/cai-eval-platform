"""HTTP client for pushing results to eval platform."""

import httpx


class EvalClient:
    def __init__(self, server_url: str, job_id: str, job_token: str = ""):
        self.base = server_url.rstrip("/")
        if not self.base.endswith("/app"):
            self.base = f"{self.base}/app"
        self.job_id = job_id
        self.job_token = job_token

    def push_result(self, payload: dict) -> dict:
        payload = dict(payload)
        if self.job_token:
            payload["job_token"] = self.job_token
        url = f"{self.base}/api/jobs/{self.job_id}/results"
        with httpx.Client(timeout=120) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            return r.json()
