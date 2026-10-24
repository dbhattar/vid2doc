# Local gVisor sandbox in a Lima Linux VM

## Context
To test long-running agents under isolation, the user wants gVisor (`runsc`) running locally. gVisor is Linux-only, and the machine is an Apple Silicon Mac (arm64, macOS 26.3) with Docker Desktop and UTM installed but no Lima. Decisions made with the user: use **Lima** to create the VM (repeatable from one YAML file), and for this first step **only prove gVisor works** with Docker + the `runsc` runtime (no Framewrite containers yet). This is a standalone local dev aid; it does not touch the product code.

## Approach
A single Lima config provisions an Ubuntu 24.04 arm64 VM with Docker and gVisor, then a short README gives the commands and the checks. Nested virtualization is **not** needed: gVisor's default `systrap` platform works inside a plain VM (only the `kvm` platform needs nested virt).

### Files (new, under `local_test/gvisor/` — local experiments live there; `deploy/` is for production provisioning)
1. `local_test/gvisor/lima-gvisor.yaml`:
   - `vmType: vz` (Apple Virtualization.framework), `arch: aarch64`, `cpus: 4`, `memory: 6GiB`, `disk: 30GiB`.
   - `images`: Ubuntu 24.04 server cloud image for arm64 (`cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-arm64.img`).
   - `mounts: []` and no containerd: the VM is deliberately isolated from the Mac's home directory, and we use Docker only.
   - One system `provision` script (idempotent, `set -eux`):
     1. Install Docker (`apt-get install -y docker.io`) and add the Lima user (`$LIMA_CIDATA_USER`) to the `docker` group.
     2. Add gVisor's signed apt repo (`gvisor.dev/archive.key` keyring + `storage.googleapis.com/gvisor/releases release main` source) and `apt-get install -y runsc`.
     3. `runsc install` (registers the `runsc` runtime in `/etc/docker/daemon.json`), then `systemctl restart docker`.
   - `probes`: wait until `docker info` works and `runsc` appears under Runtimes, so `limactl start` only returns when the VM is actually ready.
2. `local_test/gvisor/README.md` — prerequisites, commands, verification, cleanup, gotchas (below).

### Commands the README documents
```
brew install lima
limactl start --name=gvisor local_test/gvisor/lima-gvisor.yaml   # first run: a few minutes
limactl shell gvisor                                              # shell in the VM
limactl stop gvisor / limactl delete gvisor                       # cleanup
```
(Optional, noted but not required: forward the VM's Docker socket to the Mac and create a `docker context` for it. Default is to run docker via `limactl shell gvisor docker ...` so it can't be confused with Docker Desktop.)

### Verification (documented as copy-paste checks, all run inside the VM)
1. `docker info | grep -i runtimes` lists `runsc`.
2. `docker run --rm --runtime=runsc alpine uname -r` prints `4.19.0-gvisor` (gVisor's emulated kernel; observed on the release installed 2026-10-17), versus the VM's real 6.x kernel with the default runtime.
3. `docker run --rm --runtime=runsc alpine dmesg` shows gVisor's boot messages ("Starting gVisor...").
4. Long-running check: `docker run -d --runtime=runsc --name gv-long alpine sh -c 'while true; do date >> /tmp/beat; sleep 5; done'`; confirm it stays up (`docker ps`), watch `docker stats gv-long`, `docker exec gv-long tail /tmp/beat`, then `docker rm -f gv-long`.
5. Isolation spot-check: inside a `runsc` container, `cat /proc/version` and reading a host-only path both reflect the sandbox, not the VM.

### Gotchas to call out in the README
- Apple Silicon: the base image must be `arm64`/`aarch64`, and container images need arm64 variants (alpine/ubuntu are fine).
- gVisor is not a full Linux: some syscalls/`/proc`/`/sys` features are missing, so a workload that fails only under `runsc` is the signal we're testing for. Compare against `--runtime=runc` in the same VM.
- Docker Desktop on the Mac is untouched and separate; the commands above only affect the Lima VM.
- If `vz` is unavailable, set `vmType: qemu` (slower).
- `runsc` flags (e.g. `--platform`, `--network`) go in `daemon.json` `runtimeArgs` if we later want to tune them; not needed for the minimal setup.

## Out of scope (next steps once this works)
Running the Framewrite backend/worker under `runsc` via the compose files, resource limits/network policy for agent sandboxes, KVM platform with nested virtualization, a containerd/Kubernetes-based setup.

## Verification of the deliverable
After approval: write the two files, then actually run it on this Mac — `brew install lima`, `limactl start`, and the five checks above — and report real outputs. Per AGENTS.md, copy this plan to `plan/gvisor-local-sandbox-plan.md` in the repo.
