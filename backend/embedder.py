"""
Embedding Pipeline — Generates vector embeddings for text chunks.

Runs all-MiniLM-L6-v2 locally on CPU with ONNX Runtime, with zero API costs
and no PyTorch, so the server fits in 512 MB of RAM. It uses the model's
8-bit quantized ONNX export (~23MB), which produces 384-dimensional
embeddings very close to the full model's.
"""

import os
from functools import lru_cache

import numpy as np
from dotenv import load_dotenv

load_dotenv()

# Hugging Face repo of a sentence-transformers model that ships ONNX exports
MODEL_REPO = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2"
)
# The 8-bit quantized export: about a third of the memory of the full
# onnx/model.onnx, and it runs on any x86-64 or ARM CPU.
MODEL_FILE = "onnx/model_quint8_avx2.onnx"
# Recorded in the index manifest. When it changes, `python -m scraper.refresh`
# re-embeds everything, so stored and query vectors come from the same model.
DEFAULT_MODEL = f"{MODEL_REPO}/{MODEL_FILE}"
# sentence-transformers' max_seq_length for this model
MAX_TOKENS = 256


@lru_cache(maxsize=1)
def get_embedding_model():
    """
    Load the tokenizer and ONNX model (cached singleton).

    The first call downloads the model (~23MB) into the Hugging Face cache.
    Subsequent calls return the cached instances.
    """
    import onnxruntime
    from huggingface_hub import hf_hub_download
    from tokenizers import Tokenizer

    print(f"Loading embedding model: {DEFAULT_MODEL}")
    tokenizer = Tokenizer.from_file(hf_hub_download(MODEL_REPO, "tokenizer.json"))
    tokenizer.enable_truncation(max_length=MAX_TOKENS)
    tokenizer.enable_padding()
    # One thread: on a small CPU share (Render Free has 0.1 CPU) the default
    # thread pool made each query take several seconds. A full re-embed is
    # about 3x slower this way, which is fine for the weekly build.
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    session = onnxruntime.InferenceSession(
        hf_hub_download(MODEL_REPO, MODEL_FILE),
        options,
        providers=["CPUExecutionProvider"],
    )
    return tokenizer, session


def embed_texts(texts, batch_size=64):
    """
    Generate embeddings for a list of texts.

    Args:
        texts: List of strings to embed
        batch_size: Number of texts to embed at once

    Returns:
        numpy array of shape (len(texts), embedding_dim)
    """
    tokenizer, session = get_embedding_model()
    batches = []
    for i in range(0, len(texts), batch_size):
        encoded = tokenizer.encode_batch(texts[i : i + batch_size])
        input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        token_embeddings = session.run(None, {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "token_type_ids": np.zeros_like(input_ids),
        })[0]

        # Mean pooling over real (non-padding) tokens, as sentence-transformers does
        mask = attention_mask[..., None].astype(np.float32)
        pooled = (token_embeddings * mask).sum(axis=1) / mask.sum(axis=1)
        # L2 normalize for cosine similarity
        batches.append(pooled / np.linalg.norm(pooled, axis=1, keepdims=True))
    return np.concatenate(batches)


def embed_query(query):
    """
    Generate embedding for a single query string.

    Args:
        query: The search query

    Returns:
        numpy array of shape (embedding_dim,)
    """
    return embed_texts([query])[0]


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
    query = embed_query("enrollment process")
    similarities = np.dot(embeddings, query)
    print(f"\nQuery: 'enrollment process'")
    for text, sim in zip(test_texts, similarities):
        print(f"  {sim:.4f}  {text}")
