# app.py
import os, json, time, hashlib, requests
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import List
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
BRIDGE_URL     = os.getenv("BRIDGE_URL", "http://127.0.0.1:3000").strip()
ACCESS_TOKEN   = os.getenv("ACCESS_TOKEN", "").strip()

# clientes (opcionais)
try:
    from openai import OpenAI
    _openai = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception:
    _openai = None

try:
    import google.generativeai as genai
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        _gemini = genai.GenerativeModel("gemini-1.5-flash")
    else:
        _gemini = None
except Exception:
    _gemini = None

app = FastAPI(title="WA Resumo – on-demand (dia todo)")

# ---- rate-limit simples (/webhook: 5/s; /summary: 2/s) ----
_buckets = {"webhook": {"cap":5,"tok":5,"last":time.time()},
            "summary": {"cap":2,"tok":2,"last":time.time()}}
def take(name:str):
    b=_buckets[name]; now=time.time()
    if now-b["last"]>=1.0:
        b["tok"]=b["cap"]; b["last"]=now
    if b["tok"]>0: b["tok"]-=1; return True
    return False

# ---- cache incremental por grupo (arquivo) ----
CACHE_DIR = Path("cache"); CACHE_DIR.mkdir(exist_ok=True)
def _cache_path(chat_id: str) -> Path:
    date = datetime.now().strftime("%Y-%m-%d")
    h = hashlib.sha1(chat_id.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{date}_{h}.json"
def _get_cache(chat_id: str) -> dict:
    p=_cache_path(chat_id)
    if p.exists():
        try: return json.loads(p.read_text(encoding="utf-8"))
        except: pass
    return {}
def _set_cache(chat_id: str, data: dict):
    _cache_path(chat_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ---- helpers ----
def _midnight_iso() -> str:
    return datetime.combine(datetime.now().date(), dt_time.min).isoformat() + "Z"

def _fetch_today(chat_id: str, limit: int = 1200) -> List[dict]:
    """Busca do bridge todas as msgs do grupo desde 00:00 (on-demand)."""
    headers = {'x-access-token': ACCESS_TOKEN} if ACCESS_TOKEN else {}
    r = requests.get(
        f"{BRIDGE_URL}/fetch_today",
        params={"chatId": chat_id, "since": _midnight_iso(), "limit": limit},
        headers=headers, timeout=30
    )
    if r.status_code == 501:
        # backfill não suportado na versão do Baileys
        raise RuntimeError("backfill_not_supported")
    r.raise_for_status()
    data = r.json()
    return data.get("items", [])

def _normalize(items: List[dict]) -> List[dict]:
    noise = {"bom dia","boa tarde","boa noite","ok","blz","beleza","show","kk","kkk","rs","vlw","valeu"}
    clean=[]
    for m in items:
        t=(m.get("text") or "").strip()
        if len(t)<3: continue
        if t.lower() in noise: continue
        clean.append({"author": m.get("author") or "Contato", "text": t, "at": m.get("at"), "chatId": m.get("chatId")})
    # junta sequências do mesmo autor
    merged=[]
    for m in clean:
        if merged and merged[-1]["author"]==m["author"]:
            merged[-1]["text"]+=" "+m["text"]; merged[-1]["at"]=m["at"]
        else:
            merged.append(m)
    # dedup leve
    seen=set(); out=[]
    for m in merged:
        key=(m["author"], m["text"])
        if key in seen: continue
        seen.add(key); out.append(m)
    return out

def _fmt_block(items: List[dict]) -> str:
    from datetime import datetime as dt
    lines=[]
    for m in items:
        ts = dt.fromisoformat(m["at"].replace("Z","")).strftime("%H:%M")
        lines.append(f"- [{ts}] {m['author']}: {m['text']}")
    return "\n".join(lines)

def _send(chat_id: str, text: str):
    headers = {'x-access-token': ACCESS_TOKEN} if ACCESS_TOKEN else {}
    requests.post(f"{BRIDGE_URL}/send", json={"chatId": chat_id, "text": text}, headers=headers, timeout=10)

# ---- sumarização (narrativa + incremental) ----
def _summ_openai(prev: str|None, new_block: str) -> str|None:
    if not _openai: return None
    msgs=[{"role":"system","content":"Escreva resumos narrativos curtos e naturais, 1–2 parágrafos."}]
    if prev:
        msgs.append({"role":"user","content":f"Resumo atual:\n{prev}\n\nAtualize com APENAS o trecho novo abaixo, mantendo o tom e a concisão:"})
    else:
        msgs.append({"role":"user","content":"Gere um resumo narrativo (00:00→agora) do trecho abaixo:"})
    msgs.append({"role":"user","content":new_block})
    try:
        r=_openai.chat.completions.create(model=OPENAI_MODEL,temperature=0.4,messages=msgs)
        return (r.choices[0].message.content or "").strip()
    except Exception as e:
        print("openai fail:", e); return None

def _summ_gemini(prev: str|None, new_block: str) -> str|None:
    if not _gemini: return None
    if prev:
        prompt=(f"Atualize o resumo narrativo (1–2 parágrafos, PT‑BR, tom humano) com APENAS o trecho novo.\n\nResumo atual:\n{prev}\n\nTrecho novo:\n{new_block}")
    else:
        prompt=("Resuma narrativamente (1–2 parágrafos, PT‑BR) o trecho abaixo (00:00→agora), sem bullets:\n\n"+new_block)
    try:
        r=_gemini.generate_content(prompt)
        return (getattr(r,"text",None) or "").strip()
    except Exception as e:
        print("gemini fail:", e); return None

def _summ_heur(prev: str|None, items: List[dict]) -> str:
    parts=[f"{m['author']} comentou: {m['text']}" for m in items[-12:]]
    body=" ".join(parts)[:1200]
    if prev: return (prev+" "+body)[-1200:]
    return "Ao longo do dia, a conversa girou em torno de: "+body

def summarize_incremental(chat_id: str):
    # pega tudo do dia (on-demand)
    try:
        items = _fetch_today(chat_id)
    except RuntimeError:
        _send(chat_id, "⚠️ Não consigo buscar o histórico neste cliente. Atualize o bridge ou deixe o bot rodar desde cedo.")
        return {"ok": False, "error": "backfill_not_supported"}
    except Exception as e:
        _send(chat_id, f"⚠️ Erro ao buscar o histórico: {e}")
        return {"ok": False, "error": str(e)}

    norm = _normalize(items)
    cache = _get_cache(chat_id)   # { last_n, summary }
    last_n = int(cache.get("last_n", 0))
    prev   = cache.get("summary", "")

    if not prev:
        block = _fmt_block(norm)
        summary = _summ_openai(None, block) or _summ_gemini(None, block) or _summ_heur(None, norm)
        _set_cache(chat_id, {"last_n": len(norm), "summary": summary})
        _send(chat_id, f"📝 *Resumo do dia*\n{summary}")
        return {"ok": True, "count": len(norm), "mode": "init"}

    # incremental
    delta = norm[last_n:] if last_n < len(norm) else []
    if not delta:
        _send(chat_id, "🆗 Nada novo desde o último resumo.")
        return {"ok": True, "count": len(norm), "mode": "nochange"}

    block = _fmt_block(delta)
    summary = _summ_openai(prev, block) or _summ_gemini(prev, block) or _summ_heur(prev, delta)
    _set_cache(chat_id, {"last_n": len(norm), "summary": summary})
    _send(chat_id, f"📝 *Resumo atualizado*\n{summary}")
    return {"ok": True, "count": len(norm), "mode": "update"}

def group_status(chat_id: str):
    try:
        items = _fetch_today(chat_id, limit=200)
    except Exception:
        items = []
    norm = _normalize(items)
    cache = _get_cache(chat_id)
    used  = "openai" if _openai else ("gemini" if _gemini else "heuristic")
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "msgs_today": len(items),
        "msgs_norm": len(norm),
        "covered": int(cache.get("last_n", 0)),
        "provider": used,
        "has_summary": bool(cache.get("summary"))
    }

# ===== models & endpoints =====
class BridgeMsg(BaseModel):
    at: str
    author: str
    text: str
    chatId: str
    chatName: str | None = None

@app.get("/health")
def health(): return {"ok": True}

@app.post("/webhook")
def webhook(m: BridgeMsg, x_access_token: str | None = Header(None)):
    if ACCESS_TOKEN and x_access_token != ACCESS_TOKEN:
        raise HTTPException(401, "unauthorized")
    if not take("webhook"):
        return {"ok": False, "error": "rate_limited"}

    t = (m.text or "").strip().lower()
    if t.startswith("!resumo") or t.startswith("/resumo"):
        return summarize_incremental(m.chatId)
    if t.startswith("!status") or t.startswith("/status"):
        st = group_status(m.chatId)
        _send(
            m.chatId,
            "📊 Status {d}\n- Mensagens hoje: {r} (normalizadas: {n})\n- Último resumo cobre: {c}\n- Provider: {p}\n- Tem resumo salvo: {h}".format(
                d=st["date"], r=st["msgs_today"], n=st["msgs_norm"], c=st["covered"], p=st["provider"], h="sim" if st["has_summary"] else "não"
            )
        )
        return {"ok": True}
    return {"ok": True}

@app.post("/summary/run")
def run_summary(chatId: str):
    if not take("summary"): raise HTTPException(429, "rate_limited")
    return summarize_incremental(chatId)
