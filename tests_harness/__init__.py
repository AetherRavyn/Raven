"""Shared test fixtures and fakes for the RAVEN test suite.

The modules here are test infrastructure only.  They are imported
by ``tests/conftest.py`` (autouse fixtures) and by individual
test files that want a specific fake.

Modules:

  * ``fake_helix`` — :class:`FakeHelixClient`, an in-process stand-in
    for :class:`app.db.helix.HelixClient` so the live HelixDB
    integration tests can run in CI without a Docker gateway.
"""
