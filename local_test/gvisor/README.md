# Local gVisor sandbox (Lima VM)

A throwaway Ubuntu 24.04 arm64 VM on your Mac with Docker and
[gVisor](https://gvisor.dev) (`runsc`), for checking how long-running agent
workloads behave inside a sandbox. gVisor only runs on Linux, hence the VM.
Nothing is shared from your Mac into it, and Docker Desktop is untouched.

## Setup

```bash
brew install lima
limactl start --name=gvisor local_test/gvisor/lima-gvisor.yaml   # first run takes a few minutes
limactl restart gvisor                                            # once, so the new `docker` group applies
limactl shell gvisor                                              # shell inside the VM
```

Everything below runs inside that shell (or prefix with `limactl shell gvisor`).

## Check it works

```bash
docker info | grep -i runtimes                          # lists runsc
uname -r                                                # the VM's real kernel (6.x)
docker run --rm --runtime=runsc alpine uname -r         # 4.19.0-gvisor -- gVisor's emulated kernel (version varies by release)
docker run --rm --runtime=runsc alpine dmesg            # gVisor boot messages
```

Long-running check:

```bash
docker run -d --runtime=runsc --name gv-long alpine \
  sh -c 'while true; do date >> /tmp/beat; sleep 5; done'
docker ps                                               # still up
docker stats --no-stream gv-long                        # memory/CPU of the sandbox
docker exec gv-long tail -3 /tmp/beat                   # heartbeat keeps advancing
docker rm -f gv-long
```

Compare behavior with the normal runtime in the same VM by swapping
`--runtime=runsc` for `--runtime=runc`. A workload that works under `runc`
but fails under `runsc` is exactly what this setup is for finding.

## Cleanup

```bash
limactl stop gvisor      # keep the VM
limactl delete gvisor    # remove it entirely
```

## Notes

- Without the one-time `limactl restart`, `docker` fails with "permission denied" on
  the socket: the VM's already-open SSH session predates the group change.
- Apple Silicon: the VM is `aarch64`, so container images need arm64 variants
  (alpine and ubuntu are fine).
- gVisor is not a complete Linux: some syscalls and `/proc`, `/sys` features
  are missing or differ.
- Uses gVisor's default `systrap` platform, which needs no nested
  virtualization. The `kvm` platform would.
- If `vmType: vz` isn't available on your macOS, change it to `qemu` (slower).
- Runtime flags (e.g. `--network`) go under `runtimes.runsc.runtimeArgs` in the
  VM's `/etc/docker/daemon.json`; not needed for this minimal setup.
