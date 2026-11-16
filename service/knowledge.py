from __future__ import annotations

import hashlib
import io
import json
import re
import time
import uuid
import zipfile

import numpy as np
from docx import Document
from pypdf import PdfReader

from .content import SAMPLE_DOCUMENT
from .providers import ProviderError

MAX_BYTES = 15 * 1024 * 1024
MAX_CHARS = 500_000


def extract(name: str, content: bytes) -> str:
    if not content or len(content) > MAX_BYTES:
        raise ValueError("文件为空或超过15MB")
    suffix = name.rsplit(".", 1)[-1].lower()
    if suffix in ("txt", "md"):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("gb18030")
    elif suffix == "docx":
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if sum(x.file_size for x in archive.infolist()) > 50 * 1024 * 1024:
                raise ValueError("文档解压大小超过限制")
        doc = Document(io.BytesIO(content))
        text = "\n".join([p.text for p in doc.paragraphs] +
                         [" | ".join(c.text for c in row.cells) for table in doc.tables for row in table.rows])
    elif suffix == "pdf":
        pdf = PdfReader(io.BytesIO(content))
        if pdf.is_encrypted:
            raise ValueError("请先解除PDF密码")
        if len(pdf.pages) > 300:
            raise ValueError("PDF超过300页，请拆分后导入")
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        if len(text.strip()) < 20:
            raise ValueError("未找到足够文字，扫描PDF请先转换为文字后导入")
    else:
        raise ValueError("仅支持TXT、Markdown、DOCX和有文字层的PDF")
    text = text.replace("\x00", "").strip()
    if not text or len(text) > MAX_CHARS:
        raise ValueError("文档无可用文字或超过50万字，请拆分后导入")
    return text


def chunk_text(text: str) -> list[str]:
    # Heading/paragraph boundaries are kept where possible; long paragraphs overlap.
    paragraphs = re.split(r"\n\s*\n", text)
    chunks, current = [], ""
    for p in paragraphs:
        if len(current) + len(p) > 650 and current:
            chunks.append(current.strip())
            current = ""
        while len(p) > 650:
            chunks.append(p[:650])
            p = p[570:]
        current += p + "\n\n"
    if current.strip():
        chunks.append(current.strip())
    return chunks


def terms(text):
    text = re.sub(r"[^\w\u4e00-\u9fff]", "", text.lower())
    return {text[i:i + 2] for i in range(max(0, len(text) - 1))}


class Knowledge:
    def __init__(self, store):
        self.store = store
        with store.lock:
            exists = store.db.execute("SELECT id FROM documents WHERE id='demo-seed'").fetchone()
        if not exists and not store.get("demo_seeded", False):
            self.insert("演示知识库.md", "demo", SAMPLE_DOCUMENT.encode(), "demo-seed")
        store.set("demo_seeded", True)

    def insert(self, name, kb, content, doc_id=None):
        if not re.fullmatch(r"[a-z0-9_-]{1,40}", kb):
            raise ValueError("知识库标识无效")
        name = name.replace("\\", "/").rsplit("/", 1)[-1][:200]
        text = extract(name, content)
        digest = hashlib.sha256(content).hexdigest()
        with self.store.lock:
            existing = self.store.db.execute("SELECT id FROM documents WHERE digest=? AND kb=?", (digest, kb)).fetchone()
        if existing:
            return existing[0]
        doc_id = doc_id or uuid.uuid4().hex
        chunks = chunk_text(text)
        with self.store.lock, self.store.db:
            self.store.db.execute("INSERT INTO documents VALUES (?,?,?,?,?)", (doc_id, name, kb, digest, time.time()))
            self.store.db.executemany("INSERT INTO chunks(doc_id,text,ordinal) VALUES (?,?,?)",
                                     [(doc_id, s, i) for i, s in enumerate(chunks)])
        (self.store.root / "documents" / (doc_id + ".txt")).write_text(text, encoding="utf-8")
        return doc_id

    def documents(self):
        with self.store.lock:
            return [dict(r) for r in self.store.db.execute("""
                SELECT d.*,COUNT(c.id) AS chunks,COUNT(c.embedding) AS indexed
                FROM documents d LEFT JOIN chunks c ON d.id=c.doc_id GROUP BY d.id ORDER BY d.created
            """)]

    def delete(self, doc_id):
        with self.store.lock, self.store.db:
            self.store.db.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
            self.store.db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        # doc_id is never accepted as a path; resolve stored UUIDs only.
        if re.fullmatch(r"[a-f0-9]{32}|demo-seed", doc_id):
            (self.store.root / "documents" / (doc_id + ".txt")).unlink(missing_ok=True)

    async def index(self, provider, kb=None):
        with self.store.lock:
            rows = list(self.store.db.execute("""
                SELECT c.id,c.text FROM chunks c JOIN documents d ON c.doc_id=d.id
                WHERE (? IS NULL OR d.kb=?) AND (embedding IS NULL OR embedding_model IS NULL OR embedding_model!=?)
            """, (kb, kb, provider.settings.embedding_model)))
        for start in range(0, len(rows), 10):
            batch = rows[start:start + 10]
            vectors = await provider.embed([r["text"] for r in batch])
            with self.store.lock, self.store.db:
                self.store.db.executemany("UPDATE chunks SET embedding=?,embedding_model=? WHERE id=?", [
                    (json.dumps(vector), provider.settings.embedding_model, r["id"])
                    for r, vector in zip(batch, vectors, strict=True)])
        return len(rows)

    async def search(self, question, kb, provider=None, limit=4):
        with self.store.lock:
            rows = list(self.store.db.execute("""
                SELECT c.*,d.name FROM chunks c JOIN documents d ON c.doc_id=d.id WHERE d.kb=?
            """, (kb,)))
        if not rows:
            return []
        query_vector = None
        if provider and any(r["embedding"] and r["embedding_model"] == provider.settings.embedding_model for r in rows):
            try:
                query_vector = np.array((await provider.embed([question]))[0], dtype=np.float32)
            except ProviderError:
                pass  # Explicit lexical fallback still returns only real source snippets.
        query_terms = terms(question)
        ranked = []
        for row in rows:
            lexical = len(query_terms & terms(row["text"])) / max(1, len(query_terms))
            score = lexical
            if query_vector is not None and row["embedding"] and row["embedding_model"] == provider.settings.embedding_model:
                vector = np.array(json.loads(row["embedding"]), dtype=np.float32)
                if vector.shape == query_vector.shape:
                    cosine = float(vector @ query_vector / max(1e-8, np.linalg.norm(vector) * np.linalg.norm(query_vector)))
                    score = 0.75 * max(0, cosine) + 0.25 * lexical
            if score >= (0.3 if query_vector is not None else 0.12):
                ranked.append({"chunk_id": row["id"], "document": row["name"], "text": row["text"], "score": round(score, 4)})
        return sorted(ranked, key=lambda x: x["score"], reverse=True)[:limit]
