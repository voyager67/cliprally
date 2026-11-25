# Optional platform integrations

These integrations are not needed to create clips. They are separate, user-initiated operations and require the developer app, credentials, permissions, and account eligibility controlled by each platform. The adapter tests in this repository use mocked HTTP responses; they do not prove that a particular live account or app will be approved or allowed to publish.

## YouTube Shorts

Install the optional client packages:

```bash
python -m pip install -e ".[youtube-publish]"
```

Enable YouTube Data API v3 in a Google Cloud project, create OAuth 2.0 Desktop credentials, and save the downloaded client secrets file outside the repository. Then publish privately first:

```bash
cliprally publish-youtube \
  --video ./clips/01-a-strong-opening.mp4 \
  --client-secrets ./private/client_secret.json \
  --metadata ./clips/metadata.json \
  --privacy private \
  --i-have-rights
```

The OAuth refresh token is stored under the user's configuration directory (`~/.config/cliprally/` by default). Do not commit credentials or tokens. Confirm the destination channel and privacy before changing visibility.

Official documentation: [YouTube Data API](https://developers.google.com/youtube/v3) and [videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert).

## TikTok Direct Post

Create a TikTok developer app, configure the Content Posting API, request the required `video.publish` permission, and have the creator authorize the app. Set `TIKTOK_ACCESS_TOKEN` in the environment after completing the official OAuth flow.

```bash
cliprally publish-tiktok \
  --video ./clips/01-a-strong-opening.mp4 \
  --metadata ./clips/metadata.json \
  --privacy SELF_ONLY \
  --i-have-rights
```

Before uploading, ClipRally queries the authorized creator's profile and current privacy options, displays the destination and title, and requires the user to type `UPLOAD`. `--confirm-upload` is available for non-interactive workflows only when the operator has already reviewed the destination and privacy selection. TikTok returns a publish ID; publication processing can continue asynchronously. App audit and visibility restrictions are controlled by TikTok.

Official documentation: [Content Posting API](https://developers.tiktok.com/doc/content-posting-api-get-started).

## Instagram Reels

Instagram's publishing flow pulls media from a publicly reachable HTTPS URL. ClipRally does not host the MP4. Upload the clip to storage you control, then configure an Instagram API app and the permissions required for your account type.

```bash
export INSTAGRAM_USER_ID="your-ig-user-id"
export META_ACCESS_TOKEN="your-meta-access-token"

cliprally publish-instagram \
  --video-url "https://your-domain.example/clips/01-a-strong-opening.mp4" \
  --metadata ./clips/metadata.json \
  --api-version "vNN.N" \
  --i-have-rights
```

Replace `vNN.N` with an API version enabled for your Meta app. Review the hosted file URL, account, caption, and feed-sharing choice before publishing.

Official documentation: [Instagram API — Reels publishing](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/content-publishing/).

## Important limits

- Publishing is never automatic after clipping or trend discovery.
- Mocked adapter tests do not certify live provider behavior, app approval, account eligibility, or moderation outcomes.
- Platform APIs, accepted media specifications, privacy options, quotas, and app-review rules can change.
- The operator is responsible for confirming rights to the video, audio, music, likenesses, and other content, and for complying with the destination platform's terms.
- Never place client secrets, tokens, or private source media in the repository or issue tracker.