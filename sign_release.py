#!/usr/bin/env python3
"""
CyberClean — ký release artifact bằng Ed25519, đồng thời sinh .sha256
(giữ lại .sha256 chỉ để tương thích ngược cho app đời cũ < 3.0.2 — xem
_legacy_verify_sha256 trong updater.py. Từ 3.0.2 trở đi, .sig mới là
căn cứ xác thực thật sự).

CÁCH DÙNG:
    # Private key lấy từ biến môi trường (khuyến nghị — dùng trong CI):
    export CYBERCLEAN_SIGNING_KEY="<private key b64 từ gen_release_key.py>"
    python3 sign_release.py dist/CyberClean-3.0.2-linux-x86_64.tar.gz

    # Hoặc từ file (dùng khi ký thủ công trên máy local):
    python3 sign_release.py dist/CyberClean-3.0.2-linux-x86_64.tar.gz \
        --key-file cyberclean_release_private.key

Kết quả: sinh ra 2 file cạnh file gốc:
    CyberClean-3.0.2-linux-x86_64.tar.gz.sig      <- upload lên GitHub Release
    CyberClean-3.0.2-linux-x86_64.tar.gz.sha256   <- upload lên GitHub Release

KHÔNG BAO GIỜ commit private key hoặc file chứa nó vào git.
"""
import argparse
import base64
import hashlib
import os
import sys
from pathlib import Path


def load_private_key(key_file: str | None):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    raw_b64 = os.environ.get("CYBERCLEAN_SIGNING_KEY")
    if not raw_b64 and key_file:
        raw_b64 = Path(key_file).read_text().strip()
    if not raw_b64:
        print(
            "✗  Không tìm thấy private key. Set biến môi trường "
            "CYBERCLEAN_SIGNING_KEY hoặc dùng --key-file <path>.",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        raw = base64.b64decode(raw_b64)
        return Ed25519PrivateKey.from_private_bytes(raw)
    except Exception as e:
        print(f"✗  Private key không hợp lệ: {e}", file=sys.stderr)
        sys.exit(1)


def sign_file(path: Path, private_key) -> Path:
    data = path.read_bytes()
    signature = private_key.sign(data)
    sig_path = path.with_suffix(path.suffix + ".sig")
    sig_path.write_text(base64.b64encode(signature).decode() + "\n")
    return sig_path


def sha256_file(path: Path) -> Path:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    sha_path = path.with_suffix(path.suffix + ".sha256")
    sha_path.write_text(f"{h.hexdigest()}  {path.name}\n")
    return sha_path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("artifacts", nargs="+", help="File(s) to sign, e.g. dist/CyberClean-3.0.2-linux-x86_64.tar.gz")
    ap.add_argument("--key-file", help="Path to private key file (alternative to CYBERCLEAN_SIGNING_KEY env var)")
    args = ap.parse_args()

    private_key = load_private_key(args.key_file)

    for artifact in args.artifacts:
        path = Path(artifact)
        if not path.is_file():
            print(f"✗  Not found: {path}", file=sys.stderr)
            sys.exit(1)

        sig_path = sign_file(path, private_key)
        sha_path = sha256_file(path)

        print(f"✓  Signed: {path.name}")
        print(f"   -> {sig_path.name}")
        print(f"   -> {sha_path.name}")
        print(f"\n   Upload all 3 files to the GitHub Release:")
        print(f"   gh release upload v<VERSION> {path} {sig_path} {sha_path}\n")


if __name__ == "__main__":
    main()
