import base64
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7
except ImportError:  # pragma: no cover
    serialization = padding = Cipher = algorithms = modes = PKCS7 = None

SERVER_PUBKEY_PEM = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDA8iMH5c02LilrsERw9t6Pv5Nc
4k6Pz1EaDicBMpdpxKduSZu5OANqUq8er4GM95omAGIOPOh+Nx0spthYA2BqGz+l
6HRkPJ7S236FZz73In/KVuLnwI8JJ2CbuJap8kvheCCZpmAWpb/cPx/3Vr/J6I17
XcW+ML9FoCI6AOvOzwIDAQAB
-----END PUBLIC KEY-----"""


@dataclass(frozen=True)
class AuthIdentity:
    name: str = ""
    aid: str = ""
    uid: str = ""
    yx_uid: str = ""
    organization_id: str = ""
    organization_name: str = ""
    user_type: str = "personal_standard"
    security_oauth_token: str = ""
    refresh_token: str = ""


@dataclass(frozen=True)
class MachineIdentity:
    machine_id: str
    machine_token: str
    machine_type: str


@dataclass(frozen=True)
class SessionContext:
    temp_key: bytes
    cosy_key: str
    info: str
    identity: AuthIdentity
    machine: MachineIdentity


class SessionBuilder:
    @staticmethod
    def auth_payload_json(identity: AuthIdentity) -> bytes:
        payload = {
            "name": identity.name,
            "aid": identity.aid,
            "uid": identity.uid,
            "yx_uid": identity.yx_uid,
            "organization_id": identity.organization_id,
            "organization_name": identity.organization_name,
            "user_type": identity.user_type,
            "security_oauth_token": identity.security_oauth_token,
            "refresh_token": identity.refresh_token,
        }
        return json.dumps(payload, separators=(",", ":")).encode()

    @staticmethod
    def build_payload_b64(info: str, request_id: str | None = None) -> str:
        payload: dict[str, Any] = {
            "cosyVersion": "0.1.43",
            "ideVersion": "",
            "info": info,
            "requestId": request_id or str(uuid4()),
            "version": "v1",
        }
        encoded = json.dumps(dict(sorted(payload.items())), separators=(",", ":")).encode()
        return base64.b64encode(encoded).decode()

    @staticmethod
    def new_session(
        identity: AuthIdentity,
        machine: MachineIdentity,
        temp_key: bytes | None = None,
    ) -> SessionContext:
        temp_key = temp_key or uuid4().hex[:16].encode("ascii")
        cosy_key = base64.b64encode(SessionBuilder.rsa_encrypt(temp_key)).decode()
        info = base64.b64encode(
            SessionBuilder.aes_encrypt(SessionBuilder.auth_payload_json(identity), temp_key)
        ).decode()
        return SessionContext(
            temp_key=temp_key,
            cosy_key=cosy_key,
            info=info,
            identity=identity,
            machine=machine,
        )

    @staticmethod
    def rsa_encrypt(value: bytes) -> bytes:
        if serialization is None or padding is None:
            raise RuntimeError("cryptography is required for Qoder session encryption")
        public_key = serialization.load_pem_public_key(SERVER_PUBKEY_PEM.encode())
        return public_key.encrypt(value, padding.PKCS1v15())

    @staticmethod
    def aes_encrypt(value: bytes, key: bytes) -> bytes:
        if Cipher is None or algorithms is None or modes is None or PKCS7 is None:
            raise RuntimeError("cryptography is required for Qoder session encryption")
        padder = PKCS7(128).padder()
        padded = padder.update(value) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key), modes.CBC(key)).encryptor()
        return encryptor.update(padded) + encryptor.finalize()
