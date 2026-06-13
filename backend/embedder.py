"""
Embedding Pipeline — Generates vector embeddings for text chunks.

Uses sentence-transformers with a lightweight model (all-MiniLM-L6-v2)
that runs locally on CPU with zero API costs. The model is ~80MB and
produces 384-dimensional embeddings.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

# Default model — small, fast, runs on CPU
DEFAULT_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2"
)


@lru_cache(maxsize=1)
def get_embedding_model(model_name=None):
    """
    Load the embedding model (cached singleton).

    The first call downloads the model (~80MB) if not already cached.
    Subsequent calls return the cached instance.
    """
    from sentence_transformers import SentenceTransformer

    model_name = model_name or DEFAULT_MODEL
    print(f"Loading embedding model: {model_name}")
    model = SentenceTransformer(model_name)
    print(f"Model loaded! Embedding dimension: {model.get_sentence_embedding_dimension()}")
    return model


def embed_texts(texts, model_name=None, batch_size=64, show_progress=True):
    """
    Generate embeddings for a list of texts.

    Args:
        texts: List of strings to embed
        model_name: Optional model override
        batch_size: Number of texts to embed at once
        show_progress: Show progress bar

    Returns:
        numpy array of shape (len(texts), embedding_dim)
    """
    model = get_embedding_model(model_name)
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=show_progress,
        normalize_embeddings=True,  # L2 normalize for cosine similarity
    )
    return embeddings


def embed_query(query, model_name=None):
    """
    Generate embedding for a single query string.

    Args:
        query: The search query
        model_name: Optional model override

    Returns:
        numpy array of shape (embedding_dim,)
    """
    model = get_embedding_model(model_name)
    embedding = model.encode(
        query,
        normalize_embeddings=True,
    )
    return embedding


if __name__ == "__main__":
    # Quick test
    print("Testing embedding pipeline...")
    test_texts = [
        "How do I enrol in courses at UNSW?",
        "What are the graduation requirements?",
        "Where is the Nucleus Student Hub located?",
    ]
    embeddings = embed_texts(test_texts)
    print(f"Generated {len(embeddings)} embeddings of dimension {embeddings.shape[1]}")

    # Test similarity
    import numpy as np
    query = embed_query("enrollment process")
    similarities = np.dot(embeddings, query)
    print(f"\nQuery: 'enrollment process'")
    for text, sim in zip(test_texts, similarities):
        print(f"  {sim:.4f}  {text}")
