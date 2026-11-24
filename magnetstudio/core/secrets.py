"""Secrets (the Gemini API key) in the OS credential store, not in settings.json.

  Windows  Credential Manager      macOS  Keychain      Linux  Secret Service (GNOME Keyring / KWallet)

Lookup order for the API key: env GEMINI_API_KEY → keyring → legacy plain-text value in settings
(older versions; moved to the keyring by migrate_plaintext_key at startup).

If no keyring backend is available (e.g. a headless Linux box) the app still works: the key is
kept in settings.json as before and a warning is logged once.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

SERVICE = "MagnetStudio"
GEMINI_KEY = "gemini_api_key"
_warned = False


def keyring_available() -> bool:
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:
        return False
    try:
        kr = keyring.get_keyring()
    except Exception:  # noqa: BLE001 – broken backend configuration
        return False
    return not isinstance(kr, fail.Keyring) and getattr(kr, "priority", 1) > 0


def _warn_once(msg: str, *args) -> None:
    global _warned
    if not _warned:
        _warned = True
        log.warning(msg, *args)


def get_secret(name: str) -> str:
    if not keyring_available():
        return ""
    import keyring
    try:
        return keyring.get_password(SERVICE, name) or ""
    except Exception as e:  # noqa: BLE001 – locked keychain, denied access, …
        _warn_once("Cannot read %s from the OS keychain: %s", name, e)
        return ""


def set_secret(name: str, value: str) -> bool:
    """Store (or, for an empty value, delete) a secret. False if no keychain could be used."""
    if not keyring_available():
        _warn_once("No OS keychain available – the API key stays in settings.json")
        return False
    import keyring
    try:
        if value:
            keyring.set_password(SERVICE, name, value)
        else:
            try:
                keyring.delete_password(SERVICE, name)
            except keyring.errors.PasswordDeleteError:
                pass
        return True
    except Exception as e:  # noqa: BLE001
        _warn_once("Cannot write %s to the OS keychain: %s", name, e)
        return False


def get_api_key(settings: dict | None = None) -> str:
    env = os.environ.get("GEMINI_API_KEY", "").strip()
    if env:
        return env
    return (get_secret(GEMINI_KEY) or (settings or {}).get("gemini_api_key") or "").strip()


def store_api_key(settings: dict, value: str) -> str:
    """Save the key from the settings dialog. Returns where it went: 'keychain' or 'settings'."""
    value = (value or "").strip()
    if set_secret(GEMINI_KEY, value):
        settings["gemini_api_key"] = ""  # never keep a copy in plain text
        return "keychain"
    settings["gemini_api_key"] = value
    return "settings"


def migrate_plaintext_key(settings: dict) -> bool:
    """Move a key found in settings.json into the keychain. True if settings changed."""
    plain = (settings.get("gemini_api_key") or "").strip()
    if not plain:
        return False
    if set_secret(GEMINI_KEY, plain):
        settings["gemini_api_key"] = ""
        log.info("Gemini API key moved from settings.json to the OS keychain")
        return True
    return False
