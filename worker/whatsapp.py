"""
Módulo de envio de relatórios via WhatsApp (Evolution API).
Formata e envia relatório priorizado de licitações.
"""

import logging
from datetime import datetime

import base64
import os
import requests

from . import config

logger = logging.getLogger(__name__)


def format_report(
    licitacoes: list[dict],
    boletim_number: int | None = None,
    total_no_boletim: int | None = None,
) -> str:
    """
    Formata o relatório de licitações para WhatsApp.

    Args:
        licitacoes: Apenas licitaes  Alta/Média (BAIXA já filtrada pelo pipeline)
        boletim_number: Número do boletím
        total_no_boletim: Total de licitações no boletím (incluindo BAIXA)
    Returns: Mensagem formatada para WhatsApp
    """
    today = datetime.now().strftime("%d/%m/%Y")
    boletim_str = f" — Boletim {boletim_number}" if boletim_number else ""
    header = f"📋 *Relatório IndFlow{boletim_str}*\n📅 {today}"

    # Separar por aderência
    alta  = [l for l in licitacoes if l.get("aderencia") == "ALTA"]
    media = [l for l in licitacoes if l.get("aderencia") == "MEDIA"]
    baixa_count = (total_no_boletim or 0) - len(licitacoes) if total_no_boletim else 0

    # Estatísticas de documentos (apenas para ALTA)
    alta = [l for l in licitacoes if l.get("aderencia") == "ALTA"]
    com_doc    = sum(1 for l in alta if l.get("edital_disponivel") is True)
    sem_doc    = sum(1 for l in alta if l.get("edital_disponivel") is False)
    sem_info   = len(alta) - com_doc - sem_doc  # IA triage-only, sem tentativa de download

    sections = []

    # Bloco de resumo
    total_str = f"/{total_no_boletim}" if total_no_boletim else ""
    doc_line = ""
    if com_doc or sem_doc:
        doc_line = f"\n📄 Documentos: {com_doc} baixados | {sem_doc} indisponíveis no portal"
    sections.append(
        f"\n\n📊 *{len(licitacoes)}{total_str} licitaes relevantes* (de {total_no_boletim or len(licitacoes)} no boletím)"
        f"\n🟢 Alta: {len(alta)} | 🟡 Média: {len(media)} | 🔴 Baixa: {baixa_count} (filtradas)"
        + doc_line
    )

    # Alta aderência (detalhado)
    if alta:
        sections.append("\n\n🟢 *ALTA ADERÊNCIA*")
        for i, lic in enumerate(alta, 1):
            sections.append(_format_licitacao_detail(i, lic))

    # Média aderência (resumido)
    if media:
        sections.append("\n\n🟡 *MÉDIA ADERÊNCIA*")
        for i, lic in enumerate(media, 1):
            sections.append(_format_licitacao_brief(i, lic))

    return header + "\n".join(sections)


def _format_licitacao_detail(index: int, lic: dict) -> str:
    """Formata uma licitação com detalhes (para Alta aderência)."""
    num_con = lic.get('numero_conlicitacao', 'S/N')
    edital_name = lic.get('edital')
    
    # Título: Edital ou Fallback para Nº Conlicitação
    title = edital_name if edital_name else f"Nº Conlicitação: {num_con}"
    lines = [f"\n\n*{index}. {title}*"]

    # Se tivermos edital, colocar o Nº Conlicitação logo abaixo
    if edital_name:
        lines.append(f"🆔 *Nº Conlicitação:* {num_con}")

    # Link direto para a licitação no portal
    if num_con != 'S/N':
        link = f"https://consulteonline.conlicitacao.com.br/detalhes_licitacao?id={num_con}"
        lines.append(f"🔗 {link}")

    if lic.get("orgao"):
        lines.append(f"📍 {lic['orgao']}")
    if lic.get("cidade"):
        cidade_uf = lic["cidade"]
        if lic.get("uf"):
            cidade_uf += f"/{lic['uf']}"
        lines.append(f"📌 {cidade_uf}")

    lines.append(f"📦 {lic.get('objeto', 'Sem descrição')[:150]}")

    if lic.get("data_abertura"):
        lines.append(f"📅 Abertura: {lic['data_abertura']}")
    if lic.get("valor"):
        lines.append(f"💰 {lic['valor']}")

    # Resumo IA (se disponível)
    resumo = lic.get("resumo_ia", "")
    if resumo:
        lines.append(f"📝 _{resumo[:200]}_")

    # Nota: edital sem download disponível no portal
    if lic.get("edital_disponivel") is False:
        lines.append("⚠️ _Edital não disponível para download no portal — análise baseada apenas na descrição do card._")

    # Recomendação
    rec = lic.get("recomendacao", "ACOMPANHAR")
    emoji = {"PARTICIPAR": "✅", "ACOMPANHAR": "👀", "DESCARTAR": "❌"}.get(rec, "❓")
    lines.append(f"{emoji} *Recomendação: {rec}*")

    return "\n".join(lines)



def _format_licitacao_brief(index: int, lic: dict) -> str:
    """Formata uma licitação resumida (para Média aderência)."""
    num_con = lic.get("numero_conlicitacao", "S/N")
    objeto = lic.get("objeto") or "Sem descrição"
    return f"\n{index}. Nº Conlicitação: {num_con}\n   📦 {objeto}"


def send_whatsapp_message(message: str, recipient: str | None = None) -> bool:
    """
    Envia mensagem via Evolution API.
    
    Args:
        message: Texto da mensagem
        recipient: Número do destinatário (padrão: config)
    Returns: True se enviado com sucesso
    """
    recipient = recipient or config.WHATSAPP_RECIPIENT
    if not recipient:
        logger.error("❌ Nenhum destinatário configurado para WhatsApp")
        return False

    try:
        url = f"{config.EVOLUTION_API_URL}/message/sendText/{config.EVOLUTION_INSTANCE}"
        headers = {
            "Content-Type": "application/json",
            "apikey": config.EVOLUTION_API_KEY,
        }
        payload = {
            "number": recipient,
            "text": message,
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        logger.info(f"[OK] Mensagem WhatsApp enviada para {recipient}")
        return True

    except Exception as e:
        logger.error(f"[ERR] Erro ao enviar WhatsApp: {e}")
        return False


def send_whatsapp_document(file_path: str, caption: str = "", recipient: str | None = None) -> bool:
    """
    Envia um documento (PDF) via Evolution API.
    
    Args:
        file_path: Caminho local do arquivo
        caption: Legenda da mensagem
        recipient: Número do destinatário
    Returns: True se enviado com sucesso
    """
    if not os.path.exists(file_path):
        logger.error(f"[ERR] Arquivo não encontrado: {file_path}")
        return False

    recipient = recipient or config.WHATSAPP_RECIPIENT
    if not recipient:
        logger.error("❌ Nenhum destinatário configurado para WhatsApp")
        return False

    try:
        # Codificar arquivo em base64
        with open(file_path, "rb") as f:
            file_base64 = base64.b64encode(f.read()).decode("utf-8")

        url = f"{config.EVOLUTION_API_URL}/message/sendMedia/{config.EVOLUTION_INSTANCE}"
        headers = {
            "Content-Type": "application/json",
            "apikey": config.EVOLUTION_API_KEY,
        }
        
        filename = os.path.basename(file_path)
        payload = {
            "number": recipient,
            "media": file_base64,
            "mediatype": "document",
            "mimetype": "application/pdf",
            "mediaType": "document",
            "fileName": filename,
            "caption": caption or f"Documento: {filename}",
        }

        response = requests.post(url, json=payload, headers=headers, timeout=60)
        if response.status_code != 200:
            logger.error(f"[ERR] Falha ao enviar documento. Status: {response.status_code}, Resposta: {response.text}")
        response.raise_for_status()

        logger.info(f"[OK] Documento {filename} enviado para {recipient}")
        return True

    except Exception as e:
        logger.error(f"[ERR] Erro ao enviar documento WhatsApp: {e}")
        return False


def send_report(
    licitacoes: list[dict],
    boletim_number: int | None = None,
    total_no_boletim: int | None = None,
) -> bool:
    """
    Formata e envia relatório completo via WhatsApp.
    Se a mensagem for muito longa, divide em partes.
    """
    message = format_report(licitacoes, boletim_number, total_no_boletim=total_no_boletim)

    # WhatsApp tem limite de ~65k chars, mas msgs longas ficam ruins
    # Dividir se muito longo
    MAX_LENGTH = 4000
    if len(message) <= MAX_LENGTH:
        return send_whatsapp_message(message)

    # Dividir em partes
    parts = []
    current = ""
    for line in message.split("\n"):
        if len(current) + len(line) + 1 > MAX_LENGTH:
            parts.append(current)
            current = line
        else:
            current += "\n" + line if current else line
    if current:
        parts.append(current)

    success = True
    for i, part in enumerate(parts):
        if i > 0:
            part = f"📋 *Continuação ({i+1}/{len(parts)})*\n\n{part}"
        if not send_whatsapp_message(part):
            success = False

    return success
