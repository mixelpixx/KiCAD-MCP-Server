# Self-hosted CI with KiCad 10 (Windows)

This document explains how to use an existing KiCad 10 installation on a Windows machine as a GitHub Actions self-hosted runner.

When to use this
- You already have a Windows machine with KiCad 10 installed and prefer to run integration tests there.
- You want fast, reliable access to KiCad's Python bindings (`pcbnew`) without installing KiCad on every CI job.

Overview
- Register a self-hosted runner in your repository and add labels such as `windows` and `kicad-10`.
- Push workflow jobs to those labeled runners; the job will run on your machine and can call KiCad's Python directly.

Register the runner
1. Go to GitHub → Repository → Settings → Actions → Runners → New self-hosted runner.
2. Choose Windows and follow the provided setup commands.
3. When configuring, add labels: `kicad-10`, `windows`, `self-hosted`.

Run the runner
- Start the runner process per the GitHub instructions. For long-term availability, install it as a service or run it under a supervisor.

Example workflow
- See `.github/workflows/ci-kicad10-selfhosted.yml` for an example that uses the KiCad Python at `C:\Program Files\KiCad\10.0\bin\python.exe`.

Notes & caveats
- Security: self-hosted runners execute workflow code on your machine. Avoid running untrusted fork PRs on a runner with access to sensitive data.
- Availability: the machine must be online for jobs to run. Use a dedicated VM if you need high availability.
- Reproducibility: tests run on your local environment; for reproducible CI across contributors consider publishing a Docker image with KiCad, or use a dedicated image builder.
- Python deps: the workflow installs project dependencies into KiCad's Python. Ensure that Python's `pip` is available at the specified KiCad Python path.

Next steps
- If you'd like, I can open a PR with the workflow and this document.
