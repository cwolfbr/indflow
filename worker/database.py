"""
Mdulo de integrao com Supabase.
Salva e consulta licitaes processadas.
"""

import logging
from datetime import datetime, timezone

from supabase import create_client, Client

from . import config

logger = logging.getLogger(__name__)

_client: Client | None = None


def get_client() -> Client:
    """Retorna o client Supabase (singleton)."""
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client


async def save_licitacao(data: dict) -> dict | None:
    """
    Salva uma licitao processada no Supabase.
    
    Args:
        data: Dict com os dados da licitao
    Returns: Registro salvo ou None
    """
    try:
        client = get_client()
        record = {
            "numero_edital": data.get("edital", ""),
            "objeto": data.get("objeto", ""),
            "orgao": data.get("orgao", ""),
            "cidade_uf": data.get("cidade", "") + ("/" + data.get("uf", "") if data.get("uf") else ""),
            "data_abertura": data.get("data_abertura"),
            "valor_estimado": data.get("valor"),
            "status_licitacao": data.get("status", ""),
            "palavras_chave": data.get("palavras_chave", ""),
            "modalidade": data.get("modalidade", ""),
            "numero_conlicitacao": data.get("numero_conlicitacao", ""),
            "numero_boletim": data.get("numero_boletim"),
            "aderencia": data.get("aderencia", "BAIXA"),
            "recomendacao": data.get("recomendacao", ""),
            "resumo_ia": data.get("resumo_ia", ""),
            "analise_completa": data.get("analise_completa"),
            "arquivo_edital_url": data.get("arquivo_edital_url"),
            "processado_em": datetime.now(timezone.utc).isoformat(),
        }

        # Remove campos None
        record = {k: v for k, v in record.items() if v is not None and v != ""}

        result = client.table("licitacoes").insert(record).execute()
        logger.info(f"[OK] Licitao salva: {data.get('edital', '?')}")
        return result.data[0] if result.data else None

    except Exception as e:
        logger.error(f" Erro ao salvar licitao: {e}")
        return None


async def save_batch(licitacoes: list[dict]) -> int:
    """
    Salva licitaes em lote.
    
    Returns: Nmero de registros salvos com sucesso
    """
    saved = 0
    for lic in licitacoes:
        result = await save_licitacao(lic)
        if result:
            saved += 1
    logger.info(f" Lote salvo: {saved}/{len(licitacoes)} registros")
    return saved


async def check_duplicate(numero_edital: str, numero_conlicitacao: str = "") -> bool:
    """
    Verifica se uma licitao j foi processada.
    """
    try:
        client = get_client()
        query = client.table("licitacoes").select("id")

        if numero_conlicitacao:
            query = query.eq("numero_conlicitacao", numero_conlicitacao)
        elif numero_edital:
            query = query.eq("numero_edital", numero_edital)
        else:
            return False

        result = query.limit(1).execute()
        return len(result.data) > 0

    except Exception as e:
        logger.error(f"Erro ao verificar duplicata: {e}")
        return False


async def get_stats(days: int = 30) -> dict:
    """
    Retorna estatsticas das licitaes processadas.
    """
    try:
        client = get_client()
        result = client.table("licitacoes").select("aderencia, recomendacao").execute()
        
        stats = {
            "total": len(result.data),
            "alta": sum(1 for r in result.data if r.get("aderencia") == "ALTA"),
            "media": sum(1 for r in result.data if r.get("aderencia") == "MEDIA"),
            "baixa": sum(1 for r in result.data if r.get("aderencia") == "BAIXA"),
            "participar": sum(1 for r in result.data if r.get("recomendacao") == "PARTICIPAR"),
            "acompanhar": sum(1 for r in result.data if r.get("recomendacao") == "ACOMPANHAR"),
            "descartar": sum(1 for r in result.data if r.get("recomendacao") == "DESCARTAR"),
        }
        return stats

    except Exception as e:
        logger.error(f"Erro ao obter estatsticas: {e}")
        return {}
