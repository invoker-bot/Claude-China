from typing import Dict, Mapping, Optional


def merge_env(
    base_env: Mapping[str, str],
    common: Optional[Mapping] = None,
    per_app: Optional[Mapping] = None,
) -> Dict[str, str]:
    """Build the effective launch environment.

    Layering (last writer wins): base OS env -> 通用 (common) -> 专有 (per-app).
    So a per-app key overrides a common key with the same name.
    All overlay values are coerced to str (YAML may yield ints/bools).
    """
    eff: Dict[str, str] = dict(base_env)
    for layer in (common, per_app):
        if not layer:
            continue
        for key, value in layer.items():
            eff[str(key)] = str(value)
    return eff
