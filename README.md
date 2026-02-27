# IndFlow — Agente de Triagem de Licitações

Automação completa do fluxo de triagem de licitações do ConLicitação para a IndFlow.

## Arquitetura

```
Email IMAP → n8n → Python Worker (FastAPI) → Supabase + WhatsApp
```

### Fluxo:
1. **n8n** detecta e-mail do ConLicitação
2. **n8n** chama a API do Python Worker
3. **Worker** faz login no ConLicitação via Playwright
4. **Worker** exporta dados do boletim (.xlsx)
5. **Worker** faz triagem rápida (GPT-4o-mini) de todas as licitações
6. **Worker** baixa editais de Alta aderência + análise profunda (GPT-4o)
7. **Worker** salva no Supabase + envia relatório no WhatsApp

## Setup

### 1. Instalar dependências
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configurar variáveis de ambiente
```bash
cp .env.example .env
# Editar .env com suas credenciais
```

### 3. Criar tabelas no Supabase
Execute o conteúdo de `schema.sql` no SQL Editor do Supabase.

### 4. Iniciar o Worker
```bash
python -m worker.api
```

O servidor inicia em `http://localhost:8000`.

### 5. Configurar n8n
Importe o workflow `n8n_workflow.json` no seu n8n.
Configure o nó IMAP com suas credenciais de e-mail.

## Endpoints

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/process` | Processa boletim (síncrono) |
| `POST` | `/process-async` | Processa boletim (background) |

### Payload `/process`
```json
{
  "email_subject": "[4648] Serviço ConLicitação de 19 de Fevereiro de 2026, 13:01",
  "email_html": "<html>...",
  "download_editais": true,
  "send_whatsapp": true
}
```

## Estrutura
```
indflow/
├── .env.example         # Template de variáveis de ambiente
├── requirements.txt     # Dependências Python
├── schema.sql          # Schema do Supabase
├── n8n_workflow.json   # Workflow n8n para importar
├── README.md
└── worker/
    ├── __init__.py
    ├── config.py       # Configurações e catálogo IndFlow
    ├── scraper.py      # Playwright: login + export XLSX
    ├── pdf_parser.py   # Parse XLSX + ZIP + PDF
    ├── analyzer.py     # Análise IA (triagem + análise profunda)
    ├── database.py     # Integração Supabase
    ├── whatsapp.py     # Relatório via Evolution API
    ├── pipeline.py     # Orquestrador do fluxo completo
    └── api.py          # FastAPI server
```
