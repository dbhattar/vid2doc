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

`.env` is never touched by any task here on purpose -- it holds production
secrets (Stripe keys, JWT secret, DB password) that shouldn't be scripted
into a file that gets committed or passed around. Create it by hand, once.
"""

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


@task
def restart(c):
    """Restarts the stack without rebuilding -- e.g. after editing .env by
    hand, since env_file changes aren't picked up by a running container."""
    c.sudo(f"bash -c 'cd {APP_DIR}/backend && docker compose restart'")
    c.sudo(f"bash -c 'cd {APP_DIR}/backend && docker compose ps'")


@task
def logs(c, service="api", lines=100):
    """Tails logs for one service: api (default), worker, frontend, or postgres."""
    c.sudo(f"bash -c 'cd {APP_DIR}/backend && docker compose logs --tail {lines} {service}'")
