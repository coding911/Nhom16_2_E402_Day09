"""
build_index.py — Xây dựng ChromaDB index từ các file docs trong data/docs/

Chạy từ thư mục lab/:
    python build_index.py

Sau khi chạy xong, ChromaDB được lưu tại ./chroma_db với collection 'day09_docs',
sẵn sàng dùng cho workers/retrieval.py và mcp_server.py (tool search_kb).
"""

import os
import chromadb
from sentence_transformers import SentenceTransformer

# ─── Config ────────────────────────────────────────────────────────────
DOCS_DIR      = "./data/docs"
CHROMA_PATH   = "./chroma_db"
COLLECTION    = "day09_docs"       # phải khớp với workers/retrieval.py
EMBED_MODEL   = "all-MiniLM-L6-v2"  # phải khớp với workers/retrieval.py
CHUNK_SIZE    = 500   # ký tự mỗi chunk
CHUNK_OVERLAP = 100   # overlap giữa các chunk (tránh mất context ở ranh giới)
BATCH_SIZE    = 50    # số chunks mỗi lần add vào ChromaDB


# ─── Chunking ──────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Chia text thành các chunks nhỏ có overlap."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if len(chunk) > 50:  # bỏ qua chunk quá ngắn (thường là header/footer rỗng)
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


# ─── Main ──────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Build ChromaDB Index — Day 09 Lab")
    print("=" * 60)

    # ── Step 1: Load embedding model ──────────────────────────────────
    print(f"\n[1/4] Loading embedding model '{EMBED_MODEL}' ...")
    model = SentenceTransformer(EMBED_MODEL)
    print("      Done.")

    # ── Step 2: Khởi tạo ChromaDB, xóa collection cũ nếu có ──────────
    print(f"\n[2/4] Connecting ChromaDB at '{CHROMA_PATH}' ...")
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    existing_names = [c.name for c in client.list_collections()]
    if COLLECTION in existing_names:
        client.delete_collection(COLLECTION)
        print(f"      Đã xóa collection cũ '{COLLECTION}'.")

    collection = client.create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},  # cosine similarity — khớp với retrieval.py (score = 1 - distance)
    )
    print(f"      Tạo collection mới '{COLLECTION}' (cosine space).")

    # ── Step 3: Đọc, chunk, embed từng file ──────────────────────────
    print(f"\n[3/4] Đọc và index files từ '{DOCS_DIR}' ...")

    files = sorted(f for f in os.listdir(DOCS_DIR) if f.endswith(".txt"))
    if not files:
        print(f"  [WARN] Không tìm thấy file .txt nào trong {DOCS_DIR}")
        return

    all_texts, all_embeddings, all_ids, all_metadatas = [], [], [], []

    for fname in files:
        fpath = os.path.join(DOCS_DIR, fname)
        with open(fpath, encoding="utf-8") as f:
            content = f.read()

        chunks = chunk_text(content)
        # Encode tất cả chunks của file này cùng lúc (nhanh hơn encode từng cái)
        embeddings = model.encode(chunks, show_progress_bar=False).tolist()

        for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            all_texts.append(chunk)
            all_embeddings.append(emb)
            all_ids.append(f"{fname}__chunk{idx}")
            all_metadatas.append({
                "source": fname,       # retrieval.py dùng meta.get("source")
                "chunk_index": idx,
                "total_chunks": len(chunks),
            })

        print(f"  OK  {fname:45s} {len(chunks):3d} chunks")

    total = len(all_texts)

    # ── Step 4: Add vào ChromaDB theo batch ──────────────────────────
    print(f"\n[4/4] Adding {total} chunks vào ChromaDB (batch={BATCH_SIZE}) ...")

    for i in range(0, total, BATCH_SIZE):
        collection.add(
            documents=all_texts[i:i+BATCH_SIZE],          # text gốc — retrieval.py đọc từ results["documents"]
            embeddings=all_embeddings[i:i+BATCH_SIZE],     # pre-computed embedding
            ids=all_ids[i:i+BATCH_SIZE],
            metadatas=all_metadatas[i:i+BATCH_SIZE],
        )
        print(f"      Batch {i//BATCH_SIZE + 1}: added chunks [{i}–{min(i+BATCH_SIZE, total)-1}]")

    # ── Verify ────────────────────────────────────────────────────────
    count = collection.count()
    print(f"\n{'='*60}")
    print(f"  Index hoàn tất!")
    print(f"  Collection : {COLLECTION}")
    print(f"  Total docs : {count} chunks từ {len(files)} files")
    print(f"  Saved tại  : {CHROMA_PATH}")
    print(f"{'='*60}")

    # ── Smoke test ────────────────────────────────────────────────────
    print("\n[Smoke test] Thử query: 'SLA ticket P1 là bao lâu?'")
    q_emb = model.encode(["SLA ticket P1 là bao lâu?"])[0].tolist()
    results = collection.query(
        query_embeddings=[q_emb],
        n_results=3,
        include=["documents", "distances", "metadatas"],
    )
    for doc, dist, meta in zip(
        results["documents"][0],
        results["distances"][0],
        results["metadatas"][0],
    ):
        score = round(1 - dist, 4)  # cosine similarity (khớp với retrieval.py)
        print(f"  [{score:.3f}] {meta['source']}: {doc[:100]}...")

    print("\nReady! Chạy tiếp: python workers/retrieval.py")


if __name__ == "__main__":
    main()
