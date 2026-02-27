"""
Configurações centralizadas para o agente de triagem de licitações.
Carrega variáveis de ambiente e define constantes do sistema.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── ConLicitação ──────────────────────────────────────────────
CONLICITACAO_URL = "https://consulteonline.conlicitacao.com.br"
CONLICITACAO_EMAIL = os.getenv("CONLICITACAO_EMAIL", "")
CONLICITACAO_PASSWORD = os.getenv("CONLICITACAO_PASSWORD", "")

# ── OpenAI ────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL_TRIAGE = "gpt-4o-mini"       # Pré-triagem rápida
OPENAI_MODEL_ANALYSIS = "gpt-4o"           # Análise profunda (Alta aderência)

# ── Supabase ──────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ── Evolution API (WhatsApp) ──────────────────────────────────
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://localhost:8080")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "indflow")
WHATSAPP_RECIPIENT = os.getenv("WHATSAPP_RECIPIENT", "")

# ── Server ────────────────────────────────────────────────────
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

# ── Diretórios ────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
XLSX_DIR = os.path.join(DOWNLOADS_DIR, "xlsx")
ZIP_DIR = os.path.join(DOWNLOADS_DIR, "zips")
PDF_DIR = os.path.join(DOWNLOADS_DIR, "pdfs")

for d in [DOWNLOADS_DIR, XLSX_DIR, ZIP_DIR, PDF_DIR]:
    os.makedirs(d, exist_ok=True)

# ── Catálogo IndFlow (para classificação de aderência) ────────
CATALOGO_INDFLOW = {
    "medidores_vazao": [
        "medidor de vazão",
        "medidor de vazao",
        "turbina para gases",
        "turbina para líquidos",
        "ultrassônico clamp-on",
        "calha parshall",
        "eletromagnético",
        "hidrômetro",
        "hidrometro",
        "rotâmetro",
        "rotametro",
        "totalizador de volume",
        "medição de vazão",
        "medicao de vazao",
    ],
    "transmissores_nivel": [
        "transmissor de nível",
        "transmissor de nivel",
        "sonda hidrostática",
        "sonda hidrostatica",
        "sensor de nível",
        "sensor de nivel",
        "radar de nível",
        "radar de nivel",
        "medição de nível",
        "medicao de nivel",
        "nível ultrassônico",
        "nivel ultrassonico",
    ],
    "indicadores_controladores": [
        "indicador de painel",
        "controlador de processo",
        "dosador",
        "feeder",
        "indicador digital",
        "controlador digital",
        "indicador multiparâmetro",
    ],
    "telemetria": [
        "datalogger",
        "data logger",
        "telemetria",
        "aquisição de dados",
        "aquisicao de dados",
        "comunicação de dados",
        "SCADA",
    ],
    "sensores": [
        "sensor ultrassônico",
        "sensor ultrassonico",
        "MaxBotix",
    ],
}

# Keywords que indicam alta aderência (match direto com produtos)
KEYWORDS_ALTA = []
for categoria in CATALOGO_INDFLOW.values():
    KEYWORDS_ALTA.extend(categoria)
KEYWORDS_ALTA.extend([
    "instrumentação industrial",
    "instrumentacao industrial",
    "instrumento de medição",
    "instrumento de medicao",
])

# Keywords que indicam média aderência (setor adjacente)
KEYWORDS_MEDIA = [
    "automação industrial",
    "automacao industrial",
    "saneamento",
    "estação de tratamento",
    "estacao de tratamento",
    "ETA",
    "ETE",
    "monitoramento de água",
    "monitoramento de agua",
    "controle de processos",
    "tratamento de água",
    "tratamento de agua",
    "cloração",
    "cloracao",
    "tubulações industriais",
    "tubulacoes industriais",
    "processo industrial",
    "abastecimento de água",
    "abastecimento de agua",
]

# ── Scraping Config ───────────────────────────────────────────
SCRAPING_DELAY_MIN = 2    # Delay mínimo entre ações (segundos)
SCRAPING_DELAY_MAX = 5    # Delay máximo entre ações (segundos)
DOWNLOAD_TIMEOUT = 60     # Timeout para downloads (segundos)
MAX_RETRIES = 3           # Tentativas em caso de falha
