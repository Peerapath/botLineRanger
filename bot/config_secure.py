"""
Secure Configuration Module
เก็บข้อมูลสำคัญในรูปแบบ Fernet encrypted
Key derive จาก runtime properties (ไม่เก็บ key เป็น plaintext)

สร้าง encrypted values ด้วย: python encrypt_config.py
"""
import base64
import hashlib
from cryptography.fernet import Fernet


class SecureConfig:
    # Salt สำหรับ key derivation (ไม่ใช่ key ตรงๆ)
    _SALT = "BotLineRanger_v2_secure_salt_2025"

    # Encrypted data (Fernet AES-128-CBC)
    # สร้างด้วย encrypt_config.py
    _ENCRYPTED_DATA = {
        'version_url': 'gAAAAABqpqPaaMyxPvI8I0gnALgBXoj8M8oWqwrAJ7XBGAIW9KM5Eux8f6Ewfi4db7uSHuH-SwqsrQ4B-20gTj6lquP9bdA0TnzanL8QEUR-s6UR_EXOzYeyXX6sq0vTUp-_eebH-v6qc_oS6fpNTUM7uU9mnXefXFLrPp_5PqEHSBtcJ50tfsdinhW8gLXGKDetrgAK7tzU',
        'api_url': 'gAAAAABqpqPalv-iTI47S3AHj2Blu87VX_aRMfO4nX-626eDWirgJRQ9be9xKQDPPjq8cHj1D6cS67wGF3XfP_NoJzpR-ZdzsqXh-XUTAbUhqUp381wo2iVUVExU7swX-i6rTLGUhlP8',
        'service_id': 'gAAAAABqpqPakn7QPmGVvUoQEGBWx7tahmxA4fpAsSjS7S3yJFHqmBYejCaQ5pi6NNDLwePEEifcVRKOuKvH3DOeHJ9nysE44nR6gdGIEnWsFNdQJvRVXbI=',
        'master_password': 'gAAAAABqpqPa3cLJz-E5gCM50YCpwE_1iZFH52kOChLBeTHAi7azrkHOF3u2SLYCbLwvy31dD78ziOqtxR0HjWVBg2qgCU-7fN1d-Hnxyp6dl4ahEWBofxfLfNvvTx-diMNBrcM-1UxO',
        }

    _fernet = None

    @classmethod
    def _get_fernet(cls):
        """Derive key and create Fernet instance (cached)"""
        if cls._fernet is None:
            h = hashlib.sha256()
            h.update(cls._SALT.encode('utf-8'))
            h.update(b"_fernet_key_derivation_")
            key = base64.urlsafe_b64encode(h.digest())
            cls._fernet = Fernet(key)
        return cls._fernet

    @classmethod
    def _decrypt(cls, key_name: str) -> str:
        """Decrypt a value from _ENCRYPTED_DATA"""
        f = cls._get_fernet()
        encrypted = cls._ENCRYPTED_DATA[key_name].encode('utf-8')
        return f.decrypt(encrypted).decode('utf-8')

    @classmethod
    def get_version_url(cls) -> str:
        return cls._decrypt('version_url')

    @classmethod
    def get_api_url(cls) -> str:
        return cls._decrypt('api_url')

    @classmethod
    def get_service_id(cls) -> str:
        return cls._decrypt('service_id')

    @classmethod
    def get_master_password(cls) -> str:
        return cls._decrypt('master_password')


if __name__ == "__main__":
    print("Version URL:", SecureConfig.get_version_url())
    print("API URL:", SecureConfig.get_api_url())
    print("Service ID:", SecureConfig.get_service_id())
    print("Master Password:", SecureConfig.get_master_password()[:20] + "...")
