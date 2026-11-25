# Security policy

## Supported versions

Security fixes target the latest published release. Upgrade before reporting an issue against an older version.

## Reporting a vulnerability

Please do not open a public issue containing credentials, personal data, exploit instructions, or an unpatched vulnerability. Use GitHub's private vulnerability reporting for this repository, or contact the repository maintainers privately after the project is published.

## Security practices

- Never commit API keys, OAuth client secrets, token files, cookies, or private media.
- Prefer environment variables for API keys and keep OAuth tokens outside the repository.
- Treat URLs and downloaded files as untrusted input.
- ClipRally invokes FFmpeg and yt-dlp with argument arrays, not shell command strings.
- URL ingestion requires explicit rights confirmation and does not attempt DRM or access-control circumvention.
- MCP tools operate on user-supplied local paths. Connect only to trusted MCP hosts and servers.