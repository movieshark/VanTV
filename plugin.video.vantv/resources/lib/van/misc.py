from base64 import b64encode

from Cryptodome.Cipher import PKCS1_v1_5
from Cryptodome.PublicKey import RSA


def encrypt_password(password: str, public_key: str) -> str:
    """
    Encrypt the password with the public key using PKCS#1 v1.5.

    :param password: The password.
    :param public_key: The public key.
    :return: The encrypted password.
    """
    rsa_key = RSA.importKey(public_key)
    cipher = PKCS1_v1_5.new(rsa_key)
    return b64encode(cipher.encrypt(password.encode("utf-8"))).decode("utf-8")
