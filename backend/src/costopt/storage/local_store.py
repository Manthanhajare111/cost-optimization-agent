from pathlib import Path

from costopt.config import settings


def required_directories() -> dict[str, Path]:
    return {
        "data": settings.data_dir,
        "runtime": settings.runtime_dir,
        "documents": settings.document_dir,
        "synthetic": settings.synthetic_data_dir,
    }


def ensure_runtime_directories() -> None:
    for path in required_directories().values():
        path.mkdir(parents=True, exist_ok=True)
