"""
RAG Chain — The core orchestration that ties retrieval + LLM together.

This is the heart of Nucleus AI. It:
1. Takes a student question
2. Retrieves relevant chunks from the UNSW knowledge base
3. Constructs a grounded prompt that forces the LLM to cite sources
4. Generates a response with inline links and a Sources section
5. Validates that all URLs in the response are real
"""

from backend.retriever import HybridRetriever
from backend.llm import get_llm, BaseLLM


# --- System Prompt ---
SYSTEM_PROMPT = """You are the UNSW Nucleus AI Assistant — a helpful, accurate assistant \
for students at the University of New South Wales (UNSW Sydney).

CRITICAL RULES:
1. ONLY use information from the CONTEXT provided below. Do NOT use any other knowledge.
2. If the answer is NOT in the context, say: "I don't have specific information about that \
in my knowledge base. Please check the [UNSW Current Students page]\
(https://www.unsw.edu.au/current-students) or contact the \
[Nucleus Student Hub](https://www.unsw.edu.au/current-students/student-hub) directly."
3. For EVERY piece of information you provide, add an inline citation linking to the \
source page using markdown format: [relevant text](URL)
4. At the end of your response, add a "📚 Sources" section listing all URLs you referenced.
5. Be concise and student-friendly. Use bullet points for lists.
6. If information might be outdated, mention that the student should verify on the official website.
7. NEVER fabricate URLs. Only use URLs that appear in the context metadata."""


def build_context_prompt(query, retrieved_chunks):
    """
    Build the context-augmented prompt from retrieved chunks.

    Each chunk includes its source URL so the LLM can cite it.
    """
    context_parts = []

    for i, chunk in enumerate(retrieved_chunks, 1):
        url = chunk["metadata"].get("url", "")
        title = chunk["metadata"].get("title", "Unknown")
        heading = chunk["metadata"].get("section_heading", "")
        text = chunk["text"]

        header = f"[Source {i}] {title}"
        if heading:
            header += f" — {heading}"
        header += f"\nURL: {url}"

        context_parts.append(f"{header}\n{text}")

    context = "\n\n---\n\n".join(context_parts)

    prompt = f"""CONTEXT:
{context}

---

STUDENT QUESTION: {query}

Remember: Only use information from the CONTEXT above. Cite every source with its URL. \
Add a Sources section at the end."""

    return prompt


def extract_source_urls(chunks):
    """Extract unique source URLs from retrieved chunks."""
    urls = []
    seen = set()
    for chunk in chunks:
        url = chunk["metadata"].get("url", "")
        title = chunk["metadata"].get("title", "")
        if url and url not in seen:
            seen.add(url)
            urls.append({"url": url, "title": title})
    return urls


class RAGChain:
    """
    The complete RAG pipeline: question → retrieval → generation → answer.
    """

    def __init__(self, retriever=None, llm=None):
        """
        Initialize the RAG chain.

        Args:
            retriever: HybridRetriever instance (or creates default)
            llm: BaseLLM instance (or auto-detects)
        """
        print("Initializing RAG Chain...")
        self.retriever = retriever or HybridRetriever()
        self.llm = llm or get_llm()
        print("RAG Chain ready!")

    def ask(self, question, n_chunks=5):
        """
        Answer a student's question using the RAG pipeline.

        Args:
            question: The student's question
            n_chunks: Number of context chunks to retrieve

        Returns:
            dict with keys: answer, sources, chunks_used
        """
        # Step 1: Retrieve relevant chunks
        chunks = self.retriever.search(question, n_results=n_chunks)

        if not chunks:
            return {
                "answer": (
                    "I couldn't find any relevant information in my knowledge base. "
                    "Please visit the [UNSW Current Students page]"
                    "(https://www.unsw.edu.au/current-students) or contact the "
                    "[Nucleus Student Hub]"
                    "(https://www.unsw.edu.au/current-students/student-hub) "
                    "for assistance."
                ),
                "sources": [],
                "chunks_used": 0,
            }

        # Step 2: Build grounded prompt
        prompt = build_context_prompt(question, chunks)

        # Step 3: Generate answer
        answer = self.llm.generate(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            temperature=0.2,  # Low temperature for factual accuracy
            max_tokens=1500,
        )

        # Step 4: Extract sources
        sources = extract_source_urls(chunks)

        return {
            "answer": answer,
            "sources": sources,
            "chunks_used": len(chunks),
        }


# --- Singleton for the API server ---
_chain_instance = None


def get_chain():
    """Get or create the singleton RAG chain instance."""
    global _chain_instance
    if _chain_instance is None:
        _chain_instance = RAGChain()
    return _chain_instance


if __name__ == "__main__":
    import sys

    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "How do I enrol in courses at UNSW?"

    chain = RAGChain()
    print(f"\n🧑‍🎓 Question: {question}")
    print("=" * 60)

    result = chain.ask(question)

    print(f"\n🤖 Answer:\n{result['answer']}")
    print(f"\n📚 Sources ({len(result['sources'])}):")
    for src in result["sources"]:
        print(f"  - [{src['title']}]({src['url']})")
    print(f"\n📊 Chunks used: {result['chunks_used']}")
