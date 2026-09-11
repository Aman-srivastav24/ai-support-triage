# Day 0 — Learnings

Environment, tooling and version control. Read the **why** column, not just the command.

---

## 1. WSL2 is a separate machine

WSL2 is not a translation layer that converts Linux commands into Windows ones. It is a
real Linux kernel running in a lightweight VM. Ubuntu inside WSL has its own filesystem,
its own root user, its own package manager, its own PATH.

**Consequence:** installing something inside Ubuntu installs it *only* in Ubuntu.
Windows has no record of it. It will not appear in Add/Remove Programs and no Windows
program can run it.

The two systems can see each other's files, and that is the only bridge:

| From | Can reach | Path |
|---|---|---|
| Ubuntu | Windows C: drive | `/mnt/c/Users/...` |
| Windows | Ubuntu filesystem | `\\wsl.localhost\Ubuntu-26.04\home\...` |

**Why the project lives on the Linux side (`~/projects/`) and not `/mnt/c/`:**
files under `/mnt/c` are accessed across the boundary over a network-style protocol.
Measurably slow for `pip install`, considerably worse for Docker bind mounts (which the
app container uses to see source code and trigger hot reload). Permissions also behave
inconsistently across that boundary and confuse both git and Postgres.

**Git Bash is a third environment.** It is a Windows program with its own bundled
`git.exe`. It cannot see anything installed in Ubuntu. Three shells means three PATHs and
three places a command can "work on my machine." Use one.

---

## 2. The Linux filesystem has no C: drive

Linux does not install an application into its own folder. The package manager scatters
the pieces by *type* across one shared tree:

| Path | Contents |
|---|---|
| `/usr/bin` | Executables — `docker`, `python3`, `git` |
| `/etc` | Configuration files |
| `/var` | Changing data — logs, Docker images and containers |
| `/home/you` | Your files. Your project. |
| `/mnt/c` | Windows C: drive, bridged in |

This is why installing feels invisible: nothing appears in your home folder. You type
`docker` and it works because `/usr/bin` is on your PATH.

**Two words that explain most commands:**

- **`sudo`** — run as administrator. Needed for anything touching `/etc`, `/usr`, `/var`.
  Not needed in your own home folder. "Permission denied" usually means a missing `sudo`
  — or that you are writing somewhere you should not be.
- **`apt`** — Ubuntu's package manager. Fetches software and its dependencies from
  trusted servers and places the pieces correctly. There is no `.exe` to download. On
  Linux, downloading an installer is the wrong pattern.

---

## 3. Navigation and the debugging reflex

```bash
pwd                  # where am I
ls -la               # what is here, including hidden files
cd projects          # relative path — from where I am
cd /etc/apt          # absolute path — from root, works anywhere
cd ..                # up one
cd ~                 # home
mkdir -p a/b         # create nested folders, no error if they exist
rm file              # permanent — there is no recycle bin
```

**Hidden files matter.** Any filename starting with a dot is hidden from plain `ls`. Your
project is full of them: `.env`, `.gitignore`, `.git/`, `.venv/`. If a file you created
seems to have vanished, run `ls -la`.

**Leading `/` means absolute; no leading `/` means relative.**

**When something breaks, the first two commands are always `pwd` then `ls -la`.** That
resolves a large share of "it doesn't work."

**Flag convention:** single dash for single letters (`-v`), double dash for whole words
(`--version`). They are not interchangeable — `-v` often means something entirely
different from `--version`.

**Does the current folder matter?**

| Matters | Doesn't matter |
|---|---|
| `mkdir`, `touch`, `git init`, `git clone` | `apt install` |
| `python -m venv`, `pip install` | `docker run` |
| `docker build .`, `docker compose up` | anything using absolute paths |

`docker compose up` looks for `docker-compose.yml` **in the current folder**. Wrong
folder gives "no configuration file provided."

---

## 4. Third-party apt repositories are GPG-signed

Adding a repository means granting a server permission to install software as root. You
cannot simply trust an address — anyone could impersonate it.

The process: download the vendor's **public key**, then write a repo definition
containing `signed-by=/path/to/that/key`. Apt will refuse any package from that repo not
signed by that key.

**The one sentence worth keeping:** third-party apt repos are GPG-signed, and that is
what stops a compromised mirror from serving you malware.

---

## 5. IPv6 timeouts in WSL2

**Symptom:** `apt` warnings reading
`Cannot initiate the connection ... (101: Network is unreachable)` against addresses
like `2620:2d:4000:1::103`.

**Diagnosis:** those are IPv6 addresses. WSL2 frequently has no working IPv6 route. Apt
tries IPv6 first, waits for a timeout, then falls back to IPv4 — once per index file.

**Fix:**
```bash
echo 'Acquire::ForceIPv4 "true";' | sudo tee /etc/apt/apt.conf.d/99force-ipv4
```

**The transferable pattern:** `/etc/*.d/` directories hold config *snippets* read in
filename order. Dropping a file in is the standard way to override behaviour without
editing a vendor's main config file — which would be overwritten on the next upgrade.
The `99` prefix means "read last, wins." Same convention appears in `/etc/sysctl.d/`,
`/etc/apt/apt.conf.d/`, `/etc/systemd/`.

---

## 6. Docker: client, daemon, runtime

Docker is not one program. Installing it pulled five packages:

| Package | Role |
|---|---|
| `docker-ce` | **The daemon.** Background process that builds images, runs containers, manages networks and volumes. |
| `docker-ce-cli` | **The client.** The `docker` command. Sends HTTP requests to the daemon over a Unix socket — it does not run containers itself. |
| `containerd.io` | **The runtime.** Talks to the kernel to create the isolated process. The daemon delegates to it. |
| `docker-buildx-plugin` | Modern image builder. |
| `docker-compose-plugin` | Provides `docker compose` (with a space). |

**Why client and daemon being separate matters:** `docker --version` can succeed while
`docker ps` fails. The first only proves a binary exists; the second proves the daemon is
running and reachable. Always verify with something that actually contacts the daemon.

**`docker compose` (space) vs `docker-compose` (hyphen):** the hyphenated form was a
standalone Python tool, Compose v1, now deprecated. The space form is a plugin to the
Docker CLI — Compose v2. Compose files in this project assume v2.

### A container is not a virtual machine

A container is a normal Linux process, isolated using kernel features:

- **namespaces** — the process sees its own filesystem, network, process list, hostname
- **cgroups** — limits on CPU, memory, I/O

There is no guest OS. That is why containers start in milliseconds and a VM takes a
minute. **This question gets asked.**

### The docker group is effectively root

The CLI reaches the daemon through `/var/run/docker.sock`, owned by root, group `docker`.
Adding yourself to that group is how you avoid typing `sudo`.

But the daemon runs as root, so anyone in the `docker` group can start a container that
mounts the host's entire filesystem and edit anything on it. **Membership of the `docker`
group is equivalent to root access.** Not a bug — it is the design. Fine on a personal
machine; a real decision on a shared server.

```bash
sudo usermod -aG docker $USER
```

`-a` means **append**. Without it, `-G` *replaces* your entire group list, which would
remove you from `sudo` and lock you out of admin on your own machine. Never use `-G`
without `-a`. Group membership is applied at login, so a new shell is required.

### What `hello-world` proved

Read its own output — it describes the architecture:
1. Client contacted the daemon
2. Daemon pulled the image from Docker Hub
3. Daemon created a container from that image
4. Daemon streamed the output back to the client

---

## 7. Python environments

### Versions coexist

`python3.12` and `python3.14` install to separate paths with separate library folders.
Ubuntu's `python3` continues to point at the system version. Adding another interpreter
breaks nothing.

**Never run `sudo pip install`.** On Ubuntu the system Python is an OS dependency — parts
of apt are written in it. Overwriting a library there can break the machine. Modern
Ubuntu blocks this by default with an `externally-managed-environment` error.

### Virtualenv

A venv is a folder containing its own interpreter link and its own `site-packages`.
Activation prepends `.venv/bin` to PATH so the shell finds the venv's `python` before the
system one. That is the entire mechanism — no magic.

```bash
python3 -m venv .venv          # explicit version choice happens here, once
source .venv/bin/activate       # 'source' runs it in the current shell, not a subprocess
```

`source` rather than executing the script directly, because the script modifies PATH —
a subprocess could not affect the parent shell.

After activation, plain `python` and `pip` are the venv's. No version prefix needed again.

**Activation is per-shell and does not persist.** Every new terminal needs it.

**The single most common Python bug:** `ModuleNotFoundError` for a package you just
installed. Look at the prompt first — if `(.venv)` is missing, you installed into one
Python and are running another.

### Wheels, and why the Python version matters

A **wheel** is a prebuilt binary package. Filenames encode the target:

```
pydantic_core-2.x.x-cp314-cp314-manylinux_x86_64.whl
                     ^^^^^ CPython 3.14
```

If no wheel exists for your Python version, pip downloads the source and **compiles it on
your machine** — requiring a build toolchain, and failing on missing headers. This is the
real risk of running a brand-new Python release.

`py3-none-any.whl` means pure Python, no compiled code, works on any version. FastAPI,
Alembic and LangGraph are like this and are never a problem.

**Only packages with compiled extensions carry risk.** In this stack: `pydantic-core`
(Rust), `psycopg` (C), `sqlalchemy` (optional C), `tiktoken` (Rust).

**Testing method:** checking each package on PyPI by hand misses transitive dependencies.
Running `pip install` tests the entire resolved tree in one shot — and you have to run it
anyway.

**Extras:** `psycopg[binary]` — the bracket is an optional dependency group the package
defines. Here it means the prebuilt build with `libpq` bundled, rather than a source
build needing Postgres dev headers.

**Transitive dependencies:** `greenlet` appeared without being requested — SQLAlchemy
pulls it in for async support. Most of what lands in a venv was never asked for directly.

### Ubuntu unbundles venv and pip

`ensurepip is not available` on a fresh Ubuntu. Debian/Ubuntu ship `venv` and `pip` as
separate packages, unlike upstream Python. Fix: `apt install python3.X-venv`.

---

## 8. Git

### The three areas

```
working directory  →  staging area  →  commit history
                 git add          git commit
```

The **staging area** is git's distinguishing feature. You choose exactly what goes into
each commit rather than committing everything that changed — which is how a commit stays
focused on one thing when you have edited five files for two reasons.

`git status` answers three questions at once: which branch, what changed, what is staged.
Run it constantly.

### Commit hashes

`4b34788` is a SHA over the content, author, timestamp **and parent commit**. Because the
parent is included, altering any historical commit changes every hash after it. That is
what makes git history tamper-evident.

`HEAD -> main` means HEAD (current position) is on branch `main`.

### `.gitignore` must exist before the files it excludes

**Git only ignores files it is not already tracking.** Commit `.env` once, then add it to
`.gitignore`, and the secret remains in history permanently. Deleting the file and
committing again does not help — every past commit still contains it. The only real fixes
are rewriting history or rotating the key.

**Order is the whole point.** `.gitignore` was the first commit in this repo, deliberately.

What is excluded and why:

| Pattern | Reason |
|---|---|
| `.env`, `*.pem`, `*.key` | Secrets. Leaked keys are scraped off public GitHub by automated bots within minutes of a push. |
| `.venv/` | Hundreds of MB of dependencies. `requirements.txt` records *what* to install; the venv is rebuilt per machine. Committing it also breaks on any other OS. |
| `__pycache__/`, `*.pyc` | Compiled bytecode, regenerated automatically, noise in diffs. |
| `.vscode/`, `.idea/` | Your editor's settings, not the project's. |

### Conventional Commits

`feat:` · `fix:` · `chore:` · `docs:` · `test:` · `refactor:`

Written in the imperative — "add X", not "added X" — because a commit describes what
applying it *does*.

Interviewers scroll commit history. `feat: add JWT auth with role-based access` reads
differently from `update`, `changes`, `final fix v2`. Costs nothing; many teams enforce
it in CI.

### SSH authentication

GitHub removed password authentication for git in 2021. Two options remain: HTTPS with a
personal access token, or SSH keys.

**How SSH auth works:** generate a **keypair**. The private key never leaves your machine.
The public key goes to GitHub. On push, GitHub sends a challenge that can only be answered
with the private key. GitHub never learns your secret — it only verifies you hold it.

```bash
ssh-keygen -t ed25519 -C "your@email.com"
```

`ed25519` is modern elliptic-curve — shorter and faster than RSA at equivalent security.

| File | Sensitivity |
|---|---|
| `id_ed25519` | **Private.** Never share, never commit, never `cat` it in a screenshot. |
| `id_ed25519.pub` | Public. Designed to be handed out. This is what GitHub receives. |

SSH refuses to use a private key readable by other users, and fails with a permissions
error rather than explaining itself.

**Host verification runs the other way too.** On first connection SSH asks you to vouch
for github.com's key, then stores it in `~/.ssh/known_hosts`. If that fingerprint ever
changes, SSH refuses loudly — protection against someone impersonating GitHub on your
network.

*Same asymmetric-crypto pattern appears again on Day 2 with JWT signing.*

### Remotes

```bash
git remote add origin git@github.com:user/repo.git
git push -u origin main
```

`origin` is a convention, not a keyword — the nickname for "the main remote." A repo can
have several, which is how fork workflows operate.

**URL form matters:** `git@github.com:` uses your SSH key. `https://` would prompt for a
token on every push. Same repo, different transport.

`-u` sets **upstream tracking**, recording that local `main` corresponds to
`origin/main`. Passed once. Afterwards `git push` alone works, and `git status` reports
whether you are ahead or behind.

---

## 9. VS Code with a remote

Once connected via the WSL extension, extensions split into two groups:

- **UI-only** (themes, keybindings) — run on Windows
- **Code-aware** (Python, Pylance, Docker) — must be installed **into WSL** separately

The Windows copy of the Python extension cannot see your `.venv` at all. Skipping the WSL
install produces dead autocomplete and unresolvable imports, which looks like a broken
environment but is not.

**Check the bottom-left corner.** `WSL: Ubuntu-26.04` means you are on the Linux side.
A `\\wsl.localhost\...` path in the title bar means the *wrong* mode — VS Code editing
Linux files from the Windows side over file sharing.

**Restricted Mode** sandboxes untrusted folders, disabling tasks, debugging and some
extension features, in case you have opened a stranger's repository.

---

## 10. Decisions and the reasoning behind them

These are the interview answers. Know the *alternative* and why it lost.

| Decision | Alternative | Why |
|---|---|---|
| Docker Engine in WSL2 | Docker Desktop | Fewer layers, no Windows/Linux file-sharing bridge, runtime sits beside the code |
| Project on `~/` | `/mnt/c/` | Windows boundary is slow for pip and painful for bind mounts; permissions misbehave |
| Python 3.14 | 3.12 via deadsnakes PPA | 26.04 ships only 3.14; all compiled dependencies had 3.14 wheels. Dockerfile pins the same version — the container is the source of truth |
| Neon | Render Postgres | Render's free DB expires at 30 days; Neon's free tier is permanent and does not pause |
| Neon, Auth off | Neon Auth | Day 2 builds JWT + bcrypt + RBAC by hand. Managed auth removes the thing being demonstrated |
| SSH keys | HTTPS + token | No expiry to manage; matches most workplaces |
| Repo created in web UI | `gh repo create` | Repo settings (visibility, branch protection, description) live on GitHub's side and are configured there anyway |

**The general principle:** managed services are correct when the problem is
undifferentiated and you are shipping a product. They are wrong when the problem *is*
what you are trying to demonstrate. Same reasoning applies later to pgvector over
Pinecone.

---

## 11. Things that cost time today

- **Never paste a multi-command block into an interactive prompt.** The prompt reads
  whatever is queued in stdin, including pasted text. `ssh-keygen` consumed the next
  command as its filename answer.
- **Password input shows nothing** — no dots, no asterisks. Not a frozen terminal.
- **`W:` is a warning, `E:` is an error.** Apt continues past warnings using cached data.
  Read which one you have before panicking.
- **Read the error message.** Ubuntu's Python errors name the exact package to install.

---

## Recall questions

Answer out loud, no notes.

1. Docker's CLI and daemon are separate programs. What happens when you type
   `docker run`, and why can `docker --version` succeed while `docker ps` fails?
2. Why is `.venv/` in `.gitignore` when it contains the exact packages the project needs?
   What goes into git instead?
3. You have a private key and a public key. Which one did GitHub receive, and why is it
   safe for it to be public?
4. Why must `.gitignore` be written *before* `.env` exists rather than after?
5. What is the difference between a container and a virtual machine?
6. Why is adding yourself to the `docker` group equivalent to giving yourself root?