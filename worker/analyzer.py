"""
Módulo de análise por IA.
Usa LLM para gerar resumos, classificar aderência e recomendar ações.
"""

import json
import logging
from openai import AsyncOpenAI

from . import config

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

# ── Prompts ───────────────────────────────────────────────────

SYSTEM_PROMPT_TRIAGE = """Você é um analista especializado em licitações públicas trabalhando para a **IndFlow**, empresa de instrumentação industrial.

## Catálogo de Produtos IndFlow:
- **Medidores de Vazão**: turbina (gases/líquidos), ultrassônico clamp-on, calha Parshall, eletromagnético (BLIT-EM), hidrômetros, rotâmetros, totalizadores de volume
- **Transmissores de Nível**: sondas hidrostáticas (17mm, 28mm, PTFE), radar (BLIT-R), ultrassônico
- **Indicadores/Controladores**: dosadores (feeder) para painel, indicadores multiparâmetros, indicadores à prova de tempo, série BLIT
- **Telemetria**: dataloggers, aquisição e comunicação de dados
- **Sensores**: MaxBotix (ultrassônicos)

## Sua tarefa:
Analise o OBJETO da licitação e classifique a aderência ao portfólio da IndFlow.

Responda APENAS com um JSON válido:
{
  "aderencia": "ALTA" | "MEDIA" | "BAIXA",
  "motivo": "justificativa breve",
  "keywords_match": ["palavras que casaram"]
}

### Critérios:
- **ALTA**: Objeto menciona diretamente produtos do catálogo IndFlow ou instrumentação industrial/medição
- **MEDIA**: Setor adjacente (saneamento, ETA/ETE, automação industrial, monitoramento de água) onde IndFlow pode participar
- **BAIXA**: Sem relação com instrumentação industrial"""

SYSTEM_PROMPT_ANALYSIS = """Você é um analista de licitações experiente trabalhando para a **IndFlow**, fabricante de instrumentação industrial (medidores de vazão, transmissores de nível, indicadores, controladores, telemetria).

Analise o edital da licitação e gere um relatório completo.

Responda APENAS com um JSON válido:
{
  "resumo_executivo": "Resumo do edital em até 200 palavras — pontos principais, o que está sendo licitado",
  "objeto_detalhado": "Descrição detalhada do que está sendo comprado/contratado",
  "itens_relevantes": ["lista de itens/lotes que a IndFlow pode atender"],
  "exigencias_tecnicas": ["exigências técnicas importantes — certificações, normas, especificações"],
  "documentacao_necessaria": ["documentos exigidos para participação"],
  "prazos": {
    "abertura": "data de abertura da sessão",
    "proposta": "prazo para envio de proposta",
    "execucao": "prazo de execução/entrega"
  },
  "valor_estimado": "valor estimado se disponível",
  "garantias": "garantias exigidas se houver",
  "aderencia": "ALTA" | "MEDIA" | "BAIXA",
  "justificativa_aderencia": "Por que esta classificação de aderência",
  "recomendacao": "PARTICIPAR" | "ACOMPANHAR" | "DESCARTAR",
  "justificativa_recomendacao": "Por que esta recomendação",
  "alertas": ["pontos de atenção — prazos apertados, exigências difíceis, etc."]
}"""


async def triage_licitacao(objeto: str, palavras_chave: str = "") -> dict:
    """
    Pré-triagem rápida de uma licitação usando GPT-4o-mini.
    Classifica aderência apenas pelo objeto e palavras-chave.
    
    Args:
        objeto: Descrição do objeto da licitação
        palavras_chave: Palavras-chave encontradas no edital
    Returns: Dict com aderência, motivo e keywords
    """
    try:
        user_message = f"OBJETO: {objeto}"
        if palavras_chave:
            user_message += f"\nPALAVRAS-CHAVE: {palavras_chave}"

        response = await client.chat.completions.create(
            model=config.OPENAI_MODEL_TRIAGE,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_TRIAGE},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
            max_tokens=300,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)
        logger.info(f"[AI] Triagem: {result.get('aderencia', '?')} - {objeto[:80]}...")
        return result

    except Exception as e:
        logger.error(f"[ERR] Erro na triagem: {e}")
        # Fallback: classificação por keywords
        return _keyword_fallback_triage(objeto, palavras_chave)


async def analyze_edital(
    objeto: str,
    edital_text: str,
    orgao: str = "",
    cidade_uf: str = "",
) -> dict:
    """
    Análise profunda de um edital usando GPT-4o.
    Gera resumo executivo, classificação e recomendação.
    
    Args:
        objeto: Descrição do objeto
        edital_text: Texto completo extraído do PDF do edital
        orgao: Nome do órgão licitante
        cidade_uf: Cidade/UF
    Returns: Dict com análise completa
    """
    try:
        user_message = f"""OBJETO: {objeto}
ÓRGÃO: {orgao}
CIDADE/UF: {cidade_uf}

TEXTO DO EDITAL:
{edital_text}"""

        response = await client.chat.completions.create(
            model=config.OPENAI_MODEL_ANALYSIS,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_ANALYSIS},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)
        logger.info(f"[OK] Analise completa: {result.get('aderencia', '?')} - {objeto[:80]}...")
        return result

    except Exception as e:
        logger.error(f"❌ Erro na análise do edital: {e}")
        return {
            "resumo_executivo": "Erro ao analisar edital",
            "aderencia": "BAIXA",
            "recomendacao": "ACOMPANHAR",
            "error": str(e),
        }


async def batch_triage(licitacoes: list[dict]) -> list[dict]:
    """
    Executa triagem em lote para todas as licitações de um boletim.
    
    Args:
        licitacoes: Lista de dicts com pelo menos 'objeto'
    Returns: Lista de dicts com resultado de triagem adicionado
    """
    results = []
    for lic in licitacoes:
        triage = await triage_licitacao(
            objeto=lic.get("objeto", ""),
            palavras_chave=lic.get("palavras_chave", ""),
        )
        lic["triage"] = triage
        lic["aderencia"] = triage.get("aderencia", "BAIXA")
        results.append(lic)

    # Contagem por aderência
    counts = {"ALTA": 0, "MEDIA": 0, "BAIXA": 0}
    for r in results:
        counts[r.get("aderencia", "BAIXA")] += 1
    logger.info(f"[AI] Triagem em lote: ALTA={counts['ALTA']}, MEDIA={counts['MEDIA']}, BAIXA={counts['BAIXA']}")

    return results


def _keyword_fallback_triage(objeto: str, palavras_chave: str = "") -> dict:
    """
    Classificação de fallback por keywords quando a API falhar.
    """
    text = f"{objeto} {palavras_chave}".lower()

    matched_alta = [kw for kw in config.KEYWORDS_ALTA if kw.lower() in text]
    matched_media = [kw for kw in config.KEYWORDS_MEDIA if kw.lower() in text]

    if matched_alta:
        return {
            "aderencia": "ALTA",
            "motivo": f"Match direto com produtos IndFlow: {', '.join(matched_alta[:3])}",
            "keywords_match": matched_alta,
        }
    elif matched_media:
        return {
            "aderencia": "MEDIA",
            "motivo": f"Setor adjacente: {', '.join(matched_media[:3])}",
            "keywords_match": matched_media,
        }
    else:
        return {
            "aderencia": "BAIXA",
            "motivo": "Sem match com produtos ou setores da IndFlow",
            "keywords_match": [],
        }
