rca-prototype

Purpose:
- Collect GitHub repo, commits, workflows, workflow runs, jobs, deployments and statuses.
- Normalize into a JSON structure suitable for the RCA Agent.

Preconditions:
- Set GITHUB_TOKEN in your environment with at least read access to the repository and actions data.

Quick start:

1. Install dependencies
   python -m pip install -r rca-prototype/requirements.txt

2. Configure token
   export GITHUB_TOKEN="ghp_..."  # do this locally; do NOT commit the token

3. Run the prototype
   python rca-prototype/main.py

Output:
- JSON file written to rca-prototype/output/normalized_<timestamp>.json
- main prints a summary of API calls and the normalized data

Run tests:
   python -m pytest rca-prototype/tests -q

Notes:
- The prototype will not assume a successful workflow is a deployment.
- If an API call fails (403/429/5xx), the call is recorded and the run continues with partial data.
- The lookback window is controlled in rca-prototype/config.yaml.
