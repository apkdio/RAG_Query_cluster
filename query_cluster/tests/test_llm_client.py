import json

from query_cluster.llm.client import client_from_env, load_config


def test_client_reads_config_file(tmp_path):
    path = tmp_path / "llm.json"
    path.write_text(json.dumps({
        "base_url": "http://127.0.0.1:9999/v1",
        "model": "demo-model",
        "timeout": 12,
        "api_key_env": "DEMO_LLM_KEY",
    }), encoding="utf-8")
    config = load_config(path)
    client = client_from_env(config_path=path)
    assert config["model"] == "demo-model"
    assert client.base_url == "http://127.0.0.1:9999/v1"
    assert client.model == "demo-model"
    assert client.timeout == 12


def test_client_argument_overrides_config(tmp_path):
    path = tmp_path / "llm.json"
    path.write_text(json.dumps({
        "base_url": "http://config/v1",
        "model": "config-model",
    }), encoding="utf-8")
    client = client_from_env(base_url="http://cli/v1", model="cli-model", config_path=path)
    assert client.base_url == "http://cli/v1"
    assert client.model == "cli-model"
