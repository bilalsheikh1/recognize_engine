import os
import pickle
import threading
import uuid
import faiss
import numpy as np
from config.config import Config
from .persistent_faiss_collection import PersistentFaissCollection

class VectorStore:
    """Do collections: employees (registered) aur unknowns (na-maloom log). Dono cosine, 512-dim using FAISS."""

    def __init__(self):
        storage_dir = getattr(Config, "CHROMA_PATH", "./chroma_data")
        os.makedirs(storage_dir, exist_ok=True)

        emp_file = os.path.join(storage_dir, "employees.pkl")
        unk_file = os.path.join(storage_dir, "unknowns.pkl")

        self.employees = PersistentFaissCollection(filepath=emp_file, dim=Config.EMBEDDING_DIM)
        self.unknowns = PersistentFaissCollection(filepath=unk_file, dim=Config.EMBEDDING_DIM)
        self._lock = threading.Lock()

    # ---------- employees ----------
    def add_employee(self, employee_id, embeddings):
        ids = [f"emp{employee_id}_{uuid.uuid4().hex[:8]}" for _ in embeddings]
        with self._lock:
            self.employees.add(
                ids=ids,
                embeddings=[e.tolist() if isinstance(e, np.ndarray) else e for e in embeddings],
                metadatas=[{"employee_id": int(employee_id)} for _ in embeddings],
            )

    def delete_employee(self, employee_id):
        with self._lock:
            self.employees.delete_by_metadata("employee_id", int(employee_id))

    def search_employee(self, emb):
        with self._lock:
            return self.employees.search(emb, "employee_id")

    # ---------- unknowns ----------
    def add_unknown(self, unknown_id, emb):
        with self._lock:
            emb_list = emb.tolist() if isinstance(emb, np.ndarray) else emb
            self.unknowns.add(
                ids=[f"unk{unknown_id}_{uuid.uuid4().hex[:8]}"],
                embeddings=[emb_list],
                metadatas=[{"unknown_id": int(unknown_id)}],
            )

    def search_unknown(self, emb):
        with self._lock:
            return self.unknowns.search(emb, "unknown_id")