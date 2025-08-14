Bot de Resumo do WhatsApp (Python + Baileys)

Resuma conversas de grupos do WhatsApp com linguagem natural, por comando no próprio grupo:

!resumo → gera/atualiza o resumo narrativo do dia (00:00 → agora) somente daquele grupo

!status → mostra contagem de mensagens do dia, provedor de IA em uso e cobertura do último resumo

Funciona em múltiplos grupos: cada grupo mantém seu próprio histórico do dia e seu próprio resumo incremental.

✨ Principais recursos

Multi‑grupos: o bot só responde no grupo onde o comando foi digitado

Resumo narrativo (1–2 parágrafos), mais humano (não lista bullets ou responsáveis)

Incremental: atualiza o resumo com o delta desde a última vez, economizando tokens

Normalização: remove ruído curto (“ok”, “kkk” etc.), agrega mensagens sequenciais do mesmo autor e deduplica

Armazenamento diário: grava mensagens em data/YYYY‑MM‑DD.jsonl (append‑only)

Rate‑limit no envio e no recebimento para evitar flood

Segurança: endpoints locais (127.0.0.1) + ACCESS_TOKEN simples

Fallback de IA: OpenAI → Gemini → heurístico local (se APIs falharem)

🧱 Arquitetura (2 processos)
WhatsApp <—Baileys—> bridge.js (Node)  <HTTP local>  app.py (FastAPI)
         mensagens → /webhook (Python) → salva JSONL → !resumo gera resposta → /send (Node) → grupo


bridge.js: conecta ao WhatsApp Web (Baileys), repassa todas as mensagens de grupos ao Python e expõe /send para o Python responder no grupo certo.

app.py: recebe cada mensagem via /webhook, salva em JSONL por dia, e processa !resumo / !status.

✅ Requisitos

Windows ou Linux/macOS

Node.js 18+

Python 3.10+

Uma conta do WhatsApp (no celular) para parear o “aparelho” do bot (QR ou código)

Dica: use um número secundário se não quiser vincular ao seu WhatsApp principal.

📦 Instalação

Clone e entre na pasta

git clone https://github.com/<seuuser>/<seu-repo>.git
cd <seu-repo>


Dependências Node

npm i


Dependências Python

pip install -r requirements.txt


Crie seu .env (use o exemplo)

copy .env.example .env   # Windows (PowerShell: cp .env.example .env)


Abra .env e configure:

# Node / bridge.js
WEBHOOK_URL=http://127.0.0.1:8000/webhook
PORT=3000
PAIR_CODE=              # opcional: 5511999999999 (sem +) para parear por código
ACCESS_TOKEN=um-token-forte

# Python / app.py
BRIDGE_URL=http://127.0.0.1:3000
ACCESS_TOKEN=um-token-forte
OPENAI_API_KEY=         # opcional
OPENAI_MODEL=gpt-4o-mini
GEMINI_API_KEY=         # opcional (fallback gratuito do Google)


IMPORTANTE: ACCESS_TOKEN deve ser o mesmo no Node e no Python.

▶️ Como rodar

Em dois terminais:

Terminal 1 (Python)

uvicorn app:app --host 127.0.0.1 --port 8000


Terminal 2 (Node)

node bridge.js


Na primeira vez, o terminal vai mostrar um QR code (ou um pairing code se você setou PAIR_CODE).

No celular: WhatsApp → Aparelhos conectados → Conectar um aparelho e siga as instruções.

Quando aparecer ✅ Conectado, o bot está pronto.

💬 Como usar no WhatsApp

No grupo em que o bot está presente, envie:

!resumo
Gera (ou atualiza) o resumo narrativo do dia, com linguagem natural, sem bullets.
A cada novo !resumo, o bot processa só o delta desde o último resumo (incremental).

!status
Mostra:

total de mensagens do dia

total “normalizado” (após limpeza e agregação)

quantas mensagens já foram cobertas no último resumo

qual provedor de IA está ativo (openai, gemini ou heuristic)

🔐 Segurança

Bind local: o bridge escuta em 127.0.0.1 (não expõe na rede).

Token: todas as chamadas Python → bridge exigem cabeçalho x-access-token com o valor de ACCESS_TOKEN.

Criptografia: o WhatsApp é E2EE. A pasta auth/ contém a sessão do seu aparelho: não compartilhe.

.gitignore: já ignora .env, auth/, data/ e cache/.

Para revogar a sessão:
WhatsApp (celular) → Aparelhos conectados → remova o “Ubuntu/Chrome”, e apague a pasta auth/.

📂 Estrutura do projeto
.
├── app.py               # FastAPI (webhook, resumo, status)
├── bridge.js            # Baileys (WhatsApp Web) + HTTP bridge
├── requirements.txt     # deps Python
├── package.json         # deps Node
├── .env.example         # modelo de variáveis
├── .gitignore           # segurança (não subir segredos/sessões/dados)
├── data/                # JSONL do dia (gerado em runtime)
└── cache/               # cache incremental por grupo (gerado em runtime)

🧠 Como funciona o resumo

O bridge envia todas as mensagens de grupos para POST /webhook (Python).

O app salva cada mensagem do dia em data/YYYY‑MM‑DD.jsonl (uma linha por mensagem).

Ao receber !resumo, o app:

carrega as mensagens de hoje do grupo que pediu,

normaliza (remove ruído, junta mensagens sequenciais do mesmo autor, dedup),

aplica resumo incremental:

se for o primeiro do dia, resume tudo;

se já houver um resumo, processa só o delta e atualiza a narrativa.

O app envia a resposta via POST /send (bridge), que publica no grupo.

Fallback de IA:

Primeiro tenta OpenAI (se OPENAI_API_KEY configurada),

depois Gemini (se GEMINI_API_KEY configurada),

por fim um heurístico local (sem custo).

🛠️ Personalização rápida

Tom do resumo: ajuste os prompts em app.py (_summ_openai, _summ_gemini) para “casual”, “executivo” etc.

Limpeza de ruído: edite o set noise em _normalize.

Tamanho do delta: a janela de deduplicação está em merged[-300:] — aumente/diminua conforme a atividade do grupo.

Rate‑limit:

bridge.js: buckets '/to-webhook' e '/send'

app.py: buckets 'webhook' e 'summary'

🧪 Testes rápidos (via cURL)

Enviar uma mensagem manualmente pelo bridge (substitua <CHAT_ID> e o token):

curl -X POST "http://127.0.0.1:3000/send" ^
  -H "Content-Type: application/json" ^
  -H "x-access-token: um-token-forte" ^
  -d "{\"chatId\":\"<CHAT_ID>@g.us\",\"text\":\"mensagem de teste\"}"

🩺 Solução de problemas

No grupo aparece “Resumo indisponível”
Verifique se existe chave configurada e saldo:

OPENAI_API_KEY válida? Se der 429/quota, o app cai no Gemini (se houver) ou no heurístico.

GEMINI_API_KEY válida? Se falhar, cai no heurístico.

Mesmo sem chaves, o resumo sai (mais simples).

O bridge mostra “opened connection to WA” e fica parado
Isso é normal. Ele só imprime eventos quando chegam mensagens.
Garanta que o Python está rodando, e envie mensagens no grupo para ver tráfego.

O Python não recebe nada

Confirme WEBHOOK_URL=http://127.0.0.1:8000/webhook no .env do Node

ACCESS_TOKEN é o mesmo nos dois lados?

Firewall não bloqueia 127.0.0.1:3000/8000?

Rate‑limit
Se aparecer rate_limited, espere 1–2 segundos e tente de novo.
Ajuste os buckets se o grupo é muito ativo.

Sessão perdida / desconectou

Remova auth/ e pareie novamente (QR ou PAIR_CODE).

No celular, “Aparelhos conectados” deve mostrar o device “Ubuntu/Chrome”.

Backfill (histórico antes de ligar o bot)
A versão atual está no modo “gravar ao chegar” (sem backfill).
Para capturar mensagens anteriores ao start, deixe o bot ligado desde cedo (ou meça a troca de pacote Baileys que suporte backfill).

🔒 .gitignore e segredos

O repositório inclui um .gitignore que evita vazamento de:

.env (chaves e tokens)

auth/ (sessão do WhatsApp)

data/ (mensagens do dia)

cache/ (resumo incremental)

Use o .env.example como referência para outras pessoas configurarem localmente.

📜 Licença

Escolha a licença que preferir (ex.: MIT).
Crie um arquivo LICENSE na raiz do projeto.

🙋 FAQ

Posso usar em mais de um grupo?
Sim. O bridge manda mensagens de todos os grupos onde o número está. O !resumo e !status funcionam por grupo.

Ele responde mensagens privadas (1:1)?
Não — está filtrando para @g.us (grupos). Pode ser adaptado.

Dá para agendar um resumo automático todo dia às 20h?
Sim — adicione APScheduler no app.py e chame summarize_incremental para cada grupo desejado.

Onde ficam os dados?
Em data/YYYY‑MM‑DD.jsonl (append‑only) e cache/ (resumo incremental por grupo/dia).
