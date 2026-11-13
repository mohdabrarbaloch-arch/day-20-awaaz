"""Tests for password hashing and JWT handling."""

from __future__ import annotations

import pytest

from app.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        h = hash_password("mypassword123")
        assert h != "mypassword123"
        assert h.startswith("$2")

    def test_verify_correct_password(self):
        h = hash_password("mypassword123")
        assert verify_password("mypassword123", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("mypassword123")
        assert verify_password("different123", h) is False

    def test_same_password_different_salt(self):
        a = hash_password("samepassword1")
        b = hash_password("samepassword1")
        assert a != b  # bcrypt salts each hash
        assert verify_password("samepassword1", a)
        assert verify_password("samepassword1", b)

    def test_over_72_bytes_rejected(self):
        with pytest.raises(ValueError, match="72 bytes"):
            hash_password("a" * 100)

    def test_verify_against_garbage_returns_false(self):
        assert verify_password("anything", "not-a-hash") is False


class TestJwt:
    def test_roundtrip(self):
        token = create_access_token(42)
        assert decode_token(token) == "42"

    def test_tampered_token_rejected(self):
        token = create_access_token(1)
        tampered = token[:-4] + "aaaa"
        assert decode_token(tampered) is None

    def test_garbage_token_rejected(self):
        assert decode_token("not.a.jwt") is None

    def test_empty_token_rejected(self):
        assert decode_token("") is None

    def test_expired_token_rejected(self):
        token = create_access_token(1, expires_minutes=-1)
        assert decode_token(token) is None

    def test_different_subjects_differ(self):
        assert decode_token(create_access_token(1)) != decode_token(create_access_token(2))
