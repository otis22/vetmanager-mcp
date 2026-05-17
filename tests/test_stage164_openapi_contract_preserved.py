from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path


def load_contract_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "check_openapi_artifact_contract_preserved.py"
    spec = importlib.util.spec_from_file_location("check_openapi_artifact_contract_preserved", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def minimal_openapi():
    return {
        "components": {
            "schemas": {
                "user": {
                    "properties": {
                        "passwd": {
                            "type": "string",
                            "example": "abcd1234abcd1234abcd1234abcd1234",
                            "x-db-type": "varchar(32)",
                        }
                    }
                },
                "invoice": {
                    "properties": {
                        "doctor": {
                            "example": {
                                "passwd": "abcd1234abcd1234abcd1234abcd1234",
                            }
                        }
                    }
                },
            }
        }
    }


def test_contract_check_allows_scalar_value_sanitization_only():
    module = load_contract_module()
    before = minimal_openapi()
    baseline = module.build_baseline(before, "test-sha")
    after = deepcopy(before)
    after["components"]["schemas"]["user"]["properties"]["passwd"]["example"] = "0" * 32
    after["components"]["schemas"]["invoice"]["properties"]["doctor"]["example"]["passwd"] = "0" * 32

    assert module.check_contract(after, baseline) == []


def test_contract_check_rejects_structure_or_passwd_shape_changes():
    module = load_contract_module()
    before = minimal_openapi()
    baseline = module.build_baseline(before, "test-sha")
    after = deepcopy(before)
    after["components"]["schemas"]["invoice"]["properties"]["doctor"]["extra"] = {}
    after["components"]["schemas"]["user"]["properties"]["passwd"]["x-db-type"] = "varchar(64)"
    after["components"]["schemas"]["invoice"]["properties"]["doctor"]["example"]["passwd"] = "short"

    errors = module.check_contract(after, baseline)
    assert "OpenAPI structural fingerprint differs from Stage 164 baseline" in errors
    assert "passwd schema context differs from Stage 164 baseline" in errors
    assert "passwd schema x-db-type is not varchar(32)" in errors
    assert any("does not preserve 32-character shape" in error for error in errors)
