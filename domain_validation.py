"""Vetmanager clinic domain validation."""

import re

from exceptions import VetmanagerError

DOMAIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

# Stage 196: hostname suffixes users paste along with the clinic subdomain.
_KNOWN_HOST_SUFFIXES = (".vetmanager.ru", ".vetmanager.cloud")


def normalize_domain_input(raw: str) -> str:
    """Normalize user-entered clinic domain before validation.

    Mobile keyboards auto-capitalize the first letter and users often paste
    the full clinic URL; both used to fail the strict lowercase pattern.
    Accepts "MyClinic", "https://myclinic.vetmanager.ru/", "myclinic.vetmanager.cloud"
    and reduces them all to "myclinic". Unknown shapes pass through for
    validate_domain to reject with a format error.
    """
    domain = raw.strip().lower()
    for scheme in ("https://", "http://"):
        if domain.startswith(scheme):
            domain = domain[len(scheme):]
            break
    domain = domain.split("/", 1)[0].split("?", 1)[0]
    domain = domain.rstrip(".")
    for suffix in _KNOWN_HOST_SUFFIXES:
        if domain.endswith(suffix):
            domain = domain[: -len(suffix)]
            break
    return domain


def validate_domain(domain: str) -> str:
    """Validate and return a Vetmanager clinic subdomain.

    Input is normalized first (see normalize_domain_input), so values like
    "MyClinic" or "https://myclinic.vetmanager.ru" validate to "myclinic".

    Args:
        domain: Clinic subdomain (e.g. "myclinic") or a pasted clinic URL.

    Returns:
        The validated, normalized domain string.

    Raises:
        VetmanagerError: If the domain format is invalid after normalization.
    """
    normalized = normalize_domain_input(domain)
    if not DOMAIN_PATTERN.fullmatch(normalized):
        raise VetmanagerError(
            "Invalid Vetmanager domain format. Use clinic subdomain like 'myclinic'."
        )
    return normalized


# ── IP mask validation and matching ──────────────────────────────────────────

_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_OCTET_OR_WILDCARD = rf"(?:{_OCTET}|\*)"
_IP_MASK_PATTERN = re.compile(
    rf"^{_OCTET_OR_WILDCARD}\.{_OCTET_OR_WILDCARD}\.{_OCTET_OR_WILDCARD}\.{_OCTET_OR_WILDCARD}$"
)


def validate_ip_mask(mask: str) -> str:
    """Validate IP mask format: 4 dot-separated octets, each 0-255 or '*'.

    Raises ValueError for invalid masks including '0.0.0.0'.
    Returns the validated mask string.
    """
    mask = mask.strip()
    if not _IP_MASK_PATTERN.fullmatch(mask):
        raise ValueError(
            "IP mask must be 4 dot-separated octets, each 0-255 or '*' "
            "(e.g., '192.168.1.*', '*.*.*.*')."
        )
    if mask == "0.0.0.0":
        raise ValueError("IP mask '0.0.0.0' is not allowed.")
    return mask


def ip_matches_mask(ip_address: str, mask: str) -> bool:
    """Check if an IP address matches an IP mask pattern.

    Each octet in the mask is either a specific number or '*' (wildcard).
    Returns True if the IP matches, False otherwise.
    """
    if mask == "*.*.*.*":
        return True
    ip_parts = ip_address.split(".")
    mask_parts = mask.split(".")
    if len(ip_parts) != 4 or len(mask_parts) != 4:
        return False
    for ip_octet, mask_octet in zip(ip_parts, mask_parts):
        if mask_octet == "*":
            continue
        if ip_octet != mask_octet:
            return False
    return True
