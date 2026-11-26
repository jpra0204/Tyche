"""The console's lock: a token per launch, and only local host names (ADR-0046).

The server listens on ``127.0.0.1``, but any web page open in Pablo's browser can still
send requests there. Two checks stop that:

* **A token.** ``tyche ui`` makes a random one at every launch and puts it in the
  address it opens, after ``#``, so it never reaches a server log. The page sends it in
  a header with every call; a page from anywhere else cannot know it.
* **The host name.** A request must name ``127.0.0.1`` or ``localhost``, so a site that
  points its own domain at this machine (DNS rebinding) is refused.
"""

import hmac
import secrets

TOKEN_HEADER = "X-Tyche-Token"
"""The header every API call carries the token in."""

LOCAL_HOSTS = ("127.0.0.1", "localhost")
"""The host names a request may name."""


def new_token() -> str:
    """A fresh random token: 256 bits, URL-safe."""
    return secrets.token_urlsafe(32)


def same_token(given: str | None, expected: str) -> bool:
    """True if ``given`` is ``expected``, compared in constant time."""
    if given is None:
        return False
    return hmac.compare_digest(given.encode(), expected.encode())
