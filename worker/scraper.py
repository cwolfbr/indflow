"""
Mdulo de scraping do ConLicitao.
Realiza login, navegao ao boletim, exportao XLSX e download de editais via Playwright.
"""

import asyncio
import logging
import os
import random
import re
from datetime import datetime

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from . import config

logger = logging.getLogger(__name__)


class ConLicitacaoScraper:
    """Scraper para a plataforma ConLicitao usando Playwright."""

    def __init__(self):
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self._playwright = None
        self.current_boletim_number = None  # Capturado durante navegação

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def start(self):
        """Inicia o browser e contexto Playwright."""
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            accept_downloads=True,
        )
        self.page = await self.context.new_page()
        
        # Garantir que o diretório de downloads existe para prints de debug
        os.makedirs(config.DOWNLOADS_DIR, exist_ok=True)
        
        logger.info("Browser iniciado com sucesso")

    async def close(self):
        """Fecha o browser e libera recursos."""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser fechado")

    async def _delay(self):
        """Delay humanizado entre aes."""
        delay = random.uniform(config.SCRAPING_DELAY_MIN, config.SCRAPING_DELAY_MAX)
        await asyncio.sleep(delay)

    async def login(self) -> bool:
        """
        Realiza login na plataforma ConLicitao (React SPA).
        URL: consulteonline.conlicitacao.com.br
        Returns: True se login foi bem-sucedido.
        """
        try:
            logger.info("Iniciando login no ConLicitao...")

            # Usar 'domcontentloaded' em vez de 'networkidle' para evitar timeouts por scripts de tracking
            await self.page.goto(
                config.CONLICITACAO_URL,
                wait_until="domcontentloaded",
                timeout=45000,
            )
            
            # Esperar um pouco para o React assentar
            await asyncio.sleep(5)
            await self._delay()

            # Tirar print inicial do formulário vazio
            await self.page.screenshot(path=os.path.join(config.DOWNLOADS_DIR, "login_1_start.png"))

            logger.info(f"Preenchendo credenciais para: {config.CONLICITACAO_EMAIL}")
            
            # Seletores corrigidos com base em inspeção: login e senha
            # Email (name="login" ou id="login")
            email_field = self.page.locator('input[name="login"], input#login, input[type="email"]').first
            await email_field.fill(config.CONLICITACAO_EMAIL)
            
            # Senha (name="senha" ou id="senha")
            pass_field = self.page.locator('input[name="senha"], input#senha, input[type="password"]').first
            await pass_field.fill(config.CONLICITACAO_PASSWORD)
            
            await self.page.screenshot(path=os.path.join(config.DOWNLOADS_DIR, "login_2_filled.png"))
            
            # Botão Acessar (React button ou submit padrão)
            logger.info("Clicando em Acessar...")
            btn = self.page.locator('button:has-text("Acessar"), input[type="submit"], .btn-primary').first
            await btn.click()
            
            # Aguardar transição (SPA)
            await asyncio.sleep(5)
            await self.page.screenshot(path=os.path.join(config.DOWNLOADS_DIR, "login_3_after_click.png"))

            # Aguardar Dashboard ou erro
            try:
                # Seletor do Dashboard ou elemento pós-login
                await self.page.wait_for_selector('text="Dashboard", text="Sair", .MuiAvatar-root, text="Visualizar"', timeout=25000)
            except:
                logger.warning("Aguardando Dashboard demorou mais que o esperado. Verificando estado final...")
                await self.page.screenshot(path=os.path.join(config.DOWNLOADS_DIR, "login_4_wait_timeout.png"))

            if await self._is_logged_in():
                logger.info("[OK] Login realizado com sucesso!")
                return True
            
            # Verificar se há mensagem de erro explícita na tela
            error_box = self.page.locator('.alert-danger, .MuiAlert-message, text="inválido", text="Incorreto"').first
            if await error_box.is_visible(timeout=2000):
                txt = await error_box.inner_text()
                logger.error(f"❌ Erro de login no portal: {txt}")
            
            return False

        except Exception as e:
            logger.error(f"❌ Erro catastrófico durante login: {e}")
            try:
                await self.page.screenshot(path=os.path.join(config.DOWNLOADS_DIR, "login_exception.png"))
            except: pass
            return False

    async def _is_logged_in(self) -> bool:
        """Verifica se o usurio est logado checando elementos da pgina."""
        try:
            # Indicadores reais do dashboard ConLicitao ps-login
            indicators = [
                'text="Dashboard"',
                'text="Ferramentas"',
                'text="Boletins de Licitaes"',
                'text="Boas-vindas"',
                'text="Encontrar Licitaes"',
                'a:has-text("Dashboard")',
                'a:has-text("Ferramentas")',
            ]
            for selector in indicators:
                try:
                    element = self.page.locator(selector).first
                    if await element.is_visible(timeout=2000):
                        return True
                except Exception:
                    continue
        except Exception:
            pass

        # Fallback: verificar se a URL mudou para algo ps-login
        current_url = self.page.url
        return "wp-login" not in current_url.lower() and "login" not in current_url.lower()

    async def _close_welcome_modal(self):
        """
        Fecha o modal de boas-vindas e outros overlays se estiverem visveis.
        """
        try:
            # Tentar fechar vrias vezes se necessrio
            for _ in range(2):
                close_selectors = [
                    'text="Usar a plataforma"',
                    'button:has-text("Usar a plataforma")',
                    'span:has-text("Usar a plataforma")',
                    'button.close',
                    '.MuiDialog-root [class*="close"]',
                    '.modal-header .close',
                    'button[aria-label="close"]',
                    '[class*="CloseButton"]',
                    'button:has-text("Fechar")',
                    'span:has-text("Fechar")',
                    '.modal-content .close',
                    'button:has-text("Entendi")',
                    'div[role="presentation"] button:has-text("Fechar")',
                    'button svg[data-testid="CloseIcon"]', # Comum em MUI
                ]
                
                modal_found = False
                for sel in close_selectors:
                    try:
                        el = self.page.locator(sel).first
                        if await el.is_visible(timeout=1000):
                            await el.click(force=True)
                            logger.info(f"Modal fechado via selector: {sel}")
                            modal_found = True
                            await asyncio.sleep(1)
                            # Se fechou um, pode haver outro, mas vamos tentar o prximo na prxima iterao do loop externo
                    except: continue
                
                # ESC como fallback universal
                await self.page.keyboard.press("Escape")
                await asyncio.sleep(1)
                
                # Se ainda houver modais (dialogs) abertos, tentar clicar no X genrico ou fora
                dialogs = self.page.locator('[role="dialog"], [aria-modal="true"], .modal.show, .MuiDialog-root')
                if await dialogs.count() > 0:
                    logger.info("Tentando fechar dialog residual...")
                    # Tenta clicar no boto X se houver na div presentation
                    generic_x = self.page.locator('button:has-text(""), button:has-text("x"), [aria-label*="fechar"], [class*="close"]').first
                    if await generic_x.is_visible(timeout=1000):
                        await generic_x.click(force=True)
                    else:
                        # Clica no canto superior direito para tentar fechar se for um overlay sem boto detectado
                        await self.page.mouse.click(10, 10) # Clica no topo
                    await asyncio.sleep(1)
                else:
                    break

        except Exception as e:
            logger.debug(f"Aviso ao fechar modal: {e}")

    async def navigate_to_boletim(self, boletim_number: int | None = None) -> bool:
        """
        Navega até um boletim específico no calendário FullCalendar.
        """
        try:
            logger.info(f"Navegando ao boletim {boletim_number or 'mais recente'}...")

            # 1. Fechar modals iniciais
            await self._close_welcome_modal()

            # 2. Ir diretamente para a página de boletins (Calendário)
            # Nota: O subagent confirmou que o URL correto do calendário é .../boletins
            calendar_url = f"{config.CONLICITACAO_URL}/boletim_web/public/boletins"
            logger.info(f"Acessando calendário de boletins: {calendar_url}")
            
            await self.page.goto(calendar_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(5)
            
            # Aguardar o calendário FullCalendar carregar
            try:
                await self.page.wait_for_selector('.fc-view-harness, .fc-daygrid-event', timeout=20000)
            except:
                logger.warning("Calendário demorou a carregar. Verificando se há links...")

            # 3. Localizar links de boletins (FullCalendar links)
            # Seletor preciso: a.fc-daygrid-event a
            loc = self.page.locator('a.fc-daygrid-event a, a.text-white.text-center')
            count = await loc.count()
            
            if count == 0:
                # Fallback se o calendário mudou de classe
                loc = self.page.locator('a:has-text("Boletim")')
                count = await loc.count()

            if count == 0:
                debug_path = os.path.join(config.DOWNLOADS_DIR, "debug_no_bulletins.png")
                await self.page.screenshot(path=debug_path)
                logger.error(f"Nenhum boletim encontrado no calendário. Screenshot: {debug_path}")
                return False

            texts = await loc.all_inner_texts()
            # Limpar espaços e filtrar apenas os que contém 'Boletim'
            links_data = []
            for i in range(count):
                txt = " ".join(texts[i].split())
                if "Boletim" in txt:
                    links_data.append({"index": i, "text": txt})

            if not links_data:
                logger.error("Elementos encontrados mas nenhum contém o texto 'Boletim'")
                return False

            logger.info(f"Boletins detectados: {[l['text'] for l in links_data[:5]]}...")

            # 4. Escolher o boletim
            target_idx = -1
            if boletim_number:
                target_str = f"Boletim {boletim_number}"
                for item in links_data:
                    if target_str.lower() in item["text"].lower():
                        target_idx = item["index"]
                        break
            
            if target_idx == -1:
                # Pegar o de maior número (mais recente)
                max_val = -1
                for item in links_data:
                    match = re.search(r'Boletim\s+(\d+)', item["text"])
                    if match:
                        num = int(match.group(1))
                        if num > max_val:
                            max_val = num
                            target_idx = item["index"]
                
                if target_idx == -1:
                    target_idx = links_data[0]["index"] # Fallback para o primeiro da lista

            # 5. Clicar e aguardar
            target_el = loc.nth(target_idx)
            logger.info(f"Clicando no boletim: '{texts[target_idx]}'")
            
            # Garantir que o número do boletim atual está salvo
            match = re.search(r'Boletim\s+(\d+)', texts[target_idx])
            if match:
                self.current_boletim_number = int(match.group(1))

            await target_el.click()
            await asyncio.sleep(5)
            await self.page.wait_for_load_state("networkidle", timeout=30000)
            
            # Verificar se mudou para a página do boletim
            if "visualizar" in self.page.url.lower() or await self.page.locator('text="Gerar .xlsx"').count() > 0:
                logger.info(f"[OK] Chegou à página do boletim {self.current_boletim_number}")
                return True
            
            logger.warning("Navegação concluída mas não detectou a página do boletim. Prosseguindo assim mesmo...")
            return True

        except Exception as e:
            logger.error(f"Erro ao navegar ao boletim: {e}", exc_info=True)
            return False

    async def export_xlsx(self) -> str | None:
        """
        Exporta o XLSX do boletim atual.
        """
        try:
            logger.info("Iniciando exportação XLSX...")
            
            # 1. Aguardar botão aparecer
            xlsx_btn_selector = 'button:has-text("Gerar .xlsx"), a:has-text("Gerar .xlsx"), .btn:has-text("Gerar .xlsx")'
            try:
                btn = self.page.locator(xlsx_btn_selector).first
                await self.page.wait_for_selector(xlsx_btn_selector, timeout=20000)
            except:
                logger.warning("Botão XLSX não visível. Tentando rolar e fechar modais...")
                await self._close_welcome_modal()
                await self.page.mouse.wheel(0, 2000)
                await asyncio.sleep(2)
                btn = self.page.locator(xlsx_btn_selector).first

            # 2. Selecionar todos os itens se necessário (SPA rule)
            try:
                # Alguns portais exigem marcar um checkbox de "Selecionar todos" antes de exportar
                select_all = self.page.locator('input[type="checkbox"], .select-all').first
                if await select_all.is_visible(timeout=2000):
                    await select_all.click()
                    await asyncio.sleep(1)
            except: pass

            # 3. Clicar e baixar
            logger.info("Clicando no botão 'Gerar .xlsx'...")
            
            async with self.page.expect_download(timeout=90000) as download_info:
                await btn.click(force=True)
                
            download = await download_info.value
            filename = f"boletim_{self.current_boletim_number or 'export'}.xlsx"
            filepath = os.path.join(config.XLSX_DIR, filename)
            await download.save_as(filepath)
            
            logger.info(f"[OK] XLSX salvo em: {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"Falha na exportação XLSX: {e}")
            return None

    async def download_edital(self, numero_conlicitacao: str, favorite: bool = False) -> str | None:
        """
        Faz download do edital de uma licitação específica dentro da página do boletim.
        Estratégia robusta com múltiplos selectors de expansão e fallback via JS.
        
        Args:
            numero_conlicitacao: ID da licitação no ConLicitação (ex: 18621681).
        Returns: Caminho do arquivo baixado, ou None se falhar.
        """
        try:
            logger.info(f"Baixando edital da licitação {numero_conlicitacao}...")

            # 1. Localizar o ID na página (com suporte a paginação)
            found = False
            for page_idx in range(8):  # Limite de 8 páginas
                id_text_locator = self.page.get_by_text(numero_conlicitacao, exact=True).first
                if await id_text_locator.is_visible(timeout=3000):
                    found = True
                    break

                # Tentar próxima página via vários selectors de paginação
                next_selectors = [
                    'ul.pagination li:not(.disabled) a[aria-label*="xt"]',   # Next
                    'ul.pagination li:not(.disabled) a:has-text(">")',
                    'ul.pagination li:not(.disabled) a:has-text("»")',
                    'ul.pagination li:not(.disabled) a:has-text("Próxima")',
                    'ul.pagination li:not(.disabled) a:has-text("Proxima")',
                    'button[aria-label*="next" i]:not([disabled])',
                    'button[aria-label*="próxima" i]:not([disabled])',
                ]
                clicked_next = False
                for sel in next_selectors:
                    next_btn = self.page.locator(sel).first
                    try:
                        if await next_btn.is_visible(timeout=1000):
                            logger.info(f"ID {numero_conlicitacao} não na pág {page_idx+1}, avançando...")
                            await next_btn.click()
                            await asyncio.sleep(3)
                            await self.page.wait_for_load_state("networkidle", timeout=10000)
                            clicked_next = True
                            break
                    except Exception:
                        continue
                if not clicked_next:
                    break

            if not found:
                logger.warning(f"ID {numero_conlicitacao} não encontrado em nenhuma página.")
                return None

            id_text_locator = self.page.get_by_text(numero_conlicitacao, exact=True).first

            # 2. Isolar o card container
            card = id_text_locator.locator(
                "xpath=./ancestor::div[contains(@class,'MuiPaper-root') "
                "or contains(@class,'card') "
                "or contains(@class,'bidding') "
                "or contains(@class,'licitacao')][1]"
            )

            if not await card.is_visible(timeout=3000):
                logger.warning(f"Card container não isolado para {numero_conlicitacao}")
                return None

            await card.scroll_into_view_if_needed()
            await self._close_welcome_modal()

            # 3. Favoritar se solicitado
            if favorite:
                await self.mark_as_favorite_in_card(card, numero_conlicitacao)

            # 4. Verificar disponibilidade
            if await card.locator('text="Nenhum edital disponível"').is_visible(timeout=1000):
                logger.warning(f"Licitação {numero_conlicitacao} sem edital.")
                return None

            download_btn_selector = (
                'button:has-text("Baixar Edital"), a:has-text("Baixar Edital"), '
                'button:has-text("Baixar edital"), a:has-text("Baixar edital"), '
                '[class*="download"]:has-text("Edital"), '
                'a[href*="edital" i], a[href*="download" i]'
            )
            btn = card.locator(download_btn_selector).first

            # 4. Expandir — múltiplas estratégias
            if not await btn.is_visible(timeout=2000):
                logger.info(f"Expandindo card {numero_conlicitacao}...")

                expand_selectors = [
                    'text="Ver mais informações da licitação"',
                    'text="Ver mais informacoes da licitacao"',
                    'a:has-text("Ver mais")',
                    'button:has-text("Ver mais")',
                    'span:has-text("Ver mais")',
                    '[class*="expand"]',
                    '[class*="details"]',
                    '[class*="toggle"]',
                    'a:has-text("Detalhes")',
                    'button:has-text("Detalhes")',
                ]

                expanded = False
                for exp_sel in expand_selectors:
                    try:
                        exp_el = card.locator(exp_sel).first
                        if await exp_el.is_visible(timeout=800):
                            await exp_el.click(force=True)
                            logger.info(f"  Expansão via: {exp_sel}")
                            expanded = True
                            break
                    except Exception:
                        continue

                if not expanded:
                    # Fallback 1: clicar no título/objeto do card
                    box = await card.bounding_box()
                    if box:
                        await self.page.mouse.click(box['x'] + box['width'] / 2, box['y'] + 30)
                        logger.info(f"  Expansão via clique no centro do card")

                # Aguardar a expansão (animação do SPA)
                await asyncio.sleep(7)
                await self.page.wait_for_load_state("networkidle", timeout=10000)

                # Checar botão novamente
                btn = card.locator(download_btn_selector).first

                if not await btn.is_visible(timeout=3000):
                    # Fallback 2: scroll dentro do card e checar
                    await card.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
                    await asyncio.sleep(2)
                    btn = card.locator(download_btn_selector).first

                if not await btn.is_visible(timeout=3000):
                    # Fallback 3: clicar via JS no primeiro link de download encontrado
                    logger.info(f"  Tentando clique via JavaScript em {numero_conlicitacao}...")
                    clicked = await card.evaluate("""
                        el => {
                            const links = el.querySelectorAll('a[href], button');
                            for (const link of links) {
                                const text = link.textContent || '';
                                if (/baixar|edital|download/i.test(text)) {
                                    link.click();
                                    return true;
                                }
                            }
                            return false;
                        }
                    """)
                    if clicked:
                        await asyncio.sleep(3)
                        btn = card.locator(download_btn_selector).first

            if not await btn.is_visible(timeout=3000):
                logger.warning(f"Botão de download não localizado para {numero_conlicitacao} após todas as tentativas")
                return None

            await btn.scroll_into_view_if_needed()
            await asyncio.sleep(1)

            download_dir = os.path.join(config.ZIP_DIR, f"edital_{numero_conlicitacao}")
            os.makedirs(download_dir, exist_ok=True)

            logger.info(f"Clicando em Baixar Edital para {numero_conlicitacao}...")
            async with self.page.expect_download(timeout=60000) as download_info:
                await btn.click(force=True)
                download = await download_info.value
                filepath = os.path.join(download_dir, download.suggested_filename)
                await download.save_as(filepath)
                logger.info(f"[OK] Sucesso: {filepath}")
                return filepath

        except Exception as e:
            logger.error(f"[ERR] Erro em download_edital({numero_conlicitacao}): {e}")
            return None

    async def mark_as_favorite(self, numero_conlicitacao: str) -> bool:
        """
        Marca uma licitação como favorita (estrela) no portal.
        
        Args:
            numero_conlicitacao: ID da licitação.
        Returns: True se clicou com sucesso, False caso contrário.
        """
        try:
            logger.info(f"Favoritando licitação {numero_conlicitacao}...")
            
            # 1. Localizar o ID na página
            id_text_locator = self.page.get_by_text(numero_conlicitacao, exact=True).first
            if not await id_text_locator.is_visible(timeout=3000):
                logger.warning(f"ID {numero_conlicitacao} não visível para favoritar")
                return False

            # 2. Isolar o card
            card = id_text_locator.locator(
                "xpath=./ancestor::div[contains(@class,'MuiPaper-root') "
                "or contains(@class,'card') "
                "or contains(@class,'bidding') "
                "or contains(@class,'licitacao')][1]"
            )

            return await self.mark_as_favorite_in_card(card, numero_conlicitacao)

        except Exception as e:
            logger.error(f" [ERR] Erro ao favoritar {numero_conlicitacao}: {e}")
            return False

    async def mark_as_favorite_in_card(self, card, numero_conlicitacao: str) -> bool:
        """Marca como favorito dentro de um card já localizado."""
        try:
            # Seletores possíveis para o botão de favorito (estrela)
            # 1. Por título/tooltip do portal (MUI ou standard alt/title)
            # 2. Por classe de ícone (FontAwesome ou MUI Icons)
            # 3. Por ícone SVG (path que lembra uma estrela)
            fav_selectors = [
                'a[title*="Gerenciar Licitações"]',
                'button[title*="Gerenciar Licitações"]',
                '[aria-label*="Gerenciar Licitações"]',
                '.fa-star',
                '.fa-star-o',
                'svg path[d*="M12 17.27"]', # Típico path de estrela do MUI
                '[class*="star"]',
            ]
            
            fav_btn = None
            for sel in fav_selectors:
                el = card.locator(sel).first
                if await el.is_visible(timeout=500):
                    fav_btn = el
                    logger.info(f"   Botão favorito encontrado via: {sel}")
                    break
            
            if fav_btn:
                await fav_btn.click(force=True)
                logger.info(f" [OK] Licitação {numero_conlicitacao} marcada como favorita.")
                await asyncio.sleep(1)
                return True
            else:
                logger.warning(f" Botão de favorito não encontrado para {numero_conlicitacao}")
                return False
        except Exception as e:
            logger.error(f" [ERR] Erro ao favoritar no card {numero_conlicitacao}: {e}")
            return False

    async def download_editais_batch(self, ids: list[str], favorite: bool = False) -> list[dict]:
        """
        Baixa editais em lote com delays humanizados.
        
        Args:
            ids: Lista de IDs (numero_conlicitacao) das licitaes para download
            favorite: Se True, marca como favorito no processo.
        Returns: Lista de dicts com {id, filepath, success}
        """
        results = []
        for lic_id in ids:
            filepath = await self.download_edital(lic_id, favorite=favorite)
            results.append({
                "id": lic_id,
                "filepath": filepath,
                "success": filepath is not None,
            })
            await self._delay()  # Delay entre downloads

        success_count = sum(1 for r in results if r["success"])
        logger.info(f" Downloads concludos: {success_count}/{len(ids)} com sucesso")
        return results

    async def get_boletim_url_from_email(self, email_html: str) -> str | None:
        """
        Extrai a URL do boletim a partir do HTML do e-mail.
        
        Args:
            email_html: Contedo HTML do e-mail
        Returns: URL do boletim, ou None se no encontrada.
        """
        # Procurar link do boto "Acessar o Boletim"
        patterns = [
            r'href="([^"]*(?:boletim|bulletin)[^"]*)"',
            r'href="(https?://[^"]*conlicitacao[^"]*)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, email_html, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    async def navigate_to_boletim_url(self, url: str) -> bool:
        """
        Navega diretamente a uma URL de boletim extrada do e-mail.
        
        Args:
            url: URL completa do boletim
        Returns: True se navegao foi bem-sucedida.
        """
        try:
            logger.info(f"Navegando  URL do boletim: {url}")
            await self.page.goto(url, wait_until="networkidle", timeout=30000)
            await self._delay()

            # Pode redirecionar para login  tratar
            if "login" in self.page.url.lower():
                logger.info("Redirecionado para login, fazendo login primeiro...")
                if not await self.login():
                    return False
                # Aps login, navegar novamente  URL
                await self.page.goto(url, wait_until="networkidle", timeout=30000)
                await self._delay()

            return True

        except Exception as e:
            logger.error(f" Erro ao navegar  URL do boletim: {e}")
            return False

    async def scrape_bulletin_cards(self) -> tuple[list[dict], int | None]:
        """
        Faz o scraping manual dos cards de licitacao na pagina do boletim.
        Utiliza while-loop com paginação correta para capturar TODOS os cards.
        Util como fallback quando a exportacao XLSX falha.
        Returns: (lista_de_licitacoes, numero_do_boletim)
        """
        licitacoes = []
        boletim_number = self.current_boletim_number
        try:
            logger.info("Iniciando scraping manual dos cards...")

            # Tentar obter o total esperado de licitações no cabeçalho
            total_esperado = None
            try:
                total_el = self.page.locator(r'text=/Total de \d+ licita/')
                if await total_el.is_visible(timeout=5000):
                    total_text = await total_el.inner_text()
                    m = re.search(r'(\d+)', total_text)
                    if m:
                        total_esperado = int(m.group(1))
                        logger.info(f"Total esperado no boletim: {total_esperado} licitações")
            except Exception:
                pass

            # Selectors candidatos para o card container e campos
            CARD_SELECTORS = [
                '.card-body',
                '.MuiCard-root',
                '.MuiPaper-root',
                '[class*="bidding"]',
                '[class*="licitacao"]',
                '[class*="item-licitacao"]',
            ]

            # Selectors para "próxima página"
            NEXT_PAGE_SELECTORS = [
                'ul.pagination li.page-item:not(.disabled) a[aria-label*="xt"]',
                'ul.pagination li.page-item:not(.disabled) a:has-text(">") ',
                'ul.pagination li.page-item:not(.disabled) a:has-text("»")',
                'ul.pagination li.page-item:not(.disabled) a:has-text("Próxima")',
                'ul.pagination li.page-item:not(.disabled) a:has-text("Proxima")',
                'ul.pagination li:not(.disabled) > a[rel="next"]',
                'button[aria-label*="next" i]:not([disabled])',
                'nav[aria-label*="pagination" i] button:last-child:not([disabled])',
            ]

            page_num = 1
            max_pages = 20  # Segurança

            while page_num <= max_pages:
                logger.info(f"Scrapeando pagina {page_num} de cards...")

                # Descobrir qual selector de card funciona nesta página
                card_selector = None
                card_count = 0
                for sel in CARD_SELECTORS:
                    try:
                        await self.page.wait_for_selector(sel, timeout=8000)
                        cnt = await self.page.locator(sel).count()
                        if cnt > 0:
                            card_selector = sel
                            card_count = cnt
                            break
                    except Exception:
                        continue

                if not card_selector:
                    logger.warning(f"Nenhum selector de card funcionou na página {page_num}")
                    break

                logger.info(f"Encontrados {card_count} cards na pagina {page_num} (selector: {card_selector})")

                for i in range(card_count):
                    card = self.page.locator(card_selector).nth(i)
                    try:
                        # Extrair campos via JavaScript — usa padrão label+sibling do portal
                        # Estrutura: div.d-flex > div.bidding-info-title (rótulo) + div.flex-grow-1 > div (valor)
                        fields = await card.evaluate("""
                            el => {
                                function getFieldValue(labelText) {
                                    const rows = el.querySelectorAll('.d-flex');
                                    for (const row of rows) {
                                        const title = row.querySelector('.bidding-info-title');
                                        if (title && title.textContent.includes(labelText)) {
                                            const val = row.querySelector('.flex-grow-1');
                                            if (val) return val.innerText.trim();
                                        }
                                    }
                                    return '';
                                }
                                // Número ConLicitação — rodapé do card
                                let numCon = '';
                                const spans = el.querySelectorAll('span');
                                for (const s of spans) {
                                    if (/^\\d{6,}$/.test(s.textContent.trim())) {
                                        numCon = s.textContent.trim();
                                        break;
                                    }
                                }
                                return {
                                    objeto: getFieldValue('Objeto'),
                                    orgao:  getFieldValue('rgão') || getFieldValue('Orgao') || getFieldValue('Órgão'),
                                    edital: getFieldValue('Edital'),
                                    num_con: numCon || (el.innerText.match(/N[º°].*Conlicita..o:\\s*(\\d+)/i) || [])[1]
                                };
                            }
                        """)

                        objeto  = (fields.get("objeto")  or "").strip()
                        orgao   = (fields.get("orgao")   or "").strip()
                        edital  = (fields.get("edital")  or "").strip()
                        num_con = (fields.get("num_con") or "").strip()

                        # Fallbacks legados se JS não capturou
                        if not objeto:
                            for obj_sel in ['.buMCfY', 'p.card-text', '.objeto', '[class*=\"objeto\"]']:
                                try:
                                    el = card.locator(obj_sel).first
                                    if await el.is_visible(timeout=300):
                                        t = (await el.inner_text()).strip()
                                        if len(t) > 10:
                                            objeto = t
                                            break
                                except Exception:
                                    continue

                        if not num_con:
                            for num_sel in ['.number-cnl + span', '.number-cnl', '[class*=\"cnl\"]']:
                                try:
                                    el = card.locator(num_sel).first
                                    if await el.is_visible(timeout=300):
                                        t = (await el.inner_text()).strip()
                                        if re.match(r'^\d{6,}$', t):
                                            num_con = t
                                            break
                                except Exception:
                                    continue

                        # Data de abertura
                        data_abertura = ""
                        try:
                            da_fields = await card.evaluate("""
                                el => {
                                    const rows = el.querySelectorAll('.d-flex');
                                    for (const row of rows) {
                                        const title = row.querySelector('.bidding-info-title');
                                        if (title && (title.textContent.includes('Prazo') || title.textContent.includes('bertura') || title.textContent.includes('Datas'))) {
                                            const val = row.querySelector('.flex-grow-1');
                                            if (val) return val.innerText.trim();
                                        }
                                    }
                                    return '';
                                }
                            """)
                            data_abertura = (da_fields or "").strip()
                        except Exception:
                            pass

                        if not objeto and not num_con:
                            continue

                        licitacoes.append({
                            "edital": edital,
                            "objeto": objeto,
                            "orgao": orgao.replace("info", "").strip(),
                            "numero_conlicitacao": num_con,
                            "data_abertura": data_abertura,
                        })
                    except Exception as e:
                        logger.warning(f"Erro ao extrair card {i} na pagina {page_num}: {e}")

                # Parar cedo se já temos todos
                if total_esperado and len(licitacoes) >= total_esperado:
                    logger.info(f"[OK] Todos os {total_esperado} cards capturados.")
                    break

                # Tentar ir para a próxima página
                went_next = False
                for next_sel in NEXT_PAGE_SELECTORS:
                    try:
                        next_btn = self.page.locator(next_sel).first
                        if await next_btn.is_visible(timeout=1500):
                            await next_btn.click()
                            logger.info(f"Avançando para página {page_num + 1}...")
                            await asyncio.sleep(5)
                            await self.page.wait_for_load_state("networkidle", timeout=15000)
                            went_next = True
                            break
                    except Exception:
                        continue

                if not went_next:
                    logger.info("Não há mais páginas de cards.")
                    break

                page_num += 1

            logger.info(f"[OK] Scraping manual concluido: {len(licitacoes)} licitacoes encontradas.")
            return licitacoes, boletim_number
        except Exception as e:
            logger.error(f"[ERR] Erro no scraping manual: {e}")
            return licitacoes, boletim_number


async def run_scraping_flow(
    boletim_number: int | None = None,
    boletim_url: str | None = None,
    download_ids: list[str] | None = None,
) -> dict:
    """
    Executa o fluxo completo de scraping com fallback manual.
    """
    async with ConLicitacaoScraper() as scraper:
        if not await scraper.login():
            return {"success": False, "error": "Falha no login"}

        if boletim_url:
            if not await scraper.navigate_to_boletim_url(boletim_url):
                return {"success": False, "error": "Falha ao navegar ao boletim via URL"}
        else:
            if not await scraper.navigate_to_boletim(boletim_number):
                return {"success": False, "error": "Falha ao navegar ao boletim"}

        # Tentar XLSX
        xlsx_path = await scraper.export_xlsx()
        licitacoes = []
        if xlsx_path:
            from .pdf_parser import parse_xlsx
            licitacoes = parse_xlsx(xlsx_path)
        else:
            logger.info("XLSX falhou. Iniciando fallback para scraping manual...")
            licitacoes = await scraper.scrape_bulletin_cards()

        if not licitacoes:
            return {"success": False, "error": "Nenhuma licitacao encontrada (XLSX e Manual falharam)"}

        result = {
            "success": True,
            "xlsx_path": xlsx_path,
            "licitacoes": licitacoes,
            "downloads": [],
        }

        if download_ids:
            result["downloads"] = await scraper.download_editais_batch(download_ids)

        return result
