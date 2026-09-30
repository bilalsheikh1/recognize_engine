import faiss
import uuid
import pickle
import os
import threading
import numpy as np

class PersistentFaissCollection:
    """FAISS collection with L2-normalization for Cosine Similarity search and persistent storage."""

    def __init__(self, filepath, dim=512):
        self.filepath = filepath
        self.dim = dim
        self.index = faiss.IndexFlatIP(self.dim)  # Inner Product (Cosine similarity when vectors normalized)
        self.ids = []
        self.metadatas = []
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "rb") as f:
                    data = pickle.load(f)
                    self.index = faiss.deserialize_index(data["index"])
                    self.ids = data["ids"]
                    self.metadatas = data["metadatas"]
            except Exception as e:
                print(f"[FAISS Store] Load warning for {self.filepath}: {e}")

    def _save(self):
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        data = {
            "index": faiss.serialize_index(self.index),
            "ids": self.ids,
            "metadatas": self.metadatas,
        }
        with open(self.filepath, "wb") as f:
            pickle.dump(data, f)

    def count(self):
        return self.index.ntotal

    def add(self, ids, embeddings, metadatas):
        vecs = np.array(embeddings, dtype="float32")
        # Normalize vectors for Cosine Similarity
        faiss.normalize_L2(vecs)
        self.index.add(vecs)
        self.ids.extend(ids)
        self.metadatas.extend(metadatas)
        self._save()

    def delete_by_metadata(self, key, value):
        indices_to_keep = [
            i for i, meta in enumerate(self.metadatas) if meta.get(key) != value
        ]
        if len(indices_to_keep) == len(self.metadatas):
            return

        if len(indices_to_keep) == 0:
            self.index = faiss.IndexFlatIP(self.dim)
            self.ids = []
            self.metadatas = []
        else:
            # Reconstruct index without deleted vectors
            all_vectors = np.zeros((self.index.ntotal, self.dim), dtype="float32")
            for i in range(self.index.ntotal):
                all_vectors[i] = self.index.reconstruct(i)

            kept_vectors = all_vectors[indices_to_keep]
            self.ids = [self.ids[i] for i in indices_to_keep]
            self.metadatas = [self.metadatas[i] for i in indices_to_keep]

            self.index = faiss.IndexFlatIP(self.dim)
            if len(kept_vectors) > 0:
                self.index.add(kept_vectors)

        self._save()

    def search(self, emb, key):
        if self.index.ntotal == 0:
            return None, 0.0

        vec = np.array([emb], dtype="float32")
        faiss.normalize_L2(vec)

        # Inner Product yields Cosine Similarity directly
        similarities, indices = self.index.search(vec, k=1)
        best_idx = indices[0][0]
        similarity = float(similarities[0][0])

        if best_idx == -1 or best_idx >= len(self.metadatas):
            return None, 0.0

        target_id = int(self.metadatas[best_idx][key])
        return target_id, similarity
