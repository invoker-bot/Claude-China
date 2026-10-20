from src.claude_china.desktop.env import merge_env


def test_common_applied_and_base_preserved():
    base = {"PATH": "/bin"}
    out = merge_env(base, {"HTTP_PROXY": "http://p"}, {})
    assert out["PATH"] == "/bin"
    assert out["HTTP_PROXY"] == "http://p"


def test_per_app_overrides_common_on_shared_key():
    out = merge_env({}, {"K": "common", "ONLY_COMMON": "c"}, {"K": "app"})
    assert out["K"] == "app"            # 专有 wins
    assert out["ONLY_COMMON"] == "c"


def test_values_are_stringified():
    out = merge_env({}, {"N": 5}, {"B": True})
    assert out["N"] == "5"
    assert out["B"] == "True"


def test_none_inputs_are_safe():
    out = merge_env({"A": "1"}, None, None)
    assert out == {"A": "1"}
