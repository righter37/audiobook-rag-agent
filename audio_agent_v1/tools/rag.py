import os
import pickle
import zipfile
import numpy as np
from pathlib import Path
from bs4 import BeautifulSoup
from sentence_transformers import SentenceTransformer
import faiss

# 首次运行会自动下载模型（~400MB），之后缓存到本地
_MODEL_PATH = (
    Path.home()
    / ".cache/huggingface/hub"
    / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
    / "snapshots/e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
)
_model = None

INDEX_DIR = Path(__file__).parent.parent / "index"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def _get_model():
    global _model
    if _model is None:
        print(f"[embed] 加载本地模型...")
        _model = SentenceTransformer(str(_MODEL_PATH))
    return _model


def _embed(texts: list) -> np.ndarray:
    model = _get_model()
    vecs = model.encode(texts, batch_size=32, show_progress_bar=len(texts) > 32)
    return np.array(vecs, dtype="float32")


def _epub_to_text(epub_path: str) -> str:
    parts = []
    with zipfile.ZipFile(epub_path, "r") as zf:
        for name in sorted(zf.namelist()):
            if name.endswith((".html", ".xhtml", ".htm")):
                with zf.open(name) as f:
                    soup = BeautifulSoup(f.read(), "html.parser")
                    parts.append(soup.get_text(separator="\n", strip=True))
    return "\n\n".join(parts)


def _split_text(text: str, chunk_size: int, overlap: int) -> list:
    separators = ["\n\n", "\n", "。", "！", "？", "，", " ", ""]
    chunks = []

    def _split(s, sep_idx):
        if len(s) <= chunk_size:
            if s.strip():
                chunks.append(s.strip())
            return
        sep = separators[sep_idx] if sep_idx < len(separators) else ""
        parts = s.split(sep) if sep else list(s)
        current = ""
        for part in parts:
            piece = (current + sep + part) if current else part
            if len(piece) <= chunk_size:
                current = piece
            else:
                if current.strip():
                    chunks.append(current.strip())
                current = current[-overlap:] + sep + part if overlap else part
        if current.strip():
            chunks.append(current.strip())

    _split(text, 0)
    return chunks


def _safe_name(book_name: str) -> str:
    import hashlib
    return hashlib.md5(book_name.encode()).hexdigest()[:12]


def _books_json() -> dict:
    p = INDEX_DIR / "books.json"
    if p.exists():
        import json
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _save_books_json(mapping: dict):
    import json
    (INDEX_DIR / "books.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _resolve_book_name(book_name: str) -> str:
    """模糊匹配书名，返回精确 book_name 或原值"""
    mapping = _books_json()
    if book_name in mapping:
        return book_name
    for name in mapping:
        if book_name in name or name in book_name:
            return name
    return book_name


def _index_paths(book_name: str):
    name = _safe_name(book_name)
    return INDEX_DIR / f"{name}.faiss", INDEX_DIR / f"{name}.chunks.pkl"


def index_book(file_path: str) -> str:
    INDEX_DIR.mkdir(exist_ok=True)
    path = Path(file_path)
    if not path.exists():
        return f"文件不存在: {file_path}"

    book_name = path.stem
    idx_path, chunks_path = _index_paths(book_name)
    if idx_path.exists() and chunks_path.exists():
        return f"《{book_name}》已有索引，无需重建"

    print(f"[index_book] 解析 {path.name}...")
    suffix = path.suffix.lower()
    if suffix == ".epub":
        text = _epub_to_text(str(path))
    elif suffix in (".txt", ".md"):
        text = path.read_text(encoding="utf-8", errors="ignore")
    else:
        return f"不支持的格式 {suffix}，支持 epub / txt / md"

    if not text.strip():
        return "无法从文件中提取文本"

    chunks = _split_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
    print(f"[index_book] {len(chunks)} 个片段，向量化中...")

    vecs = _embed(chunks)
    faiss.normalize_L2(vecs)
    index = faiss.IndexFlatIP(vecs.shape[1])
    index.add(vecs)

    faiss.write_index(index, str(idx_path))
    with open(chunks_path, "wb") as f:
        pickle.dump(chunks, f)

    mapping = _books_json()
    mapping[book_name] = _safe_name(book_name)
    _save_books_json(mapping)

    return f"《{book_name}》索引完成，{len(chunks)} 段，已保存"


def ask_book(book_name: str, question: str, top_k: int = 5) -> str:
    book_name = _resolve_book_name(book_name)
    idx_path, chunks_path = _index_paths(book_name)

    if not idx_path.exists():
        return f"未找到《{book_name}》的索引，请先用 index_book 工具建立索引"

    index = faiss.read_index(str(idx_path))
    with open(chunks_path, "rb") as f:
        chunks = pickle.load(f)

    q_vec = _embed([question])
    faiss.normalize_L2(q_vec)
    _, indices = index.search(q_vec, top_k)

    retrieved = [chunks[i] for i in indices[0] if i < len(chunks)]
    context = "\n\n---\n\n".join(retrieved)
    return f"[召回 {len(retrieved)} 段相关内容]\n\n{context}"
