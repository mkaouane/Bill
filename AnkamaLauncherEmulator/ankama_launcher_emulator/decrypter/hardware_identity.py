import hashlib
import secrets
import uuid


def generate_hardware_id() -> str:
    """Keep the SHA1 of a random MAC-like seed stable per account across sessions."""

    numeric_mac = "".join(str(secrets.randbelow(10)) for _ in range(12))
    hardware_id = hashlib.sha1(numeric_mac.encode("utf-8")).hexdigest()
    return hashlib.sha256(hardware_id.encode()).hexdigest().upper()


def generate_machine_guid() -> str:
    return str(uuid.uuid4()).lower()


def derive_machine_guid(hardware_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"hwid:{hardware_id}")).lower()


def derive_computer_name(hardware_id: str) -> str:
    suffix = hashlib.md5(f"comp:{hardware_id}".encode()).hexdigest()[:7].upper()
    return f"DESKTOP-{suffix}"


def derive_user_name(hardware_id: str) -> str:
    suffix = hashlib.md5(f"user:{hardware_id}".encode()).hexdigest()[:6].lower()
    return f"user-{suffix}"


def derive_device_identifier(hardware_id: str) -> str:
    """Unity SystemInfo.deviceUniqueIdentifier on Windows is a 40-character lowercase hex string (SHA1)."""
    return hashlib.sha1(f"unity_device:{hardware_id}".encode("utf-8")).hexdigest().lower()

