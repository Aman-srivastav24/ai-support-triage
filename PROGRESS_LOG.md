# Progress Log — AI Support Triage API

---

## Day 0 — Environment setup

**Date:** 11 Sep 2026

### Built

- WSL2 + Ubuntu 26.04 (codename `resolute`) established as the development environment
- Docker Engine 29.8.0 + Compose v2 installed natively inside WSL (not Docker Desktop)
- Non-root Docker access configured via `usermod -aG docker`, verified with `hello-world`
- Python virtualenv created at `~/projects/ai-support-triage/.venv`
- Git repository initialised; `.gitignore` written *before* any secret file existed
- SSH keypair (ed25519) generated and registered with GitHub
- Two commits pushed to `github.com/Aman-srivastav24/ai-support-triage`
- VS Code connected to WSL — files, terminal and interpreter all on the Linux side
- Accounts created: GitHub repo, Groq API key, Neon Postgres project (Singapore, free tier)

### What broke

**1. `apt` failing against `security.ubuntu.com`**
Errors read `Cannot initiate the connection ... (101: Network is unreachable)` against
addresses like `2620:2d:4000:1::103`. Those are IPv6. WSL2 had no working IPv6 route, so
apt attempted IPv6 first, waited for the timeout, then fell back to IPv4 — repeatedly,
for every index file.
Fixed with `Acquire::ForceIPv4 "true";` in `/etc/apt/apt.conf.d/99force-ipv4`.
Result: all warnings cleared on the next `apt-get update`.

**2. `python3.12` not available**
`E: Unable to locate package python3.12`. Ubuntu 26.04 ships only Python 3.14; distro
archives do not carry older Python versions.
Resolved by changing the decision rather than the environment — see below.

**3. `ensurepip is not available`**
`python3 -m venv .venv` failed on a fresh Ubuntu. Debian/Ubuntu unbundle `venv` and
`pip` from the base Python package, unlike upstream Python.
Fixed with `sudo apt-get install python3.14-venv`.

**4. Pasted a multi-command block into an interactive prompt**
Ran `ssh-keygen` and pasted the follow-up `cat` command at the same time. `ssh-keygen`
consumed the second line as the answer to "Enter file in which to save the key" and
tried to create a key at a path that did not exist.
Lesson: interactive prompts read whatever is queued in stdin, including pasted text.
Run one command, answer its prompts, then run the next.

### Decisions

**Python 3.14, not 3.12 (deviation from the plan document)**
Ubuntu 26.04 ships only 3.14. Rather than install an older Python from a third-party
PPA, tested the four dependencies that contain compiled extensions — `pydantic-core`
(Rust), `psycopg` (C), `sqlalchemy` (optional C extensions), `tiktoken` (Rust). All
installed from prebuilt wheels with no source builds, so 3.14 is viable.
The Dockerfile will pin `python:3.14-slim` so local and container agree.
Position: *the container is the source of truth for runtime version; the local machine
only has to match it.*

**Docker Engine in WSL2, not Docker Desktop**
Fewer moving parts, no Windows/Linux file-sharing layer, and the container runtime sits
on the same side as the source code.

**Project on the Linux filesystem (`~/projects/`), not `/mnt/c/`**
Files under `/mnt/c` are reached across the Windows–Linux boundary over a network-style
protocol. Slow for `pip install`, worse for Docker bind mounts, and permissions behave
inconsistently.

**Neon Auth disabled**
Managed auth would remove the entire Day 2 build — JWT, bcrypt, `get_current_user`,
RBAC. Those are the most-interviewed backend topics in this project.

**Neon over Render Postgres**
Render's free Postgres expires after 30 days. Neon's free tier is permanent and does not
pause on inactivity, which matters when a reviewer opens the link weeks after applying.

**SSH over HTTPS + token for GitHub auth**
No token expiry to manage, and it matches what most workplaces use.

### Numbers

| Metric | Value |
|---|---|
| apt download throughput | ~5 KB/s — network is slow, budget extra time for image pulls |
| Docker Engine version | 29.8.0 |
| Python version | 3.14.4 |
| Neon free tier | 100 CU-hrs, 0.5 GB storage, 5 GB transfer/month |

### Open items

- Confirm Python extension installed on the WSL side of VS Code
- Groq has no embeddings endpoint — Day 3 will need a second provider for embeddings.
  Decide on Day 3, not before.