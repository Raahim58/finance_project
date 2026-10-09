"""Offline ingestion contracts and fixtures."""

from app.tests.support.users import signup_user


def _auth(client):
    return signup_user(client, "health@example.com")
