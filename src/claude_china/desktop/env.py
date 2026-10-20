from typing import Dict, Mapping, Optional


def merge_env(
    base_env: Mapping[str, str],
    common: Optional[Mapping] = None,
    per_app: Optional[Mapping] = None,
    proxy_url: Optional[str] = None,
) -> Dict[str, str]:
    """Build the effective launch environment.

    Layering: base OS env -> automatic proxy -> 通用 (common) -> 专有 (per-app).
    So a per-app key overrides a common key with the same name.
    All overlay values are coerced to str (YAML may yield ints/bools).
    """
    eff: Dict[str, str] = dict(base_env)
    if proxy_url is not None:
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            eff[key] = proxy_url
    for layer in (common, per_app):
        if not layer:
            continue
        for key, value in layer.items():
            eff[str(key)] = str(value)
            if proxy_url is not None and str(key).lower() in ("http_proxy", "https_proxy"):
                # Keep clients that prefer lowercase from using a stale value
                # or ignoring an explicit uppercase common/per-app override.
                eff[str(key).lower()] = eff[str(key).upper()] = str(value)
    return eff
