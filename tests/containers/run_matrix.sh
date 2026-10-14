#!/usr/bin/env bash
# Dry-run CyberClean trên nhiều distro bằng container (docker hoặc podman).
#
#   tests/containers/run_matrix.sh                 # tất cả
#   tests/containers/run_matrix.sh ubuntu fedora   # chọn vài cái
#
# Không đụng máy thật: mã nguồn được mount READ-ONLY, mỗi container dùng HOME riêng.
# Mục đích: bắt lỗi "chạy được trên Arch của tôi nhưng vỡ trên Fedora/openSUSE".
# LƯU Ý: script này CHƯA được chạy trong môi trường tạo ra nó (không có docker/podman) —
# harness Python bên trong (dryrun_harness.py) thì đã chạy trên Ubuntu; xem tests/test_containers_harness.py.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
RUNTIME="${CONTAINER_RUNTIME:-$(command -v podman || command -v docker || true)}"
[[ -n "$RUNTIME" ]] || { echo "need docker or podman" >&2; exit 2; }

# name | image | expected package manager | install python + psutil
declare -A IMAGE=( [ubuntu]=ubuntu:24.04 [debian]=debian:12 [fedora]=fedora:40 [arch]=archlinux:latest
                   [opensuse]=opensuse/tumbleweed [alpine]=alpine:3.20 [void]=ghcr.io/void-linux/void-glibc:latest )
declare -A PM=( [ubuntu]=apt [debian]=apt [fedora]=dnf [arch]=pacman [opensuse]=zypper [alpine]=apk [void]=xbps )
declare -A SETUP=(
  [ubuntu]="apt-get update -qq && apt-get install -y -qq python3 python3-psutil"
  [debian]="apt-get update -qq && apt-get install -y -qq python3 python3-psutil"
  [fedora]="dnf install -y -q python3 python3-psutil"
  [arch]="pacman -Sy --noconfirm python python-psutil"
  [opensuse]="zypper --non-interactive install -y python3 python3-psutil"
  [alpine]="apk add --no-cache python3 py3-psutil bash"
  [void]="xbps-install -Sy python3 python3-psutil"
)
WANT=("$@"); [[ ${#WANT[@]} -gt 0 ]] || WANT=(ubuntu debian fedora arch opensuse alpine void)

fail=0
for name in "${WANT[@]}"; do
  echo "════════ $name (${IMAGE[$name]}) ════════"
  if ! "$RUNTIME" run --rm -v "$ROOT:/src:ro" -e HOME=/tmp/home "${IMAGE[$name]}" sh -c \
      "set -e; ${SETUP[$name]}; mkdir -p /tmp/home/.cache/thumbnails /tmp/home/.config; \
       python3 /src/tests/containers/dryrun_harness.py --expect-pm ${PM[$name]} --home /tmp/home" \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["distro"], d["pm"], "targets:", [t["id"] for t in d["targets"]]); print("errors:", d["errors"]); sys.exit(1 if d["errors"] else 0)'
  then echo "✗ $name FAILED"; fail=1; else echo "✓ $name ok"; fi
done
exit $fail
