from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from typing import Any


APP_NAME = "AiCadConstraint"
CREDENTIAL_TARGET = "AiCadConstraint/OpenAI"
CREDENTIAL_TARGETS = {
    "openai": CREDENTIAL_TARGET,
    "deepseek": "AiCadConstraint/DeepSeek",
}
DEFAULT_CONFIG = {
    # Agent-first is the product default. A caller must explicitly opt into
    # `auto` or `openai` before this local compiler looks for an API key.
    "provider": "offline",
    "model": "gpt-5.4-mini",
    "base_url": "https://api.openai.com/v1",
    "timeout_seconds": 90,
}


def app_data_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return base / APP_NAME


def config_path() -> Path:
    return app_data_dir() / "config.json"


def load_config() -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    path = config_path()
    if path.is_file():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                config.update({key: value[key] for key in DEFAULT_CONFIG if key in value})
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    if os.environ.get("OPENAI_BASE_URL"):
        config["base_url"] = os.environ["OPENAI_BASE_URL"].rstrip("/")
    if config.get("provider") == "deepseek" and os.environ.get("DEEPSEEK_BASE_URL"):
        config["base_url"] = os.environ["DEEPSEEK_BASE_URL"].rstrip("/")
    return config


def save_config(updates: dict[str, Any]) -> Path:
    config = load_config()
    config.update({key: value for key, value in updates.items() if key in DEFAULT_CONFIG})
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD), ("Attributes", wintypes.LPVOID),
        ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
    ]


def get_api_key(provider: str = "openai") -> str | None:
    if provider not in CREDENTIAL_TARGETS:
        raise ValueError("provider must be openai or deepseek")
    env_name = "OPENAI_API_KEY" if provider == "openai" else "DEEPSEEK_API_KEY"
    env_key = os.environ.get(env_name)
    if env_key:
        return env_key.strip()
    if os.name != "nt":
        return None
    pointer = ctypes.POINTER(CREDENTIALW)()
    advapi = ctypes.WinDLL("Advapi32.dll")
    credential_target = CREDENTIAL_TARGETS[provider]
    if not advapi.CredReadW(credential_target, 1, 0, ctypes.byref(pointer)):
        return None
    try:
        credential = pointer.contents
        raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        return raw.decode("utf-16-le")
    finally:
        advapi.CredFree(pointer)


def set_api_key(api_key: str, provider: str = "openai") -> None:
    if provider not in CREDENTIAL_TARGETS:
        raise ValueError("provider must be openai or deepseek")
    if os.name != "nt":
        raise RuntimeError("Windows Credential Manager is required")
    value = api_key.strip()
    if not value:
        raise ValueError("API key cannot be empty")
    raw = value.encode("utf-16-le")
    blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    credential = CREDENTIALW()
    credential.Type, credential.TargetName, credential.CredentialBlobSize = 1, CREDENTIAL_TARGETS[provider], len(raw)
    credential.CredentialBlob, credential.Persist, credential.UserName = blob, 2, f"{provider.title()} API"
    if not ctypes.WinDLL("Advapi32.dll").CredWriteW(ctypes.byref(credential), 0):
        raise ctypes.WinError()


def delete_api_key(provider: str = "openai") -> bool:
    if provider not in CREDENTIAL_TARGETS:
        raise ValueError("provider must be openai or deepseek")
    if os.name != "nt":
        return False
    result = ctypes.WinDLL("Advapi32.dll").CredDeleteW(CREDENTIAL_TARGETS[provider], 1, 0)
    if result:
        return True
    error = ctypes.get_last_error()
    if error == 1168:
        return False
    raise ctypes.WinError(error)
