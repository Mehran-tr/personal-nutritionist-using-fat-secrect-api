# ADR 0003: Authentication — own accounts, Argon2id, short-lived JWT

**Status:** accepted

## Context
The app stores personal body data, so it needs accounts now. Clients are a web
app and later a mobile app. There is no single sign-on requirement yet.

## Decision
- Email + password accounts in our database. Passwords are hashed with **Argon2id**
  (library defaults), run in a worker thread, and upgraded transparently on login
  when parameters change.
- Login returns a **short-lived (30 min) HS256 JWT** with `sub`, `iss`, `aud`,
  `exp`, `iat`, `jti`. The algorithm is pinned on verification, and expiry is
  checked against the injected clock.
- Other modules authenticate requests only through `core.auth.AccessTokenVerifier`,
  exposed as the `CurrentUserId` dependency. They never import the identity module.
- Login failures are indistinguishable (same error, same hashing time).

## Consequences
+ Simple, stateless, fast to verify. Easy to swap for an external IdP later,
  because only `AccessTokenVerifier` needs a new implementation.
− No server-side revocation of access tokens before expiry. When clients need
  long sessions, add rotating refresh tokens stored server-side (planned with the
  mobile app), and consider asymmetric keys (RS256/EdDSA) if other services must
  verify tokens.
− Rate limiting of `/auth/token` is not in the app yet. Do it at the gateway, or add
  it before public launch.
