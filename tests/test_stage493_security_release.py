"""Stage 493 release invariants and synthetic ciphertext from stage 492 image."""
from pathlib import Path
import sys

import cryptography
from secret_manager import decrypt_secret_payload


ROOT = Path(__file__).resolve().parents[1]
# Generated with secret_manager.encrypt_secret_payload in the accepted stage 492
# candidate image (image ID sha256:7887ef41cb942e2acc44844248cf97010c32a4a94096b8a297d72f9c10c7851b).
# Payload and key are synthetic; this exercises the stored-credentials format.
OLD_TOKEN = (
    "gAAAAABrA2uqo-iG3u2cxsSA2t6OHG8_mmyyHh4ZtzGbPi95-GHAGdgwiulTaLGY0V"
    "kfSsAPzY1GKSyjjOL0wnJe2VGqBIXDikvGpKZWoO1BcpzrEWQdC_zUK6U88ksnT"
    "BNufosYD2jdEkowGBFQFhOes2yayOwLeQ=="
)


def test_pins_verified_31216_base_and_cryptography_50():
    assert sys.version_info[:3] == (3, 12, 16)
    assert cryptography.__version__ == "50.0.2"
    assert "sha256:d632bda0952ef8a17cd233c1f50b987c6ea31423e9b797aad792fd8f8762e336" in (ROOT / "Dockerfile").read_text()
    assert '"cryptography>=50,<51"' in (ROOT / "pyproject.toml").read_text()


def test_stage492_ciphertext_decrypts_after_upgrade(monkeypatch):
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    assert decrypt_secret_payload(OLD_TOKEN) == {
        "api_key": "synthetic-legacy", "domain": "example.test"
    }
