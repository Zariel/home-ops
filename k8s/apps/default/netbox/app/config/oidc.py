from pathlib import Path


SOCIAL_AUTH_OIDC_OIDC_ENDPOINT = "https://id.cbannister.xyz"
SOCIAL_AUTH_OIDC_KEY = Path("/run/secrets/oidc/client_id").read_text().strip()
SOCIAL_AUTH_OIDC_SECRET = Path("/run/secrets/oidc/client_secret").read_text().strip()
SOCIAL_AUTH_OIDC_USE_PKCE = True
SOCIAL_AUTH_REDIRECT_IS_HTTPS = True
SOCIAL_AUTH_BACKEND_ATTRS = {"oidc": ("Pocket ID", "login")}
