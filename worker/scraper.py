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

            await self.page.goto(
                config.CONLICITACAO_URL,
                wait_until="networkidle",
                timeout=60000,
            )
            # Esperar React renderizar o formulrio
            await asyncio.sleep(3)
            await self._delay()

            # Preencher email
            email_input = self.page.locator('input[type="email"]').first
            await email_input.fill(config.CONLICITACAO_EMAIL)
            await self._delay()

            # Preencher senha
            password_input = self.page.locator('input[type="password"]').first
            await password_input.fill(config.CONLICITACAO_PASSWORD)
            await self._delay()

            # Clicar no boto "Acessar" (React button)
            login_button = self.page.get_by_role("button", name="Acessar")
            await login_button.first.click()

            # Aguardar navegao ps-login
            await asyncio.sleep(5)
            # Aumentar timeout para 60s para lidar com SPA lenta
            await self.page.wait_for_load_state("networkidle", timeout=60000)
            await self._delay()

            # Verificar se login foi bem-sucedido
            is_logged_in = await self._check_logged_in()
            if is_logged_in:
                logger.info("[OK] Login realizado com sucesso!")
            else:
                logger.error(" Falha no login  no foi possvel verificar sesso")
            return is_logged_in

        except Exception as e:
            logger.error(f" Erro durante login: {e}")
            return False

    async def _check_logged_in(self) -> bool:
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
        Navega at um boletim especfico ou o mais recente.
        Fluxo do SPA: Dashboard  Visualizar boletins  Calendrio  Clique no boletim.
        
        Args:
            boletim_number: Nmero do boletim (ex: 1, 2, 3). Se None, vai ao mais recente.
        Returns: True se navegao foi bem-sucedida.
        """
        try:
            logger.info(f"Navegando ao boletim {boletim_number or 'mais recente'}...")

            # Fechar modal de boas-vindas
            await self._close_welcome_modal()

            # Navegar para lista de boletins via "Visualizar" no Dashboard
            # O seletor anterior 'text="Visualizar"' era muito genérico e podia clicar no card errado.
            try:
                # Tentar encontrar o card específico de Boletins primeiro
                boletins_card = self.page.locator('div.MuiPaper-root, .card').filter(has_text="Boletins de Licitações")
                if await boletins_card.count() > 0:
                    viz_link = boletins_card.locator('text="Visualizar"').first
                else:
                    viz_link = self.page.locator('text="Visualizar"').first

                if await viz_link.is_visible(timeout=5000):
                    await viz_link.click()
                    await asyncio.sleep(3)
                    await self.page.wait_for_load_state("networkidle", timeout=15000)
                    logger.info(f"Navegou à lista de boletins: {self.page.url}")
            except Exception as e:
                logger.warning(f"Erro ao clicar em Visualizar: {e}. Tentando seguir...")

            await self._delay()

            # Na página do calendário/lista, encontrar o boletim
            await asyncio.sleep(2) 
            
            # Tentar vários níveis de seletor para os blocos do calendário
            selectors = [
                'div[role="button"]:has-text("Boletim")',
                'span:has-text("Boletim")',
                'a:has-text("Boletim")',
                'div:has-text("Boletim")',
                '.boletim-link',
                'text="Boletim"'
            ]
            
            links_locator = None
            for sel in selectors:
                loc = self.page.locator(sel)
                cnt = await loc.count()
                if cnt > 0:
                    # Verificar se algum deles realmente tem o texto esperado
                    links_locator = loc
                    logger.info(f" Links encontrados ({cnt}) via selector: {sel}")
                    break
            
            if not links_locator:
                debug_path = os.path.join(config.DOWNLOADS_DIR, "debug_boletins_error.png")
                await self.page.screenshot(path=debug_path)
                logger.warning(f"Nenhum link de boletim encontrado. Screenshot de erro: {debug_path}")
                return False

            texts = await links_locator.all_inner_texts()
            # Limpar textos pra remover quebras de linha/espaços excessivos do calendário
            texts = [" ".join(t.split()) for t in texts]
            
            hrefs = []
            links_count = await links_locator.count()
            for i in range(links_count):
                h = await links_locator.nth(i).get_attribute("href")
                hrefs.append(h or "")

            logger.info(f"Lista de boletins detectada: {[t for t in texts if 'Boletim' in t][:10]}...")
            
            latest_link_idx = -1
            if boletim_number:
                target_id = str(boletim_number)
                target_text = f"Boletim {target_id}"
                found = False
                for i, (t, h) in enumerate(zip(texts, hrefs)):
                    if target_text.lower() in t.lower() or h.endswith(f"/{target_id}"):
                        latest_link_idx = i
                        found = True
                        break
                
                if not found:
                    logger.warning(f" Boletim {boletim_number} não encontrado na lista: {texts[:5]}...")
                    # Fallback para o primeiro se não achar o específico (evita travar)
                    latest_link_idx = 0
            else:
                # Pegar o de maior número
                max_num = -1
                for i, t in enumerate(texts):
                    match = re.search(r'Boletim\s+(\d+)', t)
                    if match:
                        num = int(match.group(1))
                        if num > max_num:
                            max_num = num
                            latest_link_idx = i
                
                if latest_link_idx == -1: latest_link_idx = 0

            # Clicar no boletim escolhido
            target_el = links_locator.nth(latest_link_idx)
            logger.info(f"Clicando no boletim: '{texts[latest_link_idx]}'")
            await target_el.click()
            await asyncio.sleep(5)
            await self.page.wait_for_load_state("networkidle", timeout=20000)
            
            return True

        except Exception as e:
            logger.error(f" Erro ao navegar ao boletim: {e}", exc_info=True)
            return False

    async def export_xlsx(self) -> str | None:
        """
        Clica no boto de exportar Excel e aguarda o download.
        """
        try:
            logger.info("Exportando dados em XLSX...")
            
            # Garantir que estamos na página do boletim (esperar o botão aparecer)
            xlsx_btn_selector = 'button:has-text("Gerar .xlsx"), text="Gerar .xlsx"'
            try:
                await self.page.wait_for_selector(xlsx_btn_selector, timeout=15000)
            except:
                logger.warning("Botão XLSX não apareceu rapidamente. Verificando URL...")
                if "boletim" not in self.page.url.lower():
                    logger.error("Não parece estar na página de um boletim para exportar.")
                    return None

            # Rolagem para garantir que elementos SPA carreguem
            await self.page.mouse.wheel(0, 5000)
            await asyncio.sleep(2)

            async with self.page.expect_download(timeout=120000) as download_info:
                # Tentar clicar via vários métodos
                btn = self.page.locator(xlsx_btn_selector).first
                await btn.click(force=True)
                
            download = await download_info.value
            filename = f"boletim_{self.current_boletim_number or 'export'}.xlsx"
            filepath = os.path.join(config.XLSX_DIR, filename)
            await download.save_as(filepath)
            
            logger.info(f"[OK] XLSX exportado: {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"[ERR] Erro ao exportar XLSX: {e}")
            return None
            
            latest_link = links_locator.nth(latest_link_idx)

            if await latest_link.is_visible(timeout=10000):
                await latest_link.scroll_into_view_if_needed()
                await latest_link.click()
                logger.info(f"Clicou no {texts[latest_link_idx]}")
            else:
                logger.warning("Link do boletim no est visvel")
                return False

            await asyncio.sleep(3)
            await self.page.wait_for_load_state("networkidle", timeout=30000)
            await self._delay()

            # Verificar se estamos na pgina do boletim (procurar "Total de X licitaes")
            total_text = self.page.locator(r'text=/Total de \d+ licita/')
            if await total_text.is_visible(timeout=5000):
                text = await total_text.inner_text()
                logger.info(f"[OK] Navegao ao boletim realizada: {text}")
                return True

            # Fallback: verificar se boto "Gerar .xlsx" existe
            xlsx_btn = self.page.locator('text="Gerar .xlsx"').first
            if await xlsx_btn.is_visible(timeout=3000):
                logger.info(" Navegao ao boletim realizada (boto XLSX encontrado)")
                return True

            logger.warning(" No foi possvel confirmar que estamos no boletim")
            return False

        except Exception as e:
            logger.error(f" Erro ao navegar ao boletim: {e}")
            return False

    async def export_xlsx(
        self, 
        boletim_number: int | None = None,
        boletim_url: str | None = None
    ) -> str | None:
        """
        Exporta os dados do boletim em formato XLSX clicando no boto 'Gerar .xlsx'.
        Args:
            boletim_number: Nmero do boletim para navegar
            boletim_url: URL direta para navegar (opcional)
        Returns: Caminho do arquivo XLSX baixado, ou None se falhar.
        """
        try:
            # Sempre navegar ao boletim antes de exportar
            if boletim_url:
                await self.navigate_to_boletim_url(boletim_url)
            else:
                # boletim_number=None → navega ao mais recente automaticamente
                await self.navigate_to_boletim(boletim_number)
                
            logger.info("Exportando dados em XLSX...")

            # Selecionar boletim antes de exportar (necessrio no SPA)
            try:
                sel_boletim = self.page.locator('text="Selecionar boletim"').first
                if await sel_boletim.is_visible(timeout=2000):
                    await sel_boletim.click()
                    await asyncio.sleep(1)
                    logger.info("'Selecionar boletim' marcado")
            except Exception:
                pass  # Prosseguir mesmo sem marcar

            # Rolar at o fim da pgina para garantir que todos os 57+ itens foram carregados no DOM
            # Isso costuma ajudar o SPA a habilitar o boto de exportao completa
            logger.info("Rolando at o final para carregar todos os itens...")
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(3)

            # Clicar no boto "Gerar .xlsx" e capturar o download
            xlsx_button = self.page.locator('text="Gerar .xlsx"').first
            
            # Esperar o boto estar habilitado (pode demorar no SPA enquanto carrega dados)
            logger.info("Aguardando botao XLSX ficar habilitado...")
            try:
                await xlsx_button.scroll_into_view_if_needed()
                # Tentar esperar por um estado 'enabled' explcito ou apenas dar tempo
                await asyncio.sleep(10) # Aumentar tempo para boletins grandes
            except Exception:
                pass

            async with self.page.expect_download(timeout=config.DOWNLOAD_TIMEOUT * 1000) as download_info:
                # Tentar clicar. Se ainda estiver desabilitado, o Playwright vai esperar at o timeout.
                await xlsx_button.click(timeout=90000)
                logger.info("[OK] Botao Gerar .xlsx clicado")

            download = await download_info.value
            filepath = os.path.join(config.XLSX_DIR, download.suggested_filename or "boletim.xlsx")
            await download.save_as(filepath)

            logger.info(f"[OK] XLSX exportado: {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"[ERR] Erro ao exportar XLSX: {e}")
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
        xlsx_path = await scraper.export_xlsx(boletim_number)
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
