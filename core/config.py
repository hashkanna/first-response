"""Load local configuration without exposing values or overriding process env."""

from pathlib import Path


def load_environment() -> None:
    path = Path(__file__).resolve().parents[1] / ".env"
    if path.is_file():
        try:
            from dotenv import load_dotenv
        except ImportError as exc:
            raise RuntimeError("A project .env exists but python-dotenv is missing. Install requirements.txt.") from exc
        load_dotenv(path, override=False)
