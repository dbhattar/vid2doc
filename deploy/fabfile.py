"""Fabric deployment tasks for the Framewrite backend + frontend stack, onto
a single Ubuntu/Debian VPS running nginx as the reverse proxy in front of
Docker Compose. Two domains: app.framewrite.cc (frontend) and
api.framewrite.cc (backend API) -- see backend/README.md's "Deploying to a
VPS" section for the full conceptual checklist this automates.

Usage (run from *this* `deploy/` directory -- `fab` auto-discovers
`fabfile.py` in the current directory):

    cd deploy
    pip install -r requirements.txt

    # One-time, connected as root: creates the `deploy` user, gives it
    # passwordless sudo, and copies root's authorized_keys so it can log in
    # with the same key. Skip this if `deploy` already exists.
    fab -H root@YOUR_VPS_IP -i ~/.ssh/your_key create-deploy-user

    # Everything below connects as `deploy`, not root.

    # One-time server setup (installs Docker, nginx, certbot; clones the repo)
    fab -H deploy@YOUR_VPS_IP -i ~/.ssh/your_key bootstrap

    # ...then SSH in once, by hand, to fill real secrets:
    #   cp /opt/framewrite/backend/.env.example /opt/framewrite/backend/.env
    #   $EDITOR /opt/framewrite/backend/.env
    # ...and point app.framewrite.cc / api.framewrite.cc DNS A records at
    # this server's IP before the next step.

    fab -H deploy@YOUR_VPS_IP -i ~/.ssh/your_key setup-tls
    fab -H deploy@YOUR_VPS_IP -i ~/.ssh/your_key deploy

    # Every deploy after that is just:
    fab -H deploy@YOUR_VPS_IP -i ~/.ssh/your_key deploy

(Invoking from elsewhere works too, via `fab -f deploy/fabfile.py ...`.)

Every privileged step uses `c.sudo(...)`, so the SSH user needs sudo rights.
Passwordless sudo is easiest; otherwise add `--prompt-for-sudo-password` to
the `fab` invocation and Fabric will ask once per run.

`.env` is never hand-authored by any task here -- it holds production secrets
(Stripe keys, JWT secret, DB password) that shouldn't be hardcoded into a file
that gets committed or passed around. Create it by hand, once:

    cp /opt/framewrite/backend/.env.example /opt/framewrite/backend/.env
    $EDITOR /opt/framewrite/backend/.env

set-env below is the one exception -- it updates a single KEY=VALUE pair
from the command line (e.g. to flip TRANSCRIPTION_ENGINE or rotate one key
without opening an editor), but nothing about .env's actual secret values is
ever written into this script itself; `value` only ever comes from what you
type on the command line for that one invocation:

    fab ... set-env --key=TRANSCRIPTION_ENGINE --value=baseten
"""

import os
import re
import tempfile
import uuid

from fabric import task

# --- Configuration -----------------------------------------------------
# Edit these to match your setup.

APP_DIR = "/opt/framewrite"
GIT_REPO_URL = "https://github.com/dbhattar/vid2doc.git"
GIT_BRANCH = "main"

DEPLOY_USER = "deploy"

APP_DOMAIN = "app.framewrite.cc"
API_DOMAIN = "api.framewrite.cc"
CERTBOT_EMAIL = "dipesh.bhattarai@gmail.com"

NGINX_SITE_NAME = "framewrite"

# GIT_REPO_URL above is the SSH form (matches this repo's own `origin`),
# which requires a deploy key: generate a keypair on the VPS
# (`ssh-keygen -t ed25519 -f ~/.ssh/framewrite_deploy -N ""`), add the
# *public* half as a read-only Deploy Key on the GitHub repo (Settings ->
# Deploy keys), and add the following to the VPS's `~/.ssh/config`:
#
#   Host github.com
#     IdentityFile ~/.ssh/framewrite_deploy
#
# If the repo is public, you can skip all of that and set GIT_REPO_URL to
# the HTTPS form instead (`https://github.com/dbhattar/vid2doc.git`).

NGINX_CONF = f"""\
server {{
    listen 80;
    server_name {APP_DOMAIN};

    location / {{
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}

server {{
    listen 80;
    server_name {API_DOMAIN};

    # Matches backend's MAX_UPLOAD_BYTES (2GB default) plus headroom --
    # otherwise nginx 413s large video uploads before FastAPI ever sees them.
    client_max_body_size 2100M;

    location / {{
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Uploading a large video (esp. on a slow connection) can take a
        # while; don't let nginx buffer the whole body in memory or time
        # the request out mid-upload.
        proxy_request_buffering off;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }}
}}
"""


@task
def create_deploy_user(c):
    """One-time, connected as root (fab -H root@YOUR_VPS_IP ...
    create-deploy-user): creates DEPLOY_USER, grants it passwordless sudo,
    and copies root's authorized_keys so it can log in with the exact same
    key root already uses. Every subsequent task in this file connects as
    DEPLOY_USER, not root -- run this one first. Safe to re-run -- every
    step checks before creating/copying anything."""
    print(f"==> Creating user '{DEPLOY_USER}' (skipped if it already exists)")
    if c.run(f"id -u {DEPLOY_USER}", warn=True, hide=True).failed:
        c.run(f"adduser --disabled-password --gecos '' {DEPLOY_USER}")
    else:
        print("    already exists, skipping")

    print(f"==> Adding '{DEPLOY_USER}' to the sudo group")
    c.run(f"usermod -aG sudo {DEPLOY_USER}")

    print(f"==> Copying root's authorized_keys to {DEPLOY_USER}'s account")
    c.run(f"mkdir -p /home/{DEPLOY_USER}/.ssh")
    c.run(f"cp /root/.ssh/authorized_keys /home/{DEPLOY_USER}/.ssh/authorized_keys")
    c.run(f"chown -R {DEPLOY_USER}:{DEPLOY_USER} /home/{DEPLOY_USER}/.ssh")
    c.run(f"chmod 700 /home/{DEPLOY_USER}/.ssh")
    c.run(f"chmod 600 /home/{DEPLOY_USER}/.ssh/authorized_keys")

    print(f"==> Granting passwordless sudo to '{DEPLOY_USER}'")
    c.run(f"echo '{DEPLOY_USER} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{DEPLOY_USER}")
    c.run(f"chmod 440 /etc/sudoers.d/{DEPLOY_USER}")
    c.run("visudo -c")

    print(
        "\n"
        "Done. Test it now, from a NEW terminal (keep this root session/shell\n"
        "open until this is confirmed):\n"
        f"  ssh -i ~/.ssh/your_key {DEPLOY_USER}@<VPS_IP>\n"
        "  sudo whoami   # should print 'root' with no password prompt\n"
        "\n"
        "Once that works, every task below (bootstrap, setup-tls, deploy, ...)\n"
        f"uses -H {DEPLOY_USER}@YOUR_VPS_IP instead of root.\n"
    )


@task
def bootstrap(c):
    """One-time VPS setup: Docker, nginx, certbot, clone the repo, write the
    (HTTP-only, pre-TLS) nginx config. Safe to re-run -- every step checks
    before installing/cloning, so it won't clobber anything already there."""
    print("==> Installing nginx + base packages")
    c.sudo("apt-get update -y")
    c.sudo("apt-get install -y ca-certificates curl gnupg git nginx")

    print("==> Installing Docker (skipped if already present)")
    if c.run("command -v docker", warn=True, hide=True).failed:
        c.sudo("install -m 0755 -d /etc/apt/keyrings")
        c.sudo("curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc")
        c.sudo("chmod a+r /etc/apt/keyrings/docker.asc")
        c.run(
            "echo "
            '"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] '
            'https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" '
            "| sudo tee /etc/apt/sources.list.d/docker.list > /dev/null"
        )
        c.sudo("apt-get update -y")
        c.sudo("apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin")
    else:
        print("    already installed, skipping")

    print("==> Installing certbot")
    c.sudo("apt-get install -y certbot python3-certbot-nginx")

    print(f"==> Cloning repo into {APP_DIR} (skipped if already cloned)")
    if c.run(f"test -d {APP_DIR}/.git", warn=True, hide=True).failed:
        c.sudo(f"mkdir -p {APP_DIR}")
        c.sudo(f"chown $(whoami) {APP_DIR}")
        c.run(f"git clone --branch {GIT_BRANCH} {GIT_REPO_URL} {APP_DIR}")
    else:
        print("    already cloned, skipping (use `fab ... deploy` to update it)")

    print("==> Writing nginx site config (HTTP only -- setup-tls adds HTTPS)")
    _write_nginx_config(c)

    print(
        "\n"
        "Bootstrap done. Before running `deploy`:\n"
        f"  1. SSH in and create real secrets: cp {APP_DIR}/backend/.env.example {APP_DIR}/backend/.env\n"
        f"     then edit {APP_DIR}/backend/.env with real values (see backend/README.md's env var table).\n"
        f"  2. Point {APP_DOMAIN} and {API_DOMAIN} DNS A records at this server's IP.\n"
        "  3. Once DNS has propagated, run: fab ... setup-tls\n"
        "  4. Then run: fab ... deploy\n"
    )


def _ensure_server_names_hash_bucket_size(c):
    """Some nginx builds ship with an effective server_names_hash_bucket_size
    of 32, which is too small to hash even short server_names like ours --
    `nginx -t` fails with 'could not build server_names_hash, you should
    increase server_names_hash_bucket_size: 32'. Idempotent: only inserts if
    no active (uncommented) directive already exists, so re-running this
    never adds a second, conflicting line inside http{}."""
    check = c.run(
        r"grep -qE '^\s*server_names_hash_bucket_size' /etc/nginx/nginx.conf", warn=True, hide=True
    )
    if check.failed:
        c.sudo(r"sed -i '/http {/a\    server_names_hash_bucket_size 64;' /etc/nginx/nginx.conf")


def _write_nginx_config(c):
    available_path = f"/etc/nginx/sites-available/{NGINX_SITE_NAME}"
    enabled_path = f"/etc/nginx/sites-enabled/{NGINX_SITE_NAME}"
    c.run(f"cat > /tmp/{NGINX_SITE_NAME}.nginx << 'FRAMEWRITE_NGINX_EOF'\n{NGINX_CONF}\nFRAMEWRITE_NGINX_EOF")
    c.sudo(f"mv /tmp/{NGINX_SITE_NAME}.nginx {available_path}")
    c.sudo(f"ln -sf {available_path} {enabled_path}")
    c.sudo("rm -f /etc/nginx/sites-enabled/default")
    _ensure_server_names_hash_bucket_size(c)
    c.sudo("nginx -t")
    c.sudo("systemctl reload nginx")


@task
def setup_tls(c):
    """Provisions Let's Encrypt certs for both domains via certbot's nginx
    plugin, which also patches the nginx config in place to add the 443
    server blocks and an HTTP->HTTPS redirect. Run once DNS for both
    domains actually resolves to this server -- certbot's HTTP-01 challenge
    will fail otherwise."""
    c.sudo(
        f"certbot --nginx -d {APP_DOMAIN} -d {API_DOMAIN} "
        f"--non-interactive --agree-tos -m {CERTBOT_EMAIL} --redirect"
    )
    c.sudo("systemctl reload nginx")
    print("TLS configured. Certbot also installed a systemd timer for auto-renewal.")


@task
def deploy(c):
    """Routine deploy: pull the latest commit on GIT_BRANCH, rebuild any
    changed images, (re)start the stack. Safe to run repeatedly --
    `docker compose up -d --build` only recreates containers whose image
    actually changed. Refuses to run if backend/.env doesn't exist yet, to
    avoid ever starting production with empty/default secrets."""
    env_check = c.run(f"test -f {APP_DIR}/backend/.env", warn=True, hide=True)
    if env_check.failed:
        print(
            f"ERROR: {APP_DIR}/backend/.env doesn't exist yet.\n"
            f"Create it by hand first: cp {APP_DIR}/backend/.env.example {APP_DIR}/backend/.env, "
            "then fill in real secrets. Refusing to deploy without it."
        )
        raise SystemExit(1)

    print("==> Pulling latest code")
    # Only affects tracked files -- backend/.env and backend/data/ are both
    # gitignored (untracked), so this can never touch either of them.
    c.run(f"cd {APP_DIR} && git fetch origin {GIT_BRANCH} && git reset --hard origin/{GIT_BRANCH}")

    print("==> Building and starting containers (this also runs pending Alembic migrations)")
    c.sudo(f"bash -c 'cd {APP_DIR}/backend && docker compose up -d --build'")

    c.sudo(f"bash -c 'cd {APP_DIR}/backend && docker compose ps'")


def _restart_stack(c):
    """Recreates the stack without rebuilding images -- e.g. after editing
    .env by hand (or via set-env below). Deliberately `up -d`, not
    `docker compose restart`: `restart` just stops/starts the *same*
    already-created containers and never re-reads .env/env_file at all,
    since that's only evaluated when a container is (re)created -- so it
    would silently keep serving whatever env vars the container started
    with, no matter what .env says now. `up -d` re-evaluates the compose
    config (including env_file) and recreates only the containers whose
    resolved config actually changed."""
    c.sudo(f"bash -c 'cd {APP_DIR}/backend && docker compose up -d'")
    c.sudo(f"bash -c 'cd {APP_DIR}/backend && docker compose ps'")


@task
def restart(c):
    """Recreates the stack without rebuilding images -- e.g. after editing
    .env by hand. See _restart_stack's docstring for why this is `up -d`,
    not `docker compose restart`."""
    _restart_stack(c)


ENV_PATH = f"{APP_DIR}/backend/.env"
ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Cosmetic only, for the confirmation printout below -- masks what's echoed back for a
# key name that looks secret-shaped, since this is often invoked with a real credential
# as `value`. Doesn't affect what's written to .env itself.
SENSITIVE_KEY_PATTERN = re.compile(r"(SECRET|TOKEN|PASSWORD|_KEY)$", re.IGNORECASE)


def _display_value(key: str, value: str) -> str:
    if SENSITIVE_KEY_PATTERN.search(key) and len(value) > 4:
        return value[:4] + "…" * 3
    return value


@task
def set_env(c, key, value, restart_after=True):
    """Updates (or adds) one KEY=VALUE line in the VPS's backend/.env, without
    needing to SSH in and hand-edit it -- e.g. to flip TRANSCRIPTION_ENGINE
    or rotate a single key without opening an editor. This is the one
    exception to this file's own "never touches .env" rule (see the module
    docstring) -- still nothing about .env's actual secret values is ever
    hardcoded here, `value` only ever comes from what you pass on the
    command line.

    Downloads the current .env, edits it locally (never puts `value`
    through a remote shell command -- no quoting/injection risk for values
    containing spaces, quotes, $(), etc., and it never touches the VPS's
    own shell history), then uploads the result to a temp path and renames
    it into place atomically, so a dropped connection mid-upload can never
    leave a half-written .env behind. Restarts the stack afterward by
    default (see _restart_stack's docstring for why that's the right way
    to pick up an edited .env) so the change actually takes effect --
    pass --no-restart-after to batch several set-env calls before one
    restart.

    Usage: fab ... set-env --key=TRANSCRIPTION_ENGINE --value=baseten
    """
    if not ENV_KEY_PATTERN.match(key):
        print(f"ERROR: '{key}' doesn't look like a valid env var name (letters/digits/underscore, can't start with a digit).")
        raise SystemExit(1)
    if "\n" in value or "\r" in value:
        print("ERROR: value can't contain a newline -- that would corrupt the .env file.")
        raise SystemExit(1)

    env_check = c.run(f"test -f {ENV_PATH}", warn=True, hide=True)
    if env_check.failed:
        print(
            f"ERROR: {ENV_PATH} doesn't exist yet.\n"
            f"Create it by hand first: cp {APP_DIR}/backend/.env.example {ENV_PATH}, "
            "then fill in real secrets. Refusing to set a value into it without it existing."
        )
        raise SystemExit(1)

    with tempfile.TemporaryDirectory() as tmp:
        local_path = os.path.join(tmp, ".env")
        c.get(ENV_PATH, local_path)

        with open(local_path) as f:
            lines = f.read().splitlines()

        new_line = f"{key}={value}"
        previous_value = None
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}=") and not line.lstrip().startswith("#"):
                previous_value = line[len(key) + 1 :]
                lines[i] = new_line
                updated = True
                break
        if not updated:
            lines.append(new_line)

        with open(local_path, "w") as f:
            f.write("\n".join(lines) + "\n")

        remote_tmp_path = f"{ENV_PATH}.tmp"
        c.put(local_path, remote_tmp_path)
        c.run(f"mv {remote_tmp_path} {ENV_PATH}")

    if updated:
        print(f"Updated {key} in {ENV_PATH} (was: {_display_value(key, previous_value)!r}, now: {_display_value(key, value)!r}).")
    else:
        print(f"Added {key}={_display_value(key, value)!r} to {ENV_PATH} (key didn't exist before).")

    if restart_after:
        print("==> Restarting the stack to pick up the change")
        _restart_stack(c)
    else:
        print("Skipped restart (--no-restart-after) -- run `fab ... restart` when ready to apply.")


@task
def put_file(c, local_file, remote_dir, filename=None):
    """Uploads one local file into a directory on the VPS -- e.g. to refresh
    backend/data/youtube_cookies.txt (bind-mounted into the api/worker
    containers as /data/youtube_cookies.txt, see app/youtube.py's
    _COOKIES_FILE) without needing to SSH in and copy it by hand.

    remote_dir is relative to APP_DIR unless given as an absolute path
    (starting with /) -- e.g. --remote-dir=backend/data resolves to
    {APP_DIR}/backend/data. The uploaded file keeps its local filename
    unless --filename overrides it.

    SFTP (what the underlying upload uses) always transfers as the
    connected SSH user, with no sudo equivalent -- so this can't just SFTP
    straight into remote_dir if that directory isn't writable by
    DEPLOY_USER (e.g. backend/data/, auto-created root-owned by the Docker
    daemon the first time `docker compose up` ran its bind mount). Same
    upload-to-/tmp-then-sudo-mv workaround _write_nginx_config already uses
    for exactly this reason: SFTP-upload to a neutral, always-writable /tmp
    path, then `sudo mkdir`/`sudo mv` into the real destination, which works
    regardless of who owns it.

    Usage:
        fab ... put-file --local-file=./youtube_cookies.txt --remote-dir=backend/data
        fab ... put-file --local-file=./cookies.txt --remote-dir=backend/data --filename=youtube_cookies.txt
    """
    if not os.path.isfile(local_file):
        print(f"ERROR: local file not found: {local_file}")
        raise SystemExit(1)

    resolved_dir = remote_dir if remote_dir.startswith("/") else f"{APP_DIR}/{remote_dir}"
    dest_filename = filename or os.path.basename(local_file)
    dest_path = f"{resolved_dir}/{dest_filename}"
    tmp_path = f"/tmp/put-file-{uuid.uuid4().hex}"

    print(f"==> Uploading {local_file} -> {dest_path}")
    c.put(local_file, tmp_path)
    c.sudo(f"mkdir -p {resolved_dir}")
    c.sudo(f"mv {tmp_path} {dest_path}")
    print("Done.")


@task
def run(c, cmd, sudo=True):
    """Runs an arbitrary command inside {APP_DIR}/backend on the VPS -- an
    escape hatch for one-off diagnostics (e.g. testing yt-dlp directly
    inside the running api container, same environment/cookies file it
    actually uses) without needing to SSH in by hand. Defaults to sudo,
    matching every docker compose invocation elsewhere in this file -- pass
    --sudo=False for a command that doesn't need it.

    Usage:
        fab ... run --cmd="docker compose ps"
        fab ... run --cmd="docker compose exec api yt-dlp --version"
        fab ... run --cmd="docker compose exec api yt-dlp --cookies /data/youtube_cookies.txt --extractor-args youtube:player_client=default,tv --verbose --dump-json --no-playlist https://youtu.be/CMPUAVKKK9k"
    """
    runner = c.sudo if sudo else c.run
    runner(f"bash -c 'cd {APP_DIR}/backend && {cmd}'")


@task
def logs(c, service="api", lines=100):
    """Tails logs for one service: api (default), worker, frontend, or postgres."""
    c.sudo(f"bash -c 'cd {APP_DIR}/backend && docker compose logs --tail {lines} {service}'")


# --- Disk usage diagnostics ------------------------------------------------
# Everything below is read-only (df/du/docker system df/journalctl --disk-usage):
# it reports where the space went and never deletes anything. Run as sudo
# because backend/data/ and /var/lib/docker are root-owned. Commands must not
# contain single quotes: they're embedded in `bash -c '...'` (same convention
# as the docker compose calls above), where nothing is expanded by the login
# shell, so globs and `command substitution` are evaluated by the inner bash.


def _report(c, title, cmd):
    """One labelled section of a disk report. warn=True so a section that
    fails (e.g. docker not running) doesn't abort the rest of the report."""
    print(f"\n==> {title}")
    c.sudo(f"bash -c '{cmd}'", warn=True)


@task
def disk(c):
    """Where is the VPS's disk space going? One read-only report: filesystem
    and inode usage, the biggest top-level directories, Docker's own
    breakdown, the app's data directories, and the usual silent culprits
    (Docker container logs, systemd journal, /var/log, apt caches).

    Start here, then drill into whatever is big with `disk-top`,
    `docker-disk` or `job-disk` below.

    Usage:
        fab ... disk
    """
    data = f"{APP_DIR}/backend/data"
    _report(c, "Filesystems (df -h) -- the Use% column is what matters", "df -hT -x tmpfs -x devtmpfs -x squashfs -x overlay")
    _report(c, "Inodes (df -i) -- 100% IUse% also means 'disk full', even with free space", "df -i / 2>/dev/null")
    _report(c, "Biggest top-level directories on / (one filesystem, largest first)", "du -xh --max-depth=1 / 2>/dev/null | sort -rh | head -15")
    _report(c, "Docker: images, containers, volumes, build cache (RECLAIMABLE = safe to prune)", "docker system df")
    _report(c, "Docker root (/var/lib/docker) by subdirectory", "du -sh /var/lib/docker/* 2>/dev/null | sort -rh")
    _report(c, f"App data ({data}) -- uploads, generated output, postgres", f"du -sh {data}/* 2>/dev/null | sort -rh")
    _report(
        c,
        "Container log files (Docker's json logs grow without bound unless rotation is configured)",
        "du -sh /var/lib/docker/containers/*/*-json.log 2>/dev/null | sort -rh | head -10",
    )
    _report(c, "systemd journal", "journalctl --disk-usage")
    _report(c, "/var/log -- 10 biggest files", "du -ah /var/log 2>/dev/null | sort -rh | head -10")
    _report(c, "Package caches (apt)", "du -sh /var/cache/apt /var/lib/apt/lists 2>/dev/null")
    print("\nNext: `fab ... disk-top --path=/some/dir` to drill in, `docker-disk` for Docker detail, `job-disk` for per-job folders.")


@task
def disk_top(c, path="/", depth=1, count=20):
    """Largest entries under one directory, biggest first -- drill into
    whatever `disk` flagged. Stays on a single filesystem (du -x) so it
    won't wander into /proc or mounted volumes when run on /.

    Usage:
        fab ... disk-top                                    # top level of /
        fab ... disk-top --path=/var --depth=2
        fab ... disk-top --path=/opt/framewrite/backend/data --count=30
    """
    path = str(path)
    if not re.fullmatch(r"/[A-Za-z0-9_./-]*", path) or ".." in path:
        print(f"ERROR: --path must be an absolute path of letters, digits and _ . / - only (got {path!r}).")
        raise SystemExit(1)
    _report(
        c,
        f"Largest entries under {path} (depth {int(depth)}, top {int(count)})",
        f"du -xh --max-depth={int(depth)} {path} 2>/dev/null | sort -rh | head -{int(count)}",
    )


@task
def docker_disk(c):
    """Docker's disk usage in detail: every image, container and volume with
    its size, plus build cache. `docker system df` in `disk` is the summary;
    this names the individual offenders (e.g. a pile of old image versions
    left behind by repeated deploys). Read-only -- to reclaim space you'd
    run `docker image prune -a` / `docker builder prune` yourself, after
    reading this.

    Usage:
        fab ... docker-disk
    """
    _report(c, "Docker disk usage, verbose (images / containers / volumes / build cache)", "docker system df -v")


@task
def docker_prune(c, keep_hours=0, images=False):
    """Reclaims Docker disk space: deletes build cache (what `docker system df`
    reports as Build Cache / RECLAIMABLE) and dangling images. Safe for a
    running stack -- it never touches running containers, volumes or the
    app's data -- but the next `deploy` rebuilds the images from scratch, so
    it's slower (re-downloads npm/pip packages).

    --keep-hours=N keeps cache newer than N hours (default 0 = delete all of
    it); --images also deletes every image no container is using, e.g.
    old versions left behind by earlier deploys. Prints `docker system df`
    before and after so you can see what it freed.

    Usage:
        fab ... docker-prune                        # all build cache + dangling images
        fab ... docker-prune --keep-hours=168       # keep the last week of cache
        fab ... docker-prune --images               # also unused images
    """
    hours = int(keep_hours)
    until = f" --filter until={hours}h" if hours > 0 else ""
    _report(c, "Before", "docker system df")
    _report(c, "Removing build cache", f"docker builder prune -a -f{until}")
    _report(c, "Removing dangling images", "docker image prune -f")
    if images:
        _report(c, "Removing images not used by any container", "docker image prune -a -f")
    _report(c, "After", "docker system df")


@task
def job_disk(c, count=20):
    """The biggest per-job folders under backend/data/uploads (the uploaded
    or imported source media) and backend/data/output (frames, audio and
    generated documents) -- usually where the app's own disk growth is.
    Folder names are job ids: look one up in the admin Jobs page. Old jobs
    are normally removed by the retention sweep (backend/retention.py), so a
    large, very old folder here may mean that sweep isn't running or is
    failing.

    Usage:
        fab ... job-disk
        fab ... job-disk --count=50
    """
    data = f"{APP_DIR}/backend/data"
    n = int(count)
    _report(c, f"Largest {n} folders in {data}/uploads (source media)", f"du -sh {data}/uploads/* 2>/dev/null | sort -rh | head -{n}")
    _report(c, f"Largest {n} folders in {data}/output (derived files)", f"du -sh {data}/output/* 2>/dev/null | sort -rh | head -{n}")
    _report(
        c,
        "Job folders: how many, and total size",
        f"echo uploads: `ls {data}/uploads 2>/dev/null | wc -l` folders; echo output: `ls {data}/output 2>/dev/null | wc -l` folders; "
        f"du -sh {data}/uploads {data}/output 2>/dev/null",
    )


# --- Retention (7-day cleanup of job files) --------------------------------
# backend/retention.py deletes old jobs' files, but it's a one-shot script:
# nothing runs it unless a scheduler does. These tasks check for, install,
# and manually run that schedule.

RETENTION_CRON_FILE = "/etc/cron.d/framewrite-retention"
RETENTION_LOG = "/var/log/framewrite-retention.log"
# -T: cron has no terminal, and `docker compose run` otherwise tries to
# allocate one.
RETENTION_COMMAND = f"cd {APP_DIR}/backend && docker compose run --rm -T api python retention.py"


@task
def retention_status(c):
    """Is the retention sweep actually scheduled, and when did it last run?
    Read-only. If the 'Scheduled' section is empty, nothing is cleaning up
    old jobs' files -- run `install-retention-cron`.

    Usage:
        fab ... retention-status
    """
    _report(c, f"Scheduled? ({RETENTION_CRON_FILE} and any crontab mentioning retention.py)",
            f"ls -l {RETENTION_CRON_FILE} 2>&1; cat {RETENTION_CRON_FILE} 2>/dev/null; "
            "grep -rs retention.py /etc/cron.d /etc/crontab /var/spool/cron 2>/dev/null; "
            "for u in root deploy; do crontab -l -u $u 2>/dev/null | grep retention.py; done; true")
    _report(c, f"Last runs ({RETENTION_LOG})",
            f"ls -l {RETENTION_LOG} 2>&1; grep -e Retention -e Total {RETENTION_LOG} 2>/dev/null | tail -10")
    _report(c, "Cron service running?", "systemctl is-active cron 2>&1")


@task
def install_retention_cron(c, hour=3):
    """Schedules the retention sweep daily (03:00 server time by default) via
    /etc/cron.d, logging to /var/log/framewrite-retention.log (rotated weekly).
    Safe to re-run -- it rewrites the same file. This only schedules it; run
    `retention-run` first to see what the first sweep would delete.

    Usage:
        fab ... install-retention-cron
        fab ... install-retention-cron --hour=4
    """
    hour = int(hour)
    if not 0 <= hour <= 23:
        print("ERROR: --hour must be 0-23.")
        raise SystemExit(1)
    cron = (
        "# Framewrite: delete old jobs' files (backend/retention.py). Managed by fab install-retention-cron.\n"
        "SHELL=/bin/bash\n"
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
        f"0 {hour} * * * root {RETENTION_COMMAND} >> {RETENTION_LOG} 2>&1\n"
    )
    logrotate = f"{RETENTION_LOG} {{\n    weekly\n    rotate 4\n    compress\n    missingok\n    notifempty\n}}\n"
    print(f"==> Installing {RETENTION_CRON_FILE} (daily at {hour:02d}:00)")
    for path, content, mode in ((RETENTION_CRON_FILE, cron, "644"), ("/etc/logrotate.d/framewrite-retention", logrotate, "644")):
        tmp = f"/tmp/fw-{uuid.uuid4().hex}"
        c.run(f"cat > {tmp} << 'FRAMEWRITE_EOF'\n{content}FRAMEWRITE_EOF")
        c.sudo(f"mv {tmp} {path}")
        c.sudo(f"chown root:root {path}")
        c.sudo(f"chmod {mode} {path}")
    c.sudo("systemctl enable --now cron", warn=True)
    print("Done. Check it with: fab ... retention-status")


@task
def retention_run(c, delete=False):
    """Runs the retention sweep right now. By default it's a DRY RUN: it lists
    what would be deleted (and how much space it would free) without deleting
    anything -- read it, then add --delete to actually clean up. Uses the same
    code path as the nightly cron.

    Usage:
        fab ... retention-run             # preview only
        fab ... retention-run --delete    # really delete
    """
    flag = "" if delete else " --dry-run"
    c.sudo(f"bash -c '{RETENTION_COMMAND}{flag}'")


@task
def cap_journal(c, size="200M"):
    """Caps the systemd journal (/var/log/journal) at `size` and trims it now.
    Left alone it can reach gigabytes. This DELETES old journal entries beyond
    the cap (application logs live in Docker's own logs, not here); it also
    writes /etc/systemd/journald.conf.d/framewrite.conf so the cap persists.

    Usage:
        fab ... cap-journal
        fab ... cap-journal --size=500M
    """
    size = str(size)
    if not re.fullmatch(r"[1-9][0-9]*[KMG]", size):
        print("ERROR: --size must look like 200M, 1G or 500K.")
        raise SystemExit(1)
    conf = f"[Journal]\nSystemMaxUse={size}\n"
    tmp = f"/tmp/fw-{uuid.uuid4().hex}"
    c.sudo("mkdir -p /etc/systemd/journald.conf.d")
    c.run(f"cat > {tmp} << 'FRAMEWRITE_EOF'\n{conf}FRAMEWRITE_EOF")
    c.sudo(f"mv {tmp} /etc/systemd/journald.conf.d/framewrite.conf")
    c.sudo("systemctl restart systemd-journald")
    c.sudo(f"journalctl --vacuum-size={size}")
    c.sudo("journalctl --disk-usage")
