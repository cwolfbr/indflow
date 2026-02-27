"""
Servidor FastAPI — Expõe endpoints para o n8n chamar o pipeline de triagem.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
import uvicorn

from .pipeline import process_boletim, extract_boletim_number_from_subject
from . import config

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Modelos ───────────────────────────────────────────────────

class BoletimRequest(BaseModel):
    """Payload enviado pelo n8n quando um e-mail de boletim chega."""
    email_subject: str = Field("", description="Assunto do e-mail")
    email_html: str = Field("", description="HTML do corpo do e-mail")
    boletim_number: int | None = Field(None, description="Número do boletim (opcional)")
    boletim_url: str | None = Field(None, description="URL do boletim (opcional)")
    download_editais: bool = Field(True, description="Baixar editais de Alta aderência")
    send_whatsapp: bool = Field(True, description="Enviar relatório via WhatsApp")


class BoletimResponse(BaseModel):
    """Resposta do processamento do boletim."""
    success: bool
    boletim_number: int | None = None
    total_licitacoes: int = 0
    triagem: dict = {}
    editais_baixados: int = 0
    editais_analisados: int = 0
    salvas_no_banco: int = 0
    whatsapp_enviado: bool = False
    errors: list[str] = []


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str


# ── App ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup e shutdown do app."""
    logger.info("🚀 Servidor de Triagem de Licitações iniciando...")
    yield
    logger.info("👋 Servidor encerrando...")


app = FastAPI(
    title="IndFlow — Agente de Triagem de Licitações",
    description="API para processar boletins do ConLicitação automaticamente",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Endpoints ─────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint para monitoramento."""
    return HealthResponse(status="ok", version="1.0.0")


@app.post("/process", response_model=BoletimResponse)
async def process_boletim_endpoint(request: BoletimRequest):
    """
    Processa um boletim do ConLicitação (síncrono).
    
    O n8n chama este endpoint quando detecta um novo e-mail de boletim.
    O processamento pode levar alguns minutos dependendo do volume.
    """
    try:
        logger.info(f"📨 Recebido pedido de processamento: {request.email_subject}")

        result = await process_boletim(
            boletim_number=request.boletim_number,
            boletim_url=request.boletim_url,
            email_subject=request.email_subject,
            email_html=request.email_html,
            download_all_alta=request.download_editais,
            send_whatsapp=request.send_whatsapp,
        )

        return BoletimResponse(
            success=result["success"],
            boletim_number=result.get("boletim_number"),
            total_licitacoes=result.get("total_licitacoes", 0),
            triagem=result.get("triagem", {}),
            editais_baixados=result.get("editais_baixados", 0),
            editais_analisados=result.get("editais_analisados", 0),
            salvas_no_banco=result.get("salvas_no_banco", 0),
            whatsapp_enviado=result.get("whatsapp_enviado", False),
            errors=result.get("errors", []),
        )

    except Exception as e:
        logger.error(f"❌ Erro no endpoint /process: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/process-async")
async def process_boletim_async(
    request: BoletimRequest,
    background_tasks: BackgroundTasks,
):
    """
    Processa um boletim em background (assíncrono).
    Retorna imediatamente com 202 Accepted.
    Útil para evitar timeout no n8n.
    """
    boletim_number = request.boletim_number
    if not boletim_number and request.email_subject:
        boletim_number = extract_boletim_number_from_subject(request.email_subject)

    background_tasks.add_task(
        _run_pipeline_background,
        request=request,
    )

    return {
        "status": "accepted",
        "message": f"Processamento do boletim {boletim_number or 'novo'} iniciado em background",
        "boletim_number": boletim_number,
    }


async def _run_pipeline_background(request: BoletimRequest):
    """Executa o pipeline em background."""
    try:
        await process_boletim(
            boletim_number=request.boletim_number,
            boletim_url=request.boletim_url,
            email_subject=request.email_subject,
            email_html=request.email_html,
            download_all_alta=request.download_editais,
            send_whatsapp=request.send_whatsapp,
        )
    except Exception as e:
        logger.error(f"❌ Erro no pipeline em background: {e}", exc_info=True)


# ── Entrypoint ────────────────────────────────────────────────

def main():
    """Inicia o servidor."""
    uvicorn.run(
        "worker.api:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
