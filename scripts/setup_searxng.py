"""Generate private SearXNG settings using the existing local Brave key."""
import json
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from partner_matcher import configured_search_key


def main():
    key = configured_search_key(ROOT)
    if not key:
        raise SystemExit("Add BRAVE_SEARCH_API_KEY to .env first")
    path = ROOT / ".local" / "searxng" / "settings.yml"
    if path.exists() and "--overwrite" not in sys.argv:
        raise SystemExit("Private settings already exist. Use --overwrite to regenerate them after rotating your key.")
    path.parent.mkdir(parents=True, exist_ok=True)
    # JSON quoted strings are valid YAML scalars and prevent config injection.
    path.write_text("""# Generated locally; contains a secret. Never commit this file.
use_default_settings:
  engines:
    keep_only:
      - duckduckgo
      - braveapi
server:
  bind_address: 0.0.0.0
  port: 8080
  limiter: false
  secret_key: SECRET
search:
  formats:
    - html
    - json
engines:
  - name: duckduckgo
    disabled: false
  - name: braveapi
    engine: braveapi
    api_key: KEY
    inactive: false
    disabled: true
    results_per_page: 10
""".replace("SECRET", json.dumps(secrets.token_hex(32))).replace("KEY", json.dumps(key)), encoding="utf-8")
    print("Created private .local/searxng/settings.yml. Key was not printed.")


if __name__ == "__main__":
    main()
