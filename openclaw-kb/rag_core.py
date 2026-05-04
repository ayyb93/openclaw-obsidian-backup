#!/usr/bin/env python3
"""Simple RAG Core for OpenCLaw — Obsidian-backed"""
import os, re, json, time, hashlib
from pathlib import Path

VAULT = "/root/radiantedge-vault"
KB_DIR = f"{VAULT}/knowledge"
os.makedirs(KB_DIR, exist_ok=True)

class SimpleRAG:
    def __init__(self):
        self.index = self._build_index()
    
    def _build_index(self):
        """فهرسة بسيطة: استخراج نصوص من ملفات المشروع"""
        index = {"chunks": [], "meta": {}}
        
        # ملفات المعرفة الثابتة
        files = [
            "/root/OpenCLaw_Master_Blueprint.md",
            "/root/RadiantEdge_Brief.md"  # سننشئه من الـ PDF
        ]
        
        for fpath in files:
            if not os.path.exists(fpath): continue
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # تقسيم إلى فقرات ذكية
            paragraphs = re.split(r'\n\s*\n|#{2,}', content)
            for i, para in enumerate(paragraphs):
                para = para.strip()
                if len(para) < 50 or len(para) > 800: continue
                # إنشاء قطعة معرفية
                chunk = {
                    "id": hashlib.md5(f"{fpath}:{i}".encode()).hexdigest()[:8],
                    "source": os.path.basename(fpath),
                    "text": para[:700],
                    "keywords": self._extract_keywords(para)
                }
                index["chunks"].append(chunk)
        
        index["meta"] = {"total": len(index["chunks"]), "updated": time.time()}
        self._save_index(index)
        return index
    
    def _extract_keywords(self, text: str) -> list:
        """استخراج كلمات مفتاحية بسيطة (عربي + إنجليزي)"""
        # كلمات مشروعنا المهمة
        project_kws = [
            'radiantedge', 'openclaw', 'dropshipping', 'luxury', 'hypoallergenic',
            'ceo', 'archivist', 'engineer', 'creative', 'obsidian', 'n8n', 'shopify',
            'لندن', 'نيويورك', 'دبي', 'فخامة', 'وكلاء', 'أتمتة', 'محتوى', 'يوتيوب'
        ]
        text_lower = text.lower()
        return [kw for kw in project_kws if kw in text_lower]
    
    def _save_index(self, index):
        with open(f"{KB_DIR}/index.json", 'w', encoding='utf-8') as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
    
    def search(self, query: str, top_k: int = 3) -> list:
        """بحث بسيط بالكلمات المفتاحية (بدون متجهات)"""
        q_kws = self._extract_keywords(query)
        if not q_kws:
            # fallback: إرجاع أحدث القطع
            return self.index["chunks"][-top_k:]
        
        # تسجيل النقاط: كل كلمة مفتاحية مطابقة = +1 نقطة
        scored = []
        for chunk in self.index["chunks"]:
            score = sum(1 for kw in q_kws if kw in chunk["keywords"])
            if score > 0:
                scored.append((score, chunk))
        
        # ترتيب وإرجاع الأفضل
        scored.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]
    
    def get_context(self, query: str) -> str:
        """بناء سياق للـ LLM من نتائج البحث"""
        results = self.search(query)
        if not results:
            return ""
        
        context_parts = []
        for i, chunk in enumerate(results, 1):
            context_parts.append(f"[مصدر {i}: {chunk['source']}]\n{chunk['text']}")
        
        return "\n\n".join(context_parts)

# دالة مساعدة للاستخدام السريع
def get_kb_context(question: str) -> str:
    rag = SimpleRAG()
    return rag.get_context(question)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
        ctx = get_kb_context(q)
        print(f"🔍 Query: {q}\n📚 Context:\n{ctx[:500]}..." if ctx else "⚠️ No relevant context found")
    else:
        print("Usage: python rag_core.py 'your question'")
