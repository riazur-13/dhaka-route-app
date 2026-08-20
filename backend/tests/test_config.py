"""The environment-reading layer: whitespace stripping and the Groq model id."""

import config


def test_surrounding_whitespace_is_stripped(monkeypatch):
    """The deploy that broke had a trailing newline on a pasted DATABASE_URL."""
    monkeypatch.setenv("EXAMPLE_URL", "  postgresql://host/db\n")

    assert config.get_env("EXAMPLE_URL") == "postgresql://host/db"


def test_a_whitespace_only_value_falls_back_to_the_default(monkeypatch):
    """Nobody means "  " — treating it as set only hides the failure later."""
    monkeypatch.setenv("EXAMPLE_URL", "   \n")

    assert config.get_env("EXAMPLE_URL", "fallback") == "fallback"
    assert config.get_env("EXAMPLE_URL") is None


def test_an_unset_variable_gives_the_default(monkeypatch):
    monkeypatch.delenv("EXAMPLE_URL", raising=False)

    assert config.get_env("EXAMPLE_URL", "fallback") == "fallback"
    assert config.get_env("EXAMPLE_URL") is None


def test_interior_whitespace_is_left_alone(monkeypatch):
    """Only the edges are suspect; a space inside a value may be meaningful."""
    monkeypatch.setenv("EXAMPLE_NAME", " Dhaka Route \n")

    assert config.get_env("EXAMPLE_NAME") == "Dhaka Route"


def test_the_decommissioned_model_is_gone():
    """llama-3.3-70b-versatile was withdrawn by Groq; requests using it 404."""
    assert config.DEFAULT_GROQ_MODEL == "openai/gpt-oss-20b"
    assert config.GROQ_MODEL
