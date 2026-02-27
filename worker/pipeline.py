"""
Pipeline orquestrador do fluxo completo de triagem de licitaes.
Coordena: Scraping  Parse  Triagem  Download  Anlise  Banco  WhatsApp
"""

import asyncio
import logging
import os
import re
from datetime import datetime

from . import config
from .scraper import ConLicitacaoScraper, run_scraping_flow
from .pdf_parser import parse_xlsx, process_edital_download
from .analyzer import triage_licitacao, analyze_edital, batch_triage
from .database import save_batch, check_duplicate
from .whatsapp import send_report, send_whatsapp_document

logger = logging.getLogger(__name__)


def extract_boletim_number_from_subject(subject: str) -> int | None:
    """Extrai o nmero do boletim do assunto do e-mail."""
    match = re.search(r'\[(\d+)\]', subject)
    if match:
        return int(match.group(1))
    return None


async def process_boletim(
    boletim_number: int | None = None,
    boletim_url: str | None = None,
    email_subject: str = "",
    email_html: str = "",
    download_all_alta: bool = True,
    send_whatsapp: bool = True,
) -> dict:
    """
    Pipeline completo de processamento de um boletim.
    
    Fluxo:
    1. Extrair nmero do boletim do assunto (se no fornecido)
    2. Login e scraping no ConLicitao
    3. Exportar e parsear XLSX com dados estruturados
    4. Pr-triagem rpida (GPT-4o-mini) de todas as licitaes
    5. Download de editais das licitaes de Alta aderncia
    6. Anlise profunda (GPT-4o) dos editais baixados
    7. Salvar tudo no banco de dados
    8. Enviar relatrio via WhatsApp
    
    Args:
        boletim_number: Nmero do boletim
        boletim_url: URL direta do boletim (do e-mail)
        email_subject: Assunto do e-mail (para extrair nmero)
        email_html: HTML do e-mail (para extrair URL)
        download_all_alta: Se True, baixa editais de todas as Alta aderncia
        send_whatsapp: Se True, envia relatrio via WhatsApp
        
    Returns: Dict com resultado completo do pipeline
    """
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info("INICIANDO PIPELINE DE TRIAGEM DE LICITAES")
    logger.info("=" * 60)

    result = {
        "success": False,
        "boletim_number": boletim_number,
        "total_licitacoes": 0,
        "triagem": {"alta": 0, "media": 0, "baixa": 0},
        "editais_baixados": 0,
        "editais_analisados": 0,
        "salvas_no_banco": 0,
        "whatsapp_enviado": False,
        "errors": [],
        "licitacoes": [],
    }

    try:
        #  1. Extrair nmero do boletim 
        if not boletim_number and email_subject:
            boletim_number = extract_boletim_number_from_subject(email_subject)
            result["boletim_number"] = boletim_number
            logger.info(f"[EMAIL] Boletim #{boletim_number} extrado do e-mail")

        #  2. Scraping: Login + XLSX 
        logger.info("[SCRAPE] Etapa 2: Login e obtencao de dados...")
        
        async with ConLicitacaoScraper() as scraper:
            if not await scraper.login():
                result["errors"].append("Falha no login do ConLicitacao")
                logger.error("[ERR] Pipeline abortado: Falha no login")
                return result

            # Tenta exportar XLSX primeiro (mais completo)
            xlsx_path = await scraper.export_xlsx(boletim_number, boletim_url)
            licitacoes = []
            
            if xlsx_path:
                logger.info("[PARSE] Etapa 3: Dados obtidos via XLSX")
                licitacoes = parse_xlsx(xlsx_path)
            else:
                logger.info("[PARSE] Etapa 3: Dados via SCRAPING MANUAL (fallback)")
                licitacoes, detected_boletim = await scraper.scrape_bulletin_cards()
                if detected_boletim and not boletim_number:
                    boletim_number = detected_boletim
                    result["boletim_number"] = detected_boletim

            result["total_licitacoes"] = len(licitacoes)
            
            if not licitacoes:
                result["errors"].append("Nenhuma licitacao encontrada no boletim")
                return result

            # Adicionar numero do boletim a cada licitacao
            # Garantir que temos o número do boletim (auto-detectado ou fornecido)
            if not boletim_number and scraper.current_boletim_number:
                boletim_number = scraper.current_boletim_number
                result["boletim_number"] = boletim_number
                logger.info(f"[PIPELINE] Usando boletim #{boletim_number} detectado pelo scraper")

            for lic in licitacoes:
                lic["numero_boletim"] = boletim_number

            #  4. Pre-triagem rpida (GPT-4o-mini) 
            logger.info(f"[AI] Etapa 4: Triagem de {len(licitacoes)} licitacoes...")
            licitacoes = await batch_triage(licitacoes)

            # Contagem
            for lic in licitacoes:
                aderencia = lic.get("aderencia", "BAIXA")
                result["triagem"][aderencia.lower()] += 1

            logger.info(
                f" Triagem: [ALTA] {result['triagem']['alta']} | "
                f"[MEDIA] {result['triagem']['media']} | "
                f"[BAIXA] {result['triagem']['baixa']}"
            )

            #  5. Download de editais (Alta aderncia) 
            alta_licitacoes = [l for l in licitacoes if l.get("aderencia") == "ALTA"]

            if download_all_alta and alta_licitacoes:
                logger.info(f"[DOWNLOAD] Etapa 5: Baixando {len(alta_licitacoes)} editais de Alta aderncia na mesma sessao...")
                
                # Precisamos dos IDs reais para download (numero_conlicitacao)
                alta_ids = [l.get("numero_conlicitacao") for l in alta_licitacoes if l.get("numero_conlicitacao")]
                
                if alta_ids:
                    # Remover duplicatas
                    alta_ids = list(dict.fromkeys(alta_ids))
                    
                    # Ao baixar ALTA, marcar como favorito no portal
                    downloads = await scraper.download_editais_batch(alta_ids, favorite=True)
                    result["editais_baixados"] = sum(1 for d in downloads if d["success"])

                    #  6. Anlise profunda dos editais 
                    logger.info("[AI] Etapa 6: Analise profunda dos editais baixados...")
                    # Note: O zip assume que a ordem dos downloads corresponde aos alta_ids, 
                    # entao precisamos garantir que o download_editais_batch mantenha a ordem ou retorne um mapa.
                    # No scraper atual, ele retorna uma lista na mesma ordem dos IDs.
                    
                    # Vamos mapear os resultados de volta para as licitacoes de alta
                    download_map = {d["id"]: d for d in downloads}
                    
                    for lic in alta_licitacoes:
                        num_con = lic.get("numero_conlicitacao")
                        download = download_map.get(num_con)
                        
                        if download and download["success"] and download["filepath"]:
                            # Guardar o caminho do arquivo original para posterior envio
                            lic["edital_pdf_path"] = download["filepath"]
                            lic["edital_disponivel"] = True
                            
                            #  6. Anlise profunda do edital 
                            edital_data = process_edital_download(download["filepath"])
                            
                            if edital_data["success"] and edital_data["combined_text"]:
                                analysis = await analyze_edital(
                                    objeto=lic.get("objeto", ""),
                                    edital_text=edital_data["combined_text"],
                                    orgao=lic.get("orgao", ""),
                                    cidade_uf=lic.get("cidade", ""),
                                )
                                # Atualizar dados da licitacao com a analise profunda
                                lic["analise_completa"] = analysis
                                lic["resumo_ia"] = analysis.get("resumo_executivo", "")
                                lic["recomendacao"] = analysis.get("recomendacao", "ACOMPANHAR")
                                lic["aderencia"] = analysis.get("aderencia", lic["aderencia"]) # Atualizar se for diferente
                                result["editais_analisados"] += 1
                        else:
                            # Edital não disponível para download — anotar e continuar
                            lic["edital_disponivel"] = False
                            logger.info(f"[INFO] Edital nao disponivel para download: {num_con} — continuando analise sem ele.")
            else:
                logger.info("[SKIP] Etapa 5-6: Nenhum edital para download/anlise profunda")

        #  7. Verificar duplicatas e salvar no banco 
        logger.info("[DATABASE] Etapa 7: Salvando no banco de dados...")
        licitacoes_novas = []
        for lic in licitacoes:
            is_dup = await check_duplicate(
                lic.get("edital", ""),
                lic.get("numero_conlicitacao", ""),
            )
            if not is_dup:
                licitacoes_novas.append(lic)

        if licitacoes_novas:
            result["salvas_no_banco"] = await save_batch(licitacoes_novas)
        logger.info(f"[DATABASE] {result['salvas_no_banco']} novas licitaes salvas")

        #  8. Enviar relatrio WhatsApp 
        if send_whatsapp:
            logger.info("[WHATSAPP] Etapa 8: Enviando relatrio via WhatsApp...")
            # Enviar apenas Alta e Mdia
            licitacoes_report = [l for l in licitacoes if l.get("aderencia") != "BAIXA"]
            if licitacoes_report:
                result["whatsapp_enviado"] = send_report(
                    licitacoes_report,
                    boletim_number,
                    total_no_boletim=result["total_licitacoes"],
                )
            else:
                logger.info("[INFO] Nenhuma licitao relevante para reportar")

            # 8b. Enviar PDFs dos editais de Alta aderência
            pdfs_enviados = 0
            for lic in licitacoes:
                raw_path = lic.get("edital_pdf_path")
                if not raw_path or lic.get("aderencia") != "ALTA":
                    continue

                edital_label = lic.get('edital') or lic.get('numero_conlicitacao', 'S/N')
                orgao_label  = lic.get('orgao', '')

                # Localizar o PDF a enviar:
                # 1. Se for PDF direto → usar diretamente
                # 2. Se for ZIP → a pasta extraída tem o mesmo nome sem .zip
                #    Varrer essa pasta em busca do maior PDF
                pdf_to_send = None

                if raw_path.lower().endswith(".pdf") and os.path.isfile(raw_path):
                    pdf_to_send = raw_path
                else:
                    # Pasta extraída: zip_path sem extensão
                    extract_dir = os.path.splitext(raw_path)[0]
                    candidates = []

                    if os.path.isdir(extract_dir):
                        for root, _, files in os.walk(extract_dir):
                            for f in files:
                                if f.lower().endswith(".pdf"):
                                    candidates.append(os.path.join(root, f))

                    if not candidates and os.path.isfile(raw_path):
                        # ZIP ainda não foi extraído — processar agora
                        edital_data = process_edital_download(raw_path)
                        candidates = edital_data.get("pdf_files", [])

                    if candidates:
                        # Enviar o maior PDF (geralmente o edital principal)
                        pdf_to_send = max(candidates, key=lambda p: os.path.getsize(p) if os.path.isfile(p) else 0)

                if not pdf_to_send or not os.path.isfile(pdf_to_send):
                    logger.warning(f"[WHATSAPP] Nenhum PDF encontrado para {edital_label}, pulando envio.")
                    continue

                caption = f"📎 Edital {edital_label} — {orgao_label}".strip(" —")
                ok = send_whatsapp_document(pdf_to_send, caption=caption)
                if ok:
                    pdfs_enviados += 1
                    logger.info(f"[WHATSAPP] PDF enviado: {edital_label}")
                else:
                    logger.warning(f"[WHATSAPP] Falha ao enviar PDF: {edital_label}")

            if pdfs_enviados:
                logger.info(f"[WHATSAPP] {pdfs_enviados} PDF(s) de Alta aderência enviados via WhatsApp")

        result["success"] = True
        result["licitacoes"] = licitacoes

    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"[ERR] Erro no pipeline: {e}", exc_info=True)

    #  Resumo final 
    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("=" * 60)
    logger.info(f"[OK] PIPELINE CONCLUDO em {elapsed:.1f}s")
    logger.info(f"   [INFO] Total: {result['total_licitacoes']} licitaes")
    logger.info(f"   [ALTA]: {result['triagem']['alta']}")
    logger.info(f"   [MEDIA]: {result['triagem']['media']}")
    logger.info(f"   [BAIXA]: {result['triagem']['baixa']}")
    logger.info(f"   [DOWNLOAD] Editais baixados: {result['editais_baixados']}")
    logger.info(f"   [AI] Editais analisados: {result['editais_analisados']}")
    logger.info(f"   [DATABASE] Salvos no banco: {result['salvas_no_banco']}")
    logger.info(f"   [WHATSAPP]: {'Enviado [OK]' if result['whatsapp_enviado'] else 'No enviado'}")
    logger.info("=" * 60)

    return result
