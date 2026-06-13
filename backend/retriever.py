"""
Hybrid Retriever — Combines vector (semantic) search with BM25 (keyword) search.

Why hybrid? Vector search excels at understanding meaning ("How do I sign up
for classes?" matches "enrolment process"), while BM25 catches exact terms
that embedding models might miss (like specific course codes "COMP1511" or
policy names).

The two result sets are merged using Reciprocal Rank Fusion (RRF).
"""

import json
import math
from pathlib import Path

from rank_bm25 import BM25Okapi

from backend.vector_store import VectorStore


class HybridRetriever:
    """
    Retriever that combines semantic vector search with BM25 keyword matching.
    """

    def __init__(self, vector_store=None, chunks=None):
        """
        Initialize the hybrid retriever.

        Args:
            vector_store: Existing VectorStore instance (or creates a new one)
            chunks: Pre-loaded chunks for BM25 (or loads from disk)
        """
        self.vector_store = vector_store or VectorStore()
        self.chunks = chunks or []
        self.bm25 = None

        if not self.chunks:
            self._load_chunks()

        if self.chunks:
            self._build_bm25_index()

    def _load_chunks(self):
        """Load chunks from disk for BM25 indexing."""
        from scraper import settings as crawler_settings

        chunks_file = Path(crawler_settings.CHUNKS_DIR) / "all_chunks.jsonl"
        if not chunks_file.exists():
            print("Warning: No chunks file found for BM25. Using vector-only search.")
            return

        self.chunks = []
        with open(chunks_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        self.chunks.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        print(f"Loaded {len(self.chunks)} chunks for BM25 indexing.")

    def _build_bm25_index(self):
        """Build the BM25 index from loaded chunks."""
        if not self.chunks:
            return

        # Tokenize: simple whitespace + lowercasing
        tokenized_corpus = [
            self._tokenize(chunk["text"]) for chunk in self.chunks
        ]
        self.bm25 = BM25Okapi(tokenized_corpus)
        print(f"BM25 index built with {len(self.chunks)} documents.")

    def _tokenize(self, text):
        """Simple tokenization: lowercase, split on whitespace and punctuation."""
        import re
        text = text.lower()
        tokens = re.findall(r"\b\w+\b", text)
        return tokens

    def search(self, query, n_results=5, vector_weight=0.6, bm25_weight=0.4):
        """
        Hybrid search combining vector similarity and BM25.

        Args:
            query: The search query
            n_results: Number of results to return
            vector_weight: Weight for vector search results (0-1)
            bm25_weight: Weight for BM25 results (0-1)

        Returns:
            List of result dicts with keys: text, metadata, score, sources
        """
        # Fetch more candidates for better fusion
        k_candidates = min(n_results * 4, 20)

        # --- Vector Search ---
        vector_results = self.vector_store.search(
            query_text=query,
            n_results=k_candidates,
        )

        # --- BM25 Search ---
        bm25_results = []
        if self.bm25 and self.chunks:
            query_tokens = self._tokenize(query)
            bm25_scores = self.bm25.get_scores(query_tokens)

            # Get top-k indices
            top_indices = sorted(
                range(len(bm25_scores)),
                key=lambda i: bm25_scores[i],
                reverse=True,
            )[:k_candidates]

            for idx in top_indices:
                if bm25_scores[idx] > 0:
                    chunk = self.chunks[idx]
                    bm25_results.append({
                        "text": chunk["text"],
                        "metadata": chunk["metadata"],
                        "bm25_score": bm25_scores[idx],
                    })

        # --- Reciprocal Rank Fusion ---
        fused = self._reciprocal_rank_fusion(
            vector_results,
            bm25_results,
            vector_weight=vector_weight,
            bm25_weight=bm25_weight,
        )

        return fused[:n_results]

    def _reciprocal_rank_fusion(
        self, vector_results, bm25_results, vector_weight=0.6, bm25_weight=0.4, k=60
    ):
        """
        Merge two ranked lists using Reciprocal Rank Fusion (RRF).

        RRF formula: score = weight * (1 / (k + rank))
        where k is a constant (typically 60) that dampens the effect of rank.
        """
        # Build a map: text → fused_score and metadata
        scores = {}

        # Process vector results
        for rank, result in enumerate(vector_results):
            key = result["text"][:100]  # Use first 100 chars as key
            rrf_score = vector_weight * (1.0 / (k + rank + 1))
            if key not in scores:
                scores[key] = {
                    "text": result["text"],
                    "metadata": result["metadata"],
                    "score": 0.0,
                    "vector_rank": rank + 1,
                    "bm25_rank": None,
                }
            scores[key]["score"] += rrf_score

        # Process BM25 results
        for rank, result in enumerate(bm25_results):
            key = result["text"][:100]
            rrf_score = bm25_weight * (1.0 / (k + rank + 1))
            if key not in scores:
                scores[key] = {
                    "text": result["text"],
                    "metadata": result["metadata"],
                    "score": 0.0,
                    "vector_rank": None,
                    "bm25_rank": rank + 1,
                }
            scores[key]["score"] += rrf_score
            scores[key]["bm25_rank"] = rank + 1

        # Sort by fused score (descending)
        fused = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
        return fused

    def vector_only_search(self, query, n_results=5):
        """Fallback: vector-only search if BM25 isn't available."""
        return self.vector_store.search(query_text=query, n_results=n_results)


if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "How do I enrol in courses?"

    retriever = HybridRetriever()
    results = retriever.search(query)

    print(f"\n🔍 Hybrid Search: '{query}'")
    print("=" * 60)
    for i, r in enumerate(results, 1):
        print(f"\n--- Result {i} (score: {r['score']:.6f}) ---")
        print(f"URL: {r['metadata'].get('url', 'N/A')}")
        print(f"Title: {r['metadata'].get('title', 'N/A')}")
        print(f"Vector Rank: {r.get('vector_rank', '-')}")
        print(f"BM25 Rank: {r.get('bm25_rank', '-')}")
        print(f"Text: {r['text'][:250]}...")
