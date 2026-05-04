#!/usr/bin/env python3
"""
OpenClaw Token Saver — Claude-Mem Style Compression for All Agents
Inspired by: https://github.com/thedotmack/claude-mem
"""
import os, json, time, hashlib, requests, re
from datetime import datetime, timedelta
from collections import deque

# === إعدادات ===
OLLAMA = "http://localhost:11434/api/generate"
VAULT = "/root/radiantedge-vault"
MEM_DB = f"{VAULT}/memory/token_db.json"
os.makedirs(os.path.dirname(MEM_DB), exist_ok=True)

# === ميزانيات التوكنز لكل وكيل ===
TOKEN_BUDGETS = {
    "ceo": {"max_ctx_tokens": 1200, "keep_recent": 3, "model": "qwen2.5:7b"},
    "storage": {"max_ctx_tokens": 800, "keep_recent": 2, "model": "qwen2.5:1.5b"},
    "engineer": {"max_ctx_tokens": 1000, "keep_recent": 3, "model": "qwen2.5:1.5b"},
    "creative": {"max_ctx_tokens": 900, "keep_recent": 2, "model": "qwen2.5:1.5b"},
}

# === قاعدة بيانات الذاكرة المضغوطة ===
class CompressedMemory:
    def __init__(self):
        self.db = self._load()
    
    def _load(self):
        if os.path.exists(MEM_DB):
            with open(MEM_DB, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"users": {}}
    
    def _save(self):
        with open(MEM_DB, 'w', encoding='utf-8') as f:
            json.dump(self.db, f, ensure_ascii=False, indent=2)
    
    def add_message(self, uid: str, agent: str, role: str, text: str):
        """إضافة رسالة مع ضغط تلقائي عند تجاوز الحد"""
        if uid not in self.db["users"]:
            self.db["users"][uid] = {"agents": {}}
        if agent not in self.db["users"][uid]["agents"]:
            self.db["users"][uid]["agents"][agent] = {
                "recent": deque(maxlen=TOKEN_BUDGETS[agent]["keep_recent"]),
                "summary": "",
                "last_compress": 0
            }
        
        mem = self.db["users"][uid]["agents"][agent]
        mem["recent"].append({"role": role, "text": text[:200], "ts": time.time()})  # اقتطاع للحفظ
        
        # ضغط تلقائي كل 10 دقائق أو عند امتلاء النافذة
        if len(mem["recent"]) >= TOKEN_BUDGETS[agent]["keep_recent"] or \
           time.time() - mem["last_compress"] > 600:
            self._compress(uid, agent)
        self._save()
    
    def _compress(self, uid: str, agent: str):
        """تلخيص المحادثة القديمة وحفظها في Obsidian"""
        mem = self.db["users"][uid]["agents"][agent]
        if not mem["recent"]: return
        
        # تجميع النص للتلخيص
        chat = "\n".join([f"{m['role']}: {m['text']}" for m in mem["recent"]])
        prompt = f"""لخّص هذه المحادثة في 2-3 نقاط قصيرة جداً (عربي):
{chat}
المخرجات: نقاط فقط، بدون مقدمة."""
        
        try:
            r = requests.post(OLLAMA, json={
                "model": TOKEN_BUDGETS[agent]["model"],
                "prompt": prompt, "stream": False,
                "options": {"temperature": 0.1, "num_predict": 80, "num_ctx": 500}
            }, timeout=20)
            summary = r.json().get("response", "").strip()
            if summary and len(summary) > 20:
                mem["summary"] = summary
                # حفظ في Obsidian كمرجع دائم
                self._save_to_obsidian(uid, agent, summary, chat)
                # تفريغ النافذة الحديثة (الاحتفاظ بآخر رسالة فقط للسياق)
                while len(mem["recent"]) > 1:
                    mem["recent"].popleft()
                mem["last_compress"] = time.time()
        except Exception as e:
            print(f"Compression error: {e}")
    
    def _save_to_obsidian(self, uid: str, agent: str, summary: str, original: str):
        """حفظ الملخص في Obsidian مع رابط للنص الأصلي المضغوط"""
        fname = f"{VAULT}/memory/compressed/{agent}_{uid}_{int(time.time())}.md"
        os.makedirs(os.path.dirname(fname), exist_ok=True)
        with open(fname, 'w', encoding='utf-8') as f:
            f.write(f"""---
uid: {uid}
agent: {agent}
ts: {datetime.now().isoformat()}
type: compressed_memory
---
# ملخص مضغوط
{summary}

---
## النص الأصلي (مقتطف)
{original[:500]}...
""")
    
    def get_context(self, uid: str, agent: str, query: str = None) -> str:
        """جلب السياق المضغوط + الذاكرة ذات الصلة فقط"""
        if uid not in self.db["users"] or agent not in self.db["users"][uid]["agents"]:
            return ""
        
        mem = self.db["users"][uid]["agents"][agent]
        budget = TOKEN_BUDGETS[agent]
        
        # 1. بدء بالملخص القديم (إذا وجد)
        ctx = mem["summary"] if mem["summary"] else ""
        
        # 2. إضافة الرسائل الحديثة فقط
        recent = [f"{m['role']}: {m['text']}" for m in mem["recent"]]
        if recent:
            ctx += "\n[أحدث]: " + " | ".join(recent)
        
        # 3. إذا كان هناك استعلام، جلب ذاكرة ذات صلة من Obsidian (محاكاة بحث متجهي بسيط)
        if query and len(query) > 10:
            relevant = self._fetch_relevant(uid, agent, query)
            if relevant:
                ctx += f"\n[ذاكرة ذات صلة]: {relevant[:200]}"
        
        # 4. قطع زائد لضمان عدم تجاوز الميزانية
        return ctx[:budget["max_ctx_tokens"]]
    
    def _fetch_relevant(self, uid: str, agent: str, query: str) -> str:
        """محاكاة بحث ذاكرة: جلب آخر ملخص يحتوي على كلمات مفتاحية"""
        keywords = [w for w in re.findall(r'[\u0600-\u06FF\w]+', query.lower()) if len(w) > 3]
        if not keywords: return ""
        
        # بحث بسيط في ملفات الذاكرة المضغوطة
        mem_dir = f"{VAULT}/memory/compressed"
        if not os.path.exists(mem_dir): return ""
        
        for fname in sorted(os.listdir(mem_dir))[-5:]:  # آخر 5 ملفات فقط
            if agent in fname and uid in fname:
                try:
                    with open(f"{mem_dir}/{fname}", 'r', encoding='utf-8') as f:
                        content = f.read()
                        if any(kw in content.lower() for kw in keywords):
                            # استخراج أول نقطة ذات صلة
                            match = re.search(r'•\s*([^\n]+)', content)
                            if match: return match.group(1)
                except: pass
        return ""

# === دالة مساعدة للاستخدام السريع ===
def estimate_tokens(text: str) -> int:
    """تقدير تقريبي لعدد التوكنز (عربي: ~3 أحرف/توكن، إنجليزي: ~4 أحرف/توكن)"""
    arabic = len(re.findall(r'[\u0600-\u06FF]', text))
    other = len(text) - arabic
    return (arabic // 3) + (other // 4) + 1

# === واجهة سطر الأوامر للاختبار ===
if __name__ == "__main__":
    import sys
    mem = CompressedMemory()
    
    if len(sys.argv) < 2:
        print("Usage: python token_saver.py <uid> <agent> <message>")
        print("Example: python token_saver.py user123 ceo 'ما هي خطة لندن؟'")
        sys.exit(0)
    
    uid, agent, msg = sys.argv[1], sys.argv[2], " ".join(sys.argv[3:])
    mem.add_message(uid, agent, "user", msg)
    ctx = mem.get_context(uid, agent, msg)
    print(f"✅ Context ({estimate_tokens(ctx)} tokens): {ctx[:200]}...")
