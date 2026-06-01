import hashlib

APPCODE = "cosy"
SECRET = "d2FyLCB3YXIgbmV2ZXIgY2hhbmdlcw=="
SEP = "&"


def sign_center_request(date: str) -> str:
    return _md5(f"{APPCODE}{SEP}{SECRET}{SEP}{date}")


def sign_qoder_request(
    payload_b64: str,
    cosy_key: str,
    cosy_date: str,
    body: str,
    path_without_algo: str,
) -> str:
    return _md5(f"{payload_b64}\n{cosy_key}\n{cosy_date}\n{body}\n{path_without_algo}")


def compose_bearer(payload_b64: str, signature: str) -> str:
    return f"Bearer COSY.{payload_b64}.{signature}"


def _md5(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()
