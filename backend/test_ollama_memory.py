from ollama_memory import OllamaMemoryClient


def test_ollama_client_parses_embedding_and_chat(monkeypatch):
    client = OllamaMemoryClient()

    def fake_post(path, payload, timeout):
        if path == "/api/embed":
            return {"embeddings": [[0.1, 0.2, 0.3]]}
        return {"message": {"content": "analysis"}}

    monkeypatch.setattr(client, "_post", fake_post)
    assert client.embed("hello") == [0.1, 0.2, 0.3]
    assert client.analyze(system="system", payload={"x": 1}) == "analysis"
