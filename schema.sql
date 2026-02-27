-- ============================================================
-- Schema Supabase: Agente de Triagem de Licitações — IndFlow
-- ============================================================

-- Tabela principal de licitações processadas
CREATE TABLE IF NOT EXISTS licitacoes (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    
    -- Dados extraídos do boletim (XLSX)
    numero_edital TEXT,
    objeto TEXT NOT NULL,
    orgao TEXT,
    cidade_uf TEXT,
    data_abertura TEXT,
    valor_estimado TEXT,
    status_licitacao TEXT,
    palavras_chave TEXT,
    modalidade TEXT,
    numero_conlicitacao TEXT,
    numero_boletim INTEGER,
    
    -- Resultado da triagem IA
    aderencia TEXT CHECK (aderencia IN ('ALTA', 'MEDIA', 'BAIXA')),
    recomendacao TEXT CHECK (recomendacao IN ('PARTICIPAR', 'ACOMPANHAR', 'DESCARTAR')),
    resumo_ia TEXT,
    analise_completa JSONB,
    
    -- Arquivos
    arquivo_edital_url TEXT,
    
    -- Metadados
    processado_em TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para busca rápida
CREATE INDEX IF NOT EXISTS idx_licitacoes_aderencia ON licitacoes(aderencia);
CREATE INDEX IF NOT EXISTS idx_licitacoes_recomendacao ON licitacoes(recomendacao);
CREATE INDEX IF NOT EXISTS idx_licitacoes_boletim ON licitacoes(numero_boletim);
CREATE INDEX IF NOT EXISTS idx_licitacoes_conlicitacao ON licitacoes(numero_conlicitacao);
CREATE INDEX IF NOT EXISTS idx_licitacoes_created ON licitacoes(created_at DESC);

-- Unique constraint para evitar duplicatas
CREATE UNIQUE INDEX IF NOT EXISTS idx_licitacoes_unique 
    ON licitacoes(numero_conlicitacao) 
    WHERE numero_conlicitacao IS NOT NULL AND numero_conlicitacao != '';

-- Trigger para atualizar updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_licitacoes_updated_at 
    BEFORE UPDATE ON licitacoes 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Tabela de log de processamento
CREATE TABLE IF NOT EXISTS processamento_log (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    numero_boletim INTEGER,
    total_licitacoes INTEGER DEFAULT 0,
    alta_aderencia INTEGER DEFAULT 0,
    media_aderencia INTEGER DEFAULT 0,
    baixa_aderencia INTEGER DEFAULT 0,
    editais_baixados INTEGER DEFAULT 0,
    editais_analisados INTEGER DEFAULT 0,
    whatsapp_enviado BOOLEAN DEFAULT FALSE,
    erros TEXT[],
    duracao_segundos REAL,
    processado_em TIMESTAMPTZ DEFAULT NOW()
);

-- RLS (Row Level Security) — desabilitado para acesso via service key
ALTER TABLE licitacoes ENABLE ROW LEVEL SECURITY;
ALTER TABLE processamento_log ENABLE ROW LEVEL SECURITY;

-- Política para service_role (acesso total)
CREATE POLICY "Service role full access on licitacoes" 
    ON licitacoes FOR ALL 
    USING (true) 
    WITH CHECK (true);

CREATE POLICY "Service role full access on processamento_log" 
    ON processamento_log FOR ALL 
    USING (true) 
    WITH CHECK (true);
