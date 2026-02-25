"""Diagnostic: test each step of the RAG pipeline with timing."""
import time, sys, signal

def timeout_handler(signum, frame):
    raise TimeoutError("Step timed out!")

# On Windows, signal.SIGALRM not available, use threading instead
import threading

def run_with_timeout(func, label, timeout_sec=30):
    result = [None]
    error = [None]
    
    def target():
        try:
            result[0] = func()
        except Exception as e:
            error[0] = e
    
    t = threading.Thread(target=target, daemon=True)
    t0 = time.time()
    t.start()
    t.join(timeout=timeout_sec)
    elapsed = time.time() - t0
    
    if t.is_alive():
        print(f"  TIMEOUT: {label} exceeded {timeout_sec}s (still running at {elapsed:.1f}s)")
        return None
    elif error[0]:
        print(f"  ERROR: {label} failed in {elapsed:.1f}s: {error[0]}")
        return None
    else:
        print(f"  OK: {label} in {elapsed:.1f}s")
        return result[0]

print("=== RAG Pipeline Diagnostic ===\n", flush=True)

# Step 1: Load config
print("Step 1: Load config", flush=True)
cfg = run_with_timeout(
    lambda: __import__('localsearch.config', fromlist=['load_config']).load_config(),
    "load_config", 10
)
if not cfg:
    sys.exit(1)

# Step 2: Create embedder
print("\nStep 2: Create embedder", flush=True)
def make_embedder():
    from localsearch.embedder import Embedder
    return Embedder(cfg.embedding.model, cfg.embedding.device, cfg.embedding.batch_size)

embedder = run_with_timeout(make_embedder, "Embedder init", 30)
if not embedder:
    sys.exit(1)

# Step 3: Embed query
print("\nStep 3: Embed query", flush=True)
query = "Windows product key serial number"
vec = run_with_timeout(lambda: embedder.embed_query(query), "embed_query", 30)
if vec is None:
    sys.exit(1)
print(f"  Vector dim: {len(vec)}")

# Step 4: Qdrant search
print("\nStep 4: Qdrant search", flush=True)
def do_search():
    from localsearch.storage.vectordb import VectorDB
    vdb = VectorDB(cfg.qdrant.host, cfg.qdrant.port, cfg.qdrant.collection)
    return vdb.search(vec, top_k=10, score_threshold=0.3)

hits = run_with_timeout(do_search, "Qdrant search", 60)
if hits is None:
    # Try with a longer timeout
    print("  Retrying with 120s timeout...", flush=True)
    hits = run_with_timeout(do_search, "Qdrant search (retry)", 120)

if hits:
    print(f"  Got {len(hits)} results")
    for h in hits[:3]:
        print(f"    [{h['score']:.3f}] {h['payload'].get('file_path','?')[:80]}")

# Step 5: Ollama chat
print("\nStep 5: Ollama chat", flush=True)
def do_chat():
    import ollama
    client = ollama.Client(host=cfg.ollama.host)
    return client.chat(
        model=cfg.ollama.model,
        messages=[{"role": "user", "content": "Say hello in one word."}],
        options={"num_ctx": 8192},
        think=False,
    )

resp = run_with_timeout(do_chat, "Ollama chat", 60)
if resp:
    print(f"  Response: {resp['message']['content'][:100]}")

# Step 6: Full RAG pipeline
if hits and resp:
    print("\nStep 6: Full RAG (already tested components work)", flush=True)
    def do_rag():
        from localsearch.query.rag import RAGEngine
        from localsearch.query.search import SearchEngine
        se = SearchEngine(cfg)
        engine = RAGEngine(cfg, se)
        return engine.ask("What Windows product keys do I have?")
    
    result = run_with_timeout(do_rag, "Full RAG", 120)
    if result:
        print(f"  Answer: {result['answer'][:500]}")
        print(f"  Sources: {len(result['sources'])}")

print("\n=== Done ===", flush=True)
