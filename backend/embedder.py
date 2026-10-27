"""
Embedding Pipeline — Generates vector embeddings for text chunks.

Runs a small embedding model locally on CPU with ONNX Runtime, with zero API
costs and no PyTorch, so the server fits in 512 MB of RAM. New indexes use
Snowflake's arctic-embed-xs, a model trained for search, in its 8-bit
quantized ONNX export (~23MB, 384-dimensional embeddings).
"""

from functools import lru_cache

import numpy as np
from dotenv import load_dotenv

load_dotenv()

# Models this app can run, by the ID the index manifest records (Hugging Face
# repo + ONNX file): how token vectors are pooled into one vector, and the
# instruction put before each query (chunks are embedded as they are).
# Both files are 8-bit exports that run on any x86-64 or ARM CPU.
MODELS = {
    "Snowflake/snowflake-arctic-embed-xs/onnx/model_uint8.onnx": (
        "cls", "Represent this sentence for searching relevant passages: ",
    ),
    # Built every index until October 2026; kept so those still work
    "sentence-transformers/all-MiniLM-L6-v2/onnx/model_quint8_avx2.onnx": (
        "mean", "",
    ),
}
# New indexes are built with this one. When it changes, `python -m scraper.refresh`
# re-embeds everything. Queries always use the model that built the index
# (see VectorStore), so a new server works with an older index.
DEFAULT_MODEL = "Snowflake/snowflake-arctic-embed-xs/onnx/model_uint8.onnx"
# Chunks are ~500 characters (about 150 tokens), so this cuts nothing off
MAX_TOKENS = 256


@lru_cache(maxsize=1)
def get_embedding_model(model):
    """
    Load the tokenizer and ONNX model (cached singleton).

    The first call downloads the model (~23MB) into the Hugging Face cache.
    Subsequent calls return the cached instances.
    """
    import onnxruntime
    from huggingface_hub import hf_hub_download
    from tokenizers import Tokenizer

    owner, name, model_file = model.split("/", 2)
    repo = f"{owner}/{name}"

    print(f"Loading embedding model: {model}")
    tokenizer = Tokenizer.from_file(hf_hub_download(repo, "tokenizer.json"))
    tokenizer.enable_truncation(max_length=MAX_TOKENS)
    tokenizer.enable_padding()
    # One thread: on a small CPU share (Render Free has 0.1 CPU) the default
    # thread pool made each query take several seconds. A full re-embed is
    # about 3x slower this way, which is fine for the weekly build.
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    session = onnxruntime.InferenceSession(
        hf_hub_download(repo, model_file),
        options,
        providers=["CPUExecutionProvider"],
    )
    return tokenizer, session


def embed_texts(texts, model=DEFAULT_MODEL, batch_size=64):
    """
    Generate embeddings for a list of texts.

    Args:
        texts: List of strings to embed
        model: Embedding model ID (a key of MODELS)
        batch_size: Number of texts to embed at once

    Returns:
        numpy array of shape (len(texts), embedding_dim)
    """
    tokenizer, session = get_embedding_model(model)
    pooling = MODELS[model][0]
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

        if pooling == "cls":
            pooled = token_embeddings[:, 0]
        else:
            # Mean pooling over real (non-padding) tokens, as sentence-transformers does
            mask = attention_mask[..., None].astype(np.float32)
            pooled = (token_embeddings * mask).sum(axis=1) / mask.sum(axis=1)
        # L2 normalize for cosine similarity
        batches.append(pooled / np.linalg.norm(pooled, axis=1, keepdims=True))
    return np.concatenate(batches)


def embed_query(query, model=DEFAULT_MODEL):
    """
    Generate embedding for a single query string.

    Args:
        query: The search query
        model: Embedding model ID (a key of MODELS)

    Returns:
        numpy array of shape (embedding_dim,)
    """
    return embed_texts([MODELS[model][1] + query], model)[0]


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
