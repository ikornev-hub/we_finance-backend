"""Пароли: Храним только хеш Argon2id, сам пароль - нигде."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Хеш с солью; один и тот же пароль каждый раз дает разный хеш"""
    return _hasher.hash(password)


def check_password(password_hash: str | None, password: str) -> bool:
    """Подходит ли пароль. Нет хеша - вход не настроен - False."""
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError, InvalidHashError:
        return False
