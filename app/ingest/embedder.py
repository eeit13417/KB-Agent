"""Turn text into vectors with a local embedding model (no API cost)."""

import logging
from functools import lru_cache

import torch
from sentence_transformers import SentenceTransformer

from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    """Load the model once and reuse it; loading costs tens of seconds."""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("loading %s on %s", settings.embedding_model, device)

    model = SentenceTransformer(settings.embedding_model, device=device)

    # Catch a model/config mismatch here rather than on the first database insert.
    dim = model.get_embedding_dimension()
    if dim != settings.embedding_dim:
        raise ValueError(
            f"{settings.embedding_model} produces {dim}-dim vectors, "
            f"but EMBEDDING_DIM is {settings.embedding_dim}"
        )
    return model


def embed_documents(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    vectors = get_model().encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=len(texts) > 100,
    )
    return vectors.tolist()


def embed_query(text: str) -> list[float]:
    """Kept separate from embed_documents: some models require different prefixes."""
    return embed_documents([text])[0]
