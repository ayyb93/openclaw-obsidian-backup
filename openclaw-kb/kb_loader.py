#!/usr/bin/env python3
"""Load and index project documents for RAG"""
import os, re, json, hashlib, time

VAULT = "/root/radiantedge-vault"
KB_FILE = f"{VAULT}/knowledge_base.json"

def load_documents():
    """قراءة الملفات الفعلية واستخراج نصوص قابلة للبحث"""
    docs = []
    
    # ملف 1: OpenCLaw_Master_Blueprint.md
    bp_path = "/root/OpenCLaw_Master_Blueprint.md"
    if os.path.exists(bp_path):
        with open(bp_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        docs.append({"source": "OpenCLaw_Blueprint", "content": content})
        print(f"✅ Loaded Blueprint: {len(content)} chars")
    
    # ملف 2: RadiantEdge (نسخة نصية من الـ PDF)
    re_path = "/root/RadiantEdge_Brief.md"  # نُنشئه يدوياً لضمان الجودة
    if os.path.exists(re_path):
        with open(re_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        docs.append({"source": "RadiantEdge_Brief", "content": content})
        print(f"✅ Loaded RadiantEdge: {len(content)} chars")
    
    return docs

def chunk_text(text: str, source: str, max_chunk: int = 400) -> list:
    """تقسيم النص إلى قطع ذكية مع الحفاظ على المعنى"""
    chunks = []
    # تقسيم حسب العناوين أولاً
    sections = re.split(r'(#{2,4}\s+[^\n]+)', text)
    
    for i, section in enumerate(sections):
        if not section.strip() or len(section) < 30:
            continue
        # إذا كان العنوان
        if section.startswith('#'):
            title = section.strip()
            content = sections[i+1] if i+1 < len(sections) else ""
            if content.strip():
                chunk = f"{title}\n{content.strip()[:300]}"
                chunks.append({
                    "id": hashlib.md5(chunk.encode()).hexdigest()[:8],
                    "source": source,
                    "text": chunk,
                    "keywords": extract_keywords(chunk)
                })
        elif len(section) <= max_chunk:
            chunks.append({
                "id": hashlib.md5(section.encode()).hexdigest()[:8],
                "source": source,
                "text": section.strip(),
                "keywords": extract_keywords(section)
            })
        else:
            # تقسيم طويل جداً إلى جمل
            sentences = re.split(r'[.!?۔]\s*', section)
            buffer = ""
            for sent in sentences:
                if len(buffer + sent) <= max_chunk:
                    buffer += sent + ". "
                else:
                    if buffer.strip():
                        chunks.append({
                            "id": hashlib.md5(buffer.encode()).hexdigest()[:8],
                            "source": source,
                            "text": buffer.strip(),
                            "keywords": extract_keywords(buffer)
                        })
                    buffer = sent + ". "
            if buffer.strip():
                chunks.append({
                    "id": hashlib.md5(buffer.encode()).hexdigest()[:8],
                    "source": source,
                    "text": buffer.strip(),
                    "keywords": extract_keywords(buffer)
                })
    
    return chunks

def extract_keywords(text: str) -> list:
    """استخراج كلمات مفتاحية ذات صلة بالمشروع"""
    text_lower = text.lower()
    # كلمات مشروعنا الحرجة
    critical = [
        # مدن
        'نيويورك', 'london', 'لندن', 'dubai', 'دبي', 'los angeles', 'لوس أنجلوس',
        # مشروع
        'radiantedge', 'openclaw', 'dropshipping', 'luxury', 'هوية', 'شعار',
        # فئات
        '20-40', 'نساء', 'فئة', 'مستهدفة', 'جمهور',
        # منتجات
        'إكسسوارات', 'مضادة للحساسية', 'تيتانيوم', 'خفيفة', 'وزن',
        # وكلاء
        'ceo', 'archivist', 'engineer', 'creative', 'obsidian', 'n8n', 'shopify',
        # قواعد
        'تسلسل', 'موارد', 'تلخيص', 'تحسين', 'ذاتي', '14 يوم',
        # زمن
        'شهر', 'أسبوع', 'أول', '90 يوم', 'مرحلة'
    ]
    return [kw for kw in critical if kw in text_lower]

def build_index():
    """بناء فهرس البحث من الملفات"""
    docs = load_documents()
    all_chunks = []
    
    for doc in docs:
        chunks = chunk_text(doc["content"], doc["source"])
        all_chunks.extend(chunks)
    
    index = {
        "chunks": all_chunks,
        "meta": {
            "total_chunks": len(all_chunks),
            "sources": list(set(c["source"] for c in all_chunks)),
            "built_at": time.time()
        }
    }
    
    os.makedirs(os.path.dirname(KB_FILE), exist_ok=True)
    with open(KB_FILE, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Index built: {len(all_chunks)} chunks from {len(docs)} sources")
    return index

def search(query: str, top_k: int = 3) -> list:
    """بحث بسيط بالكلمات المفتاحية"""
    if not os.path.exists(KB_FILE):
        build_index()
    
    with open(KB_FILE, 'r', encoding='utf-8') as f:
        index = json.load(f)
    
    q_kws = extract_keywords(query)
    if not q_kws:
        return index["chunks"][:top_k]  # fallback
    
    # تسجيل النقاط
    scored = []
    for chunk in index["chunks"]:
        score = sum(1 for kw in q_kws if kw in chunk["keywords"])
        # مكافأة إضافية إذا ظهر نص السؤال في القطعة
        if query.lower() in chunk["text"].lower():
            score += 2
        if score > 0:
            scored.append((score, chunk))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]

def get_context(query: str) -> str:
    """بناء سياق للـ LLM من نتائج البحث"""
    results = search(query)
    if not results:
        return ""
    
    parts = []
    for i, chunk in enumerate(results, 1):
        parts.append(f"[{i}:{chunk['source']}]\n{chunk['text']}")
    
    return "\n\n".join(parts)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
        ctx = get_context(q)
        print(f"🔍 Query: {q}\n📚 Context:\n{ctx[:600]}..." if ctx else "⚠️ No context found")
    else:
        build_index()
