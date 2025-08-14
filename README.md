# 🤖 Bot de Resumo do WhatsApp (Python + Baileys)

Um bot que **resume conversas de grupos do WhatsApp** em linguagem natural.  
Você chama no próprio grupo com `!resumo` e ele conta, em 1–2 parágrafos, o que rolou **hoje**.  
Também tem `!status` para ver estatísticas do dia.

---

## 🚀 Comandos disponíveis

**`!resumo`**  
Gera **ou atualiza** o resumo narrativo do dia (00:00 → agora) **apenas do grupo onde o comando foi enviado**.  
O resumo é **incremental**: a cada chamada, ele processa só o que mudou desde o último resumo.

**`!status`**  
Mostra:
- Mensagens do dia (brutas e “normalizadas”)
- Quantas mensagens já foram cobertas no último resumo
- Provedor de IA em uso (`openai`, `gemini` ou `heuristic`)

---

## ✨ Principais recursos

- **Multi‑grupos**: cada grupo mantém histórico e resumo independentes
- **Resumo narrativo humano** (1–2 parágrafos), sem bullets secos
- **Incremental**: processa apenas o delta desde o último resumo
- **Normalização**: remove ruído curto (“ok”, “kkk” etc.), agrega mensagens sequenciais do mesmo autor e faz dedup
- **Armazenamento diário**: salva em `data/YYYY‑MM‑DD.jsonl` (append‑only)
- **Rate‑limit**: limita chamadas de entrada/saída para evitar flood
- **Segurança**: endpoints locais (`127.0.0.1`) e `ACCESS_TOKEN`
- **Fallback inteligente**: OpenAI → Gemini → heurística local (sem custo)

---

## 🛠 Arquitetura

```
WhatsApp → Baileys (Node) → bridge.js → app.py (FastAPI)
mensagens → /webhook (Python) → salva JSONL → IA gera resposta → /send (Node) → grupo
```

- **bridge.js**: conecta ao WhatsApp (Baileys), repassa **todas** as mensagens de grupos ao Python e expõe `/send` para o app responder no grupo certo.  
- **app.py**: recebe as mensagens, grava em JSONL por dia e cuida dos comandos `!resumo` / `!status`.

---

## ✅ Requisitos

- Node.js **18+**
- Python **3.10+**
- WhatsApp no celular para parear (QR ou código)
- Windows, macOS ou Linux

> Dica: se puder, use um **número secundário** para o bot.

---

## 📦 Instalação

### 1) Clonar o repositório
```bash
git clone https://github.com/<seu-usuario>/<seu-repo>.git
cd <seu-repo>
```

### 2) Instalar dependências
```bash
# Node (bridge)
npm i

# Python (API)
pip install -r requirements.txt
```

### 3) Configurar variáveis de ambiente
Crie um arquivo **.env** na raiz (baseado no `.env.example`):

```env
# Node / bridge.js
WEBHOOK_URL=http://127.0.0.1:8000/webhook
PORT=3000
PAIR_CODE=              # opcional: 5511999999999 (sem +) para parear por código
ACCESS_TOKEN=um-token-forte

# Python / app.py
BRIDGE_URL=http://127.0.0.1:3000
ACCESS_TOKEN=um-token-forte            # igual ao do bridge
OPENAI_API_KEY=                        # opcional
OPENAI_MODEL=gpt-4o-mini
GEMINI_API_KEY=                        # opcional
```

> O `ACCESS_TOKEN` **deve ser o mesmo** no Node e no Python.

---

## ▶️ Como rodar

Em **dois terminais** (na raiz do projeto):

**Terminal 1 – API Python**  
```bash
uvicorn app:app --host 127.0.0.1 --port 8000
```

**Terminal 2 – Bridge Node**  
```bash
node bridge.js
```
- Na primeira execução, aparecerá um **QR code** (ou **pairing code** se você definiu `PAIR_CODE`).  
- No celular: **WhatsApp → Aparelhos conectados → Conectar um aparelho**.

Quando o terminal mostrar `✅ Conectado`, o bot está pronto.

---

## 💬 Uso no WhatsApp

No **grupo** em que o bot está presente, envie:

- `!resumo` → gera/atualiza o **resumo narrativo** do dia daquele grupo
- `!status` → mostra estatísticas (contagem, provedor ativo, cobertura, etc.)

> Observação: este modo não “busca histórico para trás”. Ele resume o que foi gravado **desde que o bot está ligado** hoje. Para pegar o dia todo, deixe o bot rodando continuamente.

---

## 🔐 Segurança

- **Bind local**: os serviços escutam apenas em `127.0.0.1` (não exposto na rede)
- **Token obrigatório**: o Python chama o `/send` do bridge com `x-access-token: ACCESS_TOKEN`
- **Sessão do WhatsApp**: fica em `auth/` → **não compartilhe**. Para revogar: remova o aparelho no WhatsApp e apague `auth/`.

### .gitignore recomendado
```gitignore
# Segredos / sessões / dados
.env
auth/
data/
cache/

# Node
node_modules/
npm-debug.log*
package-lock.json

# Python
__pycache__/
*.pyc
.venv/
venv/

# IDE / SO
.vscode/
.DS_Store
Thumbs.db
```

---

## 🧩 Personalização rápida

- **Tom do resumo**: edite os prompts em `app.py` (`_summ_openai` / `_summ_gemini`) – “casual”, “executivo”, etc.
- **Limpeza de ruído**: ajuste o set `noise` em `_normalize`.
- **Janela de dedup**: altere o tamanho de `merged[-300:]` conforme a atividade do grupo.
- **Rate‑limit**: mude os buckets no `bridge.js` (`/to-webhook`, `/send`) e no `app.py` (`webhook`, `summary`).

---

## 🩺 Solução de problemas

- **Bridge “parado” no console**: normal; ele só imprime algo quando chegam mensagens/eventos.
- **Python não recebe nada**: confira `WEBHOOK_URL` e o `ACCESS_TOKEN` em ambos os lados.
- **429/Quota na OpenAI**: o app usa Gemini (se houver) e, na ausência, um heurístico local (sempre funciona).
- **Desconectou / “device_removed”**: apague `auth/` e pareie de novo.

---

## 📂 Estrutura do projeto

```
.
├── app.py               # FastAPI (webhook, resumo, status)
├── bridge.js            # WhatsApp bridge (Baileys)
├── requirements.txt     # Dependências Python
├── package.json         # Dependências Node
├── .env.example         # Modelo de variáveis
├── .gitignore           # Segurança (ignora .env, auth/, data/, cache/)
├── data/                # JSONL diário (gerado em runtime)
└── cache/               # Cache incremental por grupo (gerado em runtime)
```

---

## 📜 Licença

Este projeto é distribuído sob a licença **MIT**.  
Use, modifique e compartilhe com crédito. :)

---

## 🙋 FAQ

**Funciona em vários grupos?**  
Sim. O bridge envia mensagens de todos os grupos e o app responde **somente no grupo que pediu**.

**Atende mensagens privadas (1:1)?**  
Não. O filtro atual considera apenas JIDs terminando com `@g.us` (grupos). Pode ser adaptado facilmente.

**Dá pra agendar um resumo diário automático?**  
Sim. Adicione APScheduler no `app.py` e chame `summarize_incremental()` no horário desejado.
