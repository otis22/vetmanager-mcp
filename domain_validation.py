"""Vetmanager clinic domain validation."""

import re

from exceptions import VetmanagerError

DOMAIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def validate_domain(domain: str) -> str:
    """Validate and return a Vetmanager clinic subdomain.

    Args:
        domain: Clinic subdomain (e.g. "myclinic").

    Returns:
        The validated domain string.

    Raises:
        VetmanagerError: If the domain format is invalid.
    """
    if not DOMAIN_PATTERN.fullmatch(domain):
        raise VetmanagerError(
            "Invalid Vetmanager domain format. Use clinic subdomain like 'myclinic'."
        )
    return domain
