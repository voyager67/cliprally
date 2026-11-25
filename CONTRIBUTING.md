# Contributing

Thanks for helping improve ClipRally. Keep the local-first contract and avoid adding mandatory API credentials to the clipping path.

## Before opening a pull request

1. Create a virtual environment and install `pip install -e ".[dev]"`.
2. Run `pytest -q` and `ruff check .`.
3. Add or update tests for behavior changes. Prefer local fixtures and mocked network calls.
4. Never include real media without documented rights, API tokens, OAuth secrets, personal data, or downloaded model weights.
5. Update the README when changing CLI flags, optional dependencies, supported platforms, or limitations.

## Design expectations

- Core clipping must work with a local video file and no API credentials.
- External network behavior must be opt-in, documented, and testable with mocks.
- Do not bypass DRM, paywalls, private content controls, platform policies, or rate limits.
- Prefer small provider adapters behind simple interfaces.
- Keep logs free of access tokens and sensitive content.