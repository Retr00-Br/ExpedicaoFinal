# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from supabase import create_client, Client
import re
import sqlite3
import json
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Master Expedição - Painel Central",
    page_icon="🚚",
    layout="wide"
)

# ==============================================================================
# ARQUITETURA POLIMÓRFICA E POLÍTICA DE SEGURANÇA DE DADOS (ABC)
# ==============================================================================

class Repository(ABC):
    """Interface abstrata para definição de persistência de dados."""
    
    @abstractmethod
    def ler_todos(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def upsert_lote(self, lista_dados: List[Dict[str, Any]]) -> bool:
        pass

    @abstractmethod
    def atualizar_coluna(self, id_registro: str, chave_id: str, dados_atualizacao: Dict[str, Any]) -> bool:
        pass


class LocalQueue(ABC):
    """Interface abstrata para controle de contingência física local (Offline-First)."""
    
    @abstractmethod
    def salvar_offline(self, identificador: str, payload: Dict[str, Any], tipo_operacao: str) -> None:
        pass

    @abstractmethod
    def obter_pendentes(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def resolver_pendentes(self, ids_resolvidos: List[int]) -> None:
        pass

# ==============================================================================
# IMPLEMENTAÇÕES CONCRETAS (POLIMORFISMO NA PRÁTICA)
# ==============================================================================

class SupabaseRepository(Repository):
    """Gerenciador de persistência no Supabase com paginação automática e controle de chunks."""
    
    def __init__(self, client: Client, tabela: str):
        self.client = client
        self.tabela = tabela

    def ler_todos(self) -> List[Dict[str, Any]]:
        """Lê todos os registros tratando a paginação do Supabase para volumes > 1000 itens."""
        todos_dados = []
        limite_pagina = 1000
        offset = 0
        
        try:
            while True:
                resposta = self.client.table(self.tabela)\
                    .select("*")\
                    .range(offset, offset + limite_pagina - 1)\
                    .execute()
                
                dados_pagina = resposta.data
                if not dados_pagina:
                    break
                
                todos_dados.extend(dados_pagina)
                if len(dados_pagina) < limite_pagina:
                    break
                offset += limite_pagina
                
            return todos_dados
        except Exception as e:
            st.error(f"⚠️ Erro crítico na leitura do Supabase ({self.tabela}): {e}")
            return []

    def upsert_lote(self, lista_dados: List[Dict[str, Any]]) -> bool:
        """
        Realiza o Upsert fatiando em lotes menores para evitar estouro de buffer de memória.
        BLINDAGEM ADICIONADA: Configurado para ignorar duplicatas baseando-se na chave correspondente.
        Se o registro já existir no banco, ele NÃO altera e NÃO apaga nada. Mantém o dado original.
        """
        if not lista_dados:
            return True
        
        tamanho_chunk = 150  # Tamanho otimizado para não estourar a API do Supabase
        sucesso_total = True
        
        # Determina o campo de conflito com base no destino da tabela
        campo_conflito = "nota_fiscal" if self.tabela == "tb_divergencias" else "numero_nf"
        
        try:
            for i in range(0, len(lista_dados), tamanho_chunk):
                chunk = lista_dados[i : i + tamanho_chunk]
                
                # Executa o upsert blindado: ignora registros que já existem no Supabase
                self.client.table(self.tabela).upsert(
                    chunk,
                    on_conflict=campo_conflito,
                    ignore_duplicates=True  # <--- BLINDAGEM ATIVA AQUI
                ).execute()
                
            return sucesso_total
        except Exception as e:
            st.error(f"❌ Falha ao sincronizar lote com o Supabase: {e}")
            return False

    def atualizar_coluna(self, id_registro: str, chave_id: str, dados_atualizacao: Dict[str, Any]) -> bool:
        """Atualiza uma linha específica baseada em um ID sanitizado."""
        try:
            resposta = self.client.table(self.tabela)\
                .update(dados_atualizacao)\
                .eq(chave_id, id_registro)\
                .execute()
            return len(resposta.data) > 0
        except Exception as e:
            st.error(f"⚠️ Erro ao atualizar registro {id_registro} via API: {e}")
            return False


class SQLiteQueue(LocalQueue):
    """Banco de dados local leve e ultra-resistente (ACID) para contingência física imediata."""
    
    def __init__(self, db_name="contingencia_expedicao.db"):
        self.db_name = db_name
        self._inicializar_banco()

    def _inicializar_banco(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tb_contingencia (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    identificador TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    tipo_operacao TEXT NOT NULL,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def salvar_offline(self, identificador: str, payload: Dict[str, Any], tipo_operacao: str) -> None:
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO tb_contingencia (identificador, payload, tipo_operacao) VALUES (?, ?, ?)",
                (identificador, json.dumps(payload), tipo_operacao)
            )
            conn.commit()

    # Corrigido de 'obtener_pendentes' para 'obter_pendentes'
    def obter_pendentes(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, identificador, payload, tipo_operacao FROM tb_contingencia ORDER BY id ASC")
            linhas = cursor.fetchall()
            
            pendentes = []
            for id_db, identificador, payload_str, tipo_operacao in linhas:
                pendentes.append({
                    "id_interno": id_db,
                    "identificador": identificador,
                    "payload": json.loads(payload_str),
                    "tipo_operacao": tipo_operacao
                })
            return pendentes

    def resolver_pendentes(self, ids_resolvidos: List[int]) -> None:
        if not ids_resolvidos:
            return
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in ids_resolvidos)
            cursor.execute(f"DELETE FROM tb_contingencia WHERE id IN ({placeholders})", ids_resolvidos)
            conn.commit()
            
# ==============================================================================
# INICIALIZAÇÃO DE REPOSITÓRIOS COM INJEÇÃO DE DEPENDÊNCIA
# ==============================================================================

@st.cache_resource
def obter_cliente_supabase() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# Componentes de infraestrutura instanciados estavelmente
supabase_client = obter_cliente_supabase()
repo_expedicao = SupabaseRepository(supabase_client, "tb_expedicao")
repo_divergencias = SupabaseRepository(supabase_client, "tb_divergencias")
fila_contingencia = SQLiteQueue()

# --- FUNÇÃO DE SINC AUTOMÁTICO (Roda silenciosamente na carga da página) ---
def sincronizar_fila_local_pendente():
    itens_pendentes = fila_contingencia.obter_pendentes()
    if not itens_pendentes:
        return
        
    sucessos = []
    for item in itens_pendentes:
        tipo = item["tipo_operacao"]
        payload = item["payload"]
        identificador = item["identificador"]
        
        if tipo == "UPSERT_EXPEDICAO":
            if repo_expedicao.upsert_lote([payload]):
                sucessos.append(item["id_interno"])
        elif tipo == "UPSERT_DIVERGENCIA":
            if repo_divergencias.upsert_lote([payload]):
                sucessos.append(item["id_interno"])
        elif tipo == "UPDATE_STATUS_EXPEDICAO":
            coluna = payload.get("coluna")
            valor = payload.get("valor")
            reg_dt = payload.get("registrar_data_hora", False)
            
            dados_up = {coluna: valor}
            agora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if reg_dt:
                if coluna == "status_ida":
                    dados_up["data_carregamento_ida"] = agora_str
                elif coluna == "status_volta":
                    dados_up["data_retorno_volta"] = agora_str
            
            if repo_expedicao.atualizar_coluna(identificador, "numero_nf", dados_up):
                sucessos.append(item["id_interno"])

    if sucessos:
        fila_contingencia.resolver_pendentes(sucessos)
        st.sidebar.success(f"🔄 Sincronizador: {len(sucessos)} registros locais enviados!")

# Executa sincronização silenciosa em background
sincronizar_fila_local_pendente()

# ==============================================================================
# ENGENHARIA DEFENSIVA E AUXILIARES
# ==============================================================================

def extrair_nf_da_bipagem(input_bipado: str) -> str:
    if not input_bipado:
        return ""
    texto_limpo = input_bipado.strip().replace("NFe", "")
    texto_limpo = re.sub(r'\D', '', texto_limpo)
    if len(texto_limpo) == 44:
        return str(int(texto_limpo[25:34]))
    if texto_limpo.isdigit() and texto_limpo != "0":
        return str(int(texto_limpo))
    return ""

@st.dialog("📦 Expedição Realizada")
def mostrar_modal_sucesso(mensagem, detalhes_timestamp):
    st.success(mensagem)
    st.markdown(f"**🕒 Registro do Sistema:** {detalhes_timestamp}")
    st.write("A operação foi salva localmente e enviada para a nuvem.")
    if st.button("👍 Prosseguir", use_container_width=True):
        st.rerun()

# ==============================================================================
# CARREGAMENTO DE DADOS COM TRATAMENTO DE EXCEÇÃO E FALLBACKS
# ==============================================================================

def processar_dataframe_expedicao() -> pd.DataFrame:
    dados_raw = repo_expedicao.ler_todos()
    if dados_raw:
        return pd.DataFrame(dados_raw)
    return pd.DataFrame(columns=[
        "numero_nf", "romaneio", "motorista", "cliente", "valor_nota", 
        "data_emissao", "previsao_entrega", "status_ida", "status_volta"
    ])

def processar_dataframe_divergencias() -> pd.DataFrame:
    dados_raw = repo_divergencias.ler_todos()
    if dados_raw:
        df = pd.DataFrame(dados_raw)
        df = df.rename(columns={
            "arquivo_xml": "Arquivo XML",
            "nota_fiscal": "Nota Fiscal",
            "cliente": "Cliente",
            "previsao_entrega": "Previsão Entrega",
            "status_auditoria": "Status Auditoria",
            "justificativa_motivo": "Justificativa / Motivo"
        })
        return df
    return pd.DataFrame(columns=[
        "Arquivo XML", "Nota Fiscal", "Cliente", "Previsão Entrega", "Status Auditoria", "Justificativa / Motivo"
    ])

df_principal = processar_dataframe_expedicao()
df_div = processar_dataframe_divergencias()

# ==============================================================================
# RENDERIZAÇÃO DA INTERFACE DO USUÁRIO (STREAMLIT)
# ==============================================================================

st.sidebar.title("🚚 Controle de Logística")
st.sidebar.markdown("---")
modo_visao = st.sidebar.radio(
    "Selecione o Painel:",
    [
        "📊 Dashboard Geral", 
        "📤 Bipagem - Saída Expedição", 
        "📥 Bipagem - Retorno Carga", 
        "⚙️ Injeção de Planilhas (Carga)", 
        "🚨 Divergências de XML"
    ]
)

# ==============================================================================
# MODO: DASHBOARD GERAL
# ==============================================================================
if modo_visao == "📊 Dashboard Geral":
    st.title("📊 Painel Central de Controle de Entregas")
    
    st.subheader("📈 Indicadores Operacionais da Doca")
    kpi1, kpi2, kpi3 = st.columns(3)
    
    total_notas = len(df_principal)
    financeiro_total = df_principal["valor_nota"].sum() if total_notas > 0 else 0.0
    total_orfas = len(df_div)

    kpi1.metric("Volume de Notas Ativas", f"{total_notas} NFs")
    kpi2.metric("Faturamento Roteirizado", f"R$ {financeiro_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    kpi3.metric("Alertas de Divergência", f"{total_orfas} Ocorrências")

    st.markdown("---")
    st.subheader("📋 Visão Consolidada de Notas Cruzadas (XML 🔄 Romaneio)")
    
    if df_principal.empty:
        st.info("ℹ️ Sistema vazio no Supabase. Realize a primeira carga de planilhas para sincronizar.")
    else:
        st.dataframe(df_principal[[
            "numero_nf", "romaneio", "motorista", "cliente", "valor_nota", "data_emissao", "previsao_entrega", "status_ida", "status_volta"
        ]], use_container_width=True)

# ==============================================================================
# MODO: BIPAGEM - SAÍDA EXPEDIÇÃO
# ==============================================================================
elif modo_visao == "📤 Bipagem - Saída Expedição":
    st.title("📤 Controle de Fluxo - Saída da Doca")
    
    if df_principal.empty:
        st.warning("📋 Sistema vazio no Supabase. Realize a primeira carga para liberar a expedição.")
    else:
        df_limpo = df_principal.dropna(subset=["romaneio"])
        valores_originais = df_limpo["romaneio"].astype(str).str.strip().unique()
        valores_filtrados = [r for r in valores_originais if r not in ["nan", "None", "", "null", "-", "None "]]
        
        if len(valores_filtrados) == 0:
            st.info("💡 Nenhum romaneio ativo aguardando liberação.")
        else:
            romaneios_disponiveis = sorted(valores_filtrados)
            romaneio_selecionado = st.selectbox("📋 Selecione o Romaneio para Carregamento:", romaneios_disponiveis, key="rom_saida")
            df_viagem = df_principal[df_principal["romaneio"].astype(str).str.strip() == romaneio_selecionado]
            
            if not df_viagem.empty:
                nome_motorista = df_viagem["motorista"].iloc[0] if "motorista" in df_viagem.columns and pd.notna(df_viagem["motorista"].iloc[0]) else "Não Informado"
                st.info(f"🚚 Motorista Escalado: {nome_motorista} | Total de Notas: {len(df_viagem)}")
                
                st.markdown("---")
                
                col_bipa_ida, col_problemas_ida = st.columns(2)
                
                with col_bipa_ida:
                    st.markdown("### 🔍 Validação de Saída Física (Carregamento)")
                    nf_bipada_saida = st.text_input("Aponte o Leitor para o Código de Barras (Saída):", key="txt_saida", placeholder="Bipa a nota fiscal...")
                    
                    if nf_bipada_saida:
                        nf_limpa = extrair_nf_da_bipagem(nf_bipada_saida)
                        if nf_limpa and nf_limpa in df_viagem["numero_nf"].astype(str).values:
                            agora_carregamento = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
                            
                            payload_update = {"coluna": "status_ida", "valor": "CONFERIDO NA DOCA / EM TRÂNSITO", "registrar_data_hora": True}
                            fila_contingencia.salvar_offline(nf_limpa, payload_update, "UPDATE_STATUS_EXPEDICAO")
                            
                            enviado = repo_expedicao.atualizar_coluna(
                                nf_limpa, 
                                "numero_nf", 
                                {"status_ida": "CONFERIDO NA DOCA / EM TRÂNSITO", "data_carregamento_ida": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                            )
                            
                            if enviado:
                                pendentes = fila_contingencia.obter_pendentes()
                                ids_limpar = [item["id_interno"] for item in pendentes if item["identificador"] == nf_limpa]
                                fila_contingencia.resolver_pendentes(ids_limpar)
                            
                            mostrar_modal_sucesso(
                                mensagem=f"Nota Fiscal {nf_limpa} liberada e carregada com sucesso!",
                                detalhes_timestamp=f"Expedição registrada em {agora_carregamento}"
                            )
                        else:
                            st.error("❌ Erro de Carregamento: O código lido não corresponde a nenhuma NF pendente deste romaneio!")
                
                with col_problemas_ida:
                    st.markdown("### ⚠️ Registro de Pendências/Não Envio")
                    notas_pendentes_ida = list(df_viagem[df_viagem["status_ida"] == "PENDENTE DE BIPAGEM"]["numero_nf"].astype(str).unique())
                    
                    nf_problema_ida = st.selectbox("Selecione a NF não embarcada:", ["-"] + notas_pendentes_ida, key="sel_problema_ida")
                    motivo_nao_envio = st.selectbox("Selecione o motivo de não embarque:", [
                        "Perda de nota",
                        "Nota não realizada",
                        "Falta de Material",
                        "Mudança na data"
                    ])
                    
                    if st.button("Registrar Ocorrência de Saída") and nf_problema_ida != "-":
                        agora_registro = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
                        novo_status_motivo = f"🚨 RETIDA ({motivo_nao_envio.upper()})"
                        
                        nome_cliente = df_viagem[df_viagem["numero_nf"].astype(str) == nf_problema_ida]["cliente"].iloc[0] if "cliente" in df_viagem.columns else "Cliente Não Identificado"
                        data_prev = df_viagem[df_viagem["numero_nf"].astype(str) == nf_problema_ida]["previsao_entrega"].iloc[0] if "previsao_entrega" in df_viagem.columns else "N/A"
                        
                        div_payload = {
                            "nota_fiscal": nf_problema_ida,
                            "arquivo_xml": f"SAIDA_OCORRENCIA_{nf_problema_ida}.xml",
                            "cliente": nome_cliente,
                            "previsao_entrega": str(data_prev),
                            "status_auditoria": f"🚨 EXPEDIÇÃO RECUSADA ({motivo_nao_envio.upper()})",
                            "justificativa_motivo": f"Problema relatado no carregamento às {agora_registro}: {motivo_nao_envio}"
                        }
                        
                        fila_contingencia.salvar_offline(nf_problema_ida, {"coluna": "status_ida", "valor": novo_status_motivo, "registrar_data_hora": True}, "UPDATE_STATUS_EXPEDICAO")
                        fila_contingencia.salvar_offline(nf_problema_ida, div_payload, "UPSERT_DIVERGENCIA")
                        
                        up_status = repo_expedicao.atualizar_coluna(nf_problema_ida, "numero_nf", {"status_ida": novo_status_motivo, "data_carregamento_ida": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                        up_div = repo_divergencias.upsert_lote([div_payload])
                        
                        if up_status and up_div:
                            pendentes = fila_contingencia.obter_pendentes()
                            ids_limpar = [item["id_interno"] for item in pendentes if item["identificador"] == nf_problema_ida]
                            fila_contingencia.resolver_pendentes(ids_limpar)
                        
                        mostrar_modal_sucesso(
                            mensagem=f"Ocorrência de saída '{motivo_nao_envio}' registrada com sucesso para a NF {nf_problema_ida}!",
                            detalhes_timestamp=f"Ocorrência computada em {agora_registro}"
                        )
                
                st.markdown("---")
                st.subheader("📋 Notas Vinculadas a esta Viagem")
                st.dataframe(df_viagem, use_container_width=True)

# ==============================================================================
# MODO: BIPAGEM - RETORNO CARGA
# ==============================================================================
elif modo_visao == "📥 Bipagem - Retorno Carga":
    st.title("📥 Prestação de Contas - Retorno de Motoristas")
    
    if df_principal.empty:
        st.warning("📋 Sistema vazio no Supabase. Realize a primeira carga de planilhas para sincronizar.")
    else:
        df_limpo = df_principal.dropna(subset=["romaneio"])
        valores_originais = df_limpo["romaneio"].astype(str).str.strip().unique()
        valores_filtrados = [r for r in valores_originais if r not in ["nan", "None", "", "null", "-", "None "]]
            
        if len(valores_filtrados) == 0:
            st.info("💡 Nenhum romaneio válido encontrado na coluna 'romaneio' do banco de dados.")
            df_viagem = pd.DataFrame()
        else:
            romaneios_disponiveis_ret = sorted(valores_filtrados)
            romaneio_selecionado = st.selectbox("📋 Selecione o Romaneio que está retornando:", romaneios_disponiveis_ret, key="rom_ret")
            df_viagem = df_principal[df_principal["romaneio"].astype(str).str.strip() == romaneio_selecionado]
            
        if not df_viagem.empty:
            nome_motorista = df_viagem["motorista"].iloc[0] if "motorista" in df_viagem.columns and pd.notna(df_viagem["motorista"].iloc[0]) else "Não Informado"
            st.info(f"🚚 Motorista: {nome_motorista} | Notas do Romaneio: {len(df_viagem)}")
            
            st.markdown("---")
            col_baixa, col_dev = st.columns(2)
            
            with col_baixa:
                st.markdown("### 🟢 Baixa de Canhotos (Entregues)")
                nf_bipada_ret = st.text_input("Aponte o Leitor (Canhoto):", key="txt_retorno", placeholder="Bipa o canhoto...")
                
                if nf_bipada_ret:
                    nf_limpa = extrair_nf_da_bipagem(nf_bipada_ret)
                    if nf_limpa and nf_limpa in df_viagem["numero_nf"].astype(str).values:
                        agora_retorno = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
                        
                        fila_contingencia.salvar_offline(
                            nf_limpa, 
                            {"coluna": "status_volta", "valor": "ENTREGUE / CANHOTO OK", "registrar_data_hora": True}, 
                            "UPDATE_STATUS_EXPEDICAO"
                        )
                        
                        enviado = repo_expedicao.atualizar_coluna(
                            nf_limpa, 
                            "numero_nf", 
                            {"status_volta": "ENTREGUE / CANHOTO OK", "data_retorno_volta": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                        )
                        
                        if enviado:
                            pendentes = fila_contingencia.obter_pendentes()
                            ids_limpar = [item["id_interno"] for item in pendentes if item["identificador"] == nf_limpa]
                            fila_contingencia.resolver_pendentes(ids_limpar)
                        
                        mostrar_modal_sucesso(
                            mensagem=f"Baixa confirmada para a NF {nf_limpa}! Canhoto validado e retornado física/digitalmente.",
                            detalhes_timestamp=f"Retorno de Carga realizado em {agora_retorno}"
                        )
                    else:
                        st.error("❌ Erro de Roteiro: O código lido não pertence a esta viagem!")

            with col_dev:
                st.markdown("### 🔴 Registro de Ocorrências / Não Retorno")
                notas_pendentes_volta = list(df_viagem[df_viagem["status_volta"] == "EM AGUARDO"]["numero_nf"].astype(str).unique())
                
                nf_problema = st.selectbox("Selecione a NF com Ocorrência:", ["-"] + notas_pendentes_volta)
                motivo_nao_retorno = st.selectbox("Motivo do Não Retorno do Canhoto:", [
                    "🚨 DEVOLUÇÃO TOTAL", 
                    "❌ RECUSADO PELO CLIENTE", 
                    "🔄 REENTREGA SOLICITADA", 
                    "🔍 CANHOTO EM ANÁLISE"
                ])
                
                if st.button("Registrar Ocorrência") and nf_problema != "-":
                    agora_retorno_problema = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
                    
                    nome_cliente = df_viagem[df_viagem["numero_nf"].astype(str) == nf_problema]["cliente"].iloc[0] if "cliente" in df_viagem.columns else "Cliente Não Identificado"
                    data_prev = df_viagem[df_viagem["numero_nf"].astype(str) == nf_problema]["previsao_entrega"].iloc[0] if "previsao_entrega" in df_viagem.columns else "N/A"

                    div_payload = {
                        "nota_fiscal": nf_problema,
                        "arquivo_xml": f"RETORNO_OCORRENCIA_{nf_problema}.xml",
                        "cliente": nome_cliente,
                        "previsao_entrega": str(data_prev),
                        "status_auditoria": f"🚨 RETORNO WITH ERROR ({motivo_nao_retorno})",
                        "justificativa_motivo": f"Problema relatado no retorno do motorista às {agora_retorno_problema}: {motivo_nao_retorno}"
                    }
                    
                    fila_contingencia.salvar_offline(nf_problema, {"coluna": "status_volta", "valor": motivo_nao_retorno, "registrar_data_hora": True}, "UPDATE_STATUS_EXPEDICAO")
                    fila_contingencia.salvar_offline(nf_problema, div_payload, "UPSERT_DIVERGENCIA")
                    
                    up_status = repo_expedicao.atualizar_coluna(nf_problema, "numero_nf", {"status_volta": motivo_nao_retorno, "data_retorno_volta": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                    up_div = repo_divergencias.upsert_lote([div_payload])
                    
                    if up_status and up_div:
                        pendentes = fila_contingencia.obter_pendentes()
                        ids_limpar = [item["id_interno"] for item in pendentes if item["identificador"] == nf_problema]
                        fila_contingencia.resolver_pendentes(ids_limpar)
                    
                    mostrar_modal_sucesso(
                        mensagem=f"Ocorrência de retorno gravada com sucesso para a NF {nf_problema}!",
                        detalhes_timestamp=f"Ocorrência catalogada às {agora_retorno_problema}"
                    )

            st.markdown("---")
            st.subheader("📋 Grid de Controle de Entrega Física da Viagem")
            st.dataframe(df_viagem, use_container_width=True)

# ==============================================================================
# MODO: INJEÇÃO DE PLANILHAS (CARGA VIA REPOSITÓRIO LIMITADO POR MEMÓRIA)
# ==============================================================================
elif modo_visao == "⚙️ Injeção de Planilhas (Carga)":
    st.title("⚙️ Painel de Carga e Cruzamento de Dados")
    st.subheader("Alimente e sincronize a base de dados com proteção de memória")

    col1, col2 = st.columns(2)
    with col1:
        romaneio_file = st.file_uploader("1. Carregar Romaneios.csv", type=["csv"])
    with col2:
        xml_files = st.file_uploader("2. Selecionar Arquivos XML", type=["xml"], accept_multiple_files=True)

    if st.button("🚀 Processar e Sincronizar com Supabase", use_container_width=True):
        if not romaneio_file or not xml_files:
            st.error("❌ Carregue ambos os arquivos para executar o processamento.")
        else:
            with st.spinner("⏳ Analisando e fatiando cargas para proteção do banco de dados..."):
                try:
                    nfs_romaneios = {}
                    romaneio_atual = "-"
                    motorista_atual = "-"
                    
                    conteudo_csv = romaneio_file.getvalue().decode("utf-8", errors="ignore").splitlines()
                    
                    for linha in conteudo_csv:
                        linha_limpa = linha.strip()
                        if not linha_limpa:
                            continue
                        
                        colunas = [c.strip() for c in linha.split(";")]
                        if len(colunas) == 0:
                            continue
                        
                        primeira_celula = colunas[0]
                        if re.match(r'^\d+\s*-', primeira_celula):
                            romaneio_atual = primeira_celula.split("-")[0].strip()
                            if len(colunas) > 4 and colunas[4]:
                                motorista_atual = colunas[4].strip()
                            continue
                        
                        if "Nr. Romaneio" in primeira_celula or "Filial" in primeira_celula:
                            continue
                        
                        num_nf_raw = ""
                        valor_raw = ""
                        
                        colunas_validas = [c for c in colunas if c != ""]
                        if len(colunas_validas) >= 3:
                            for idx, celula in enumerate(colunas):
                                if "R$" in celula:
                                    valor_raw = celula
                                    if idx > 0 and colunas[idx-1].isdigit():
                                        num_nf_raw = colunas[idx-1]
                                    break
                                    
                            if not num_nf_raw:
                                for celula in reversed(colunas):
                                    if celula.isdigit() and len(celula) >= 4 and len(celula) <= 9:
                                        num_nf_raw = celula
                                        break
                        
                        if num_nf_raw and num_nf_raw.isdigit() and num_nf_raw != "0":
                            num_nf_limpo = str(int(num_nf_raw))
                            
                            valor_limpo = valor_raw.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".").strip()
                            try:
                                valor_estimado = float(valor_limpo)
                            except:
                                valor_estimado = 0.0
                                            
                            nfs_romaneios[num_nf_limpo] = {
                                "romaneio": romaneio_atual,
                                "motorista": motorista_atual if motorista_atual != "-" else "MOTORISTA PADRÃO",
                                "valor": valor_estimado
                            }

                    lista_divergencias = []
                    novos_registros_expedicao = []

                    # Reconstrução do Processamento Seguro dos Arquivos XML
                    for xml_file in xml_files:
                        try:
                            tree = ET.parse(xml_file)
                            root = tree.getroot()
                            
                            ns = {'ns': 'http://www.portalfiscal.inf.br/nfe'}
                            
                            infNFe = root.find('.//ns:infNFe', ns)
                            if infNFe is None:
                                continue
                                
                            ide = infNFe.find('ns:ide', ns)
                            emit = infNFe.find('ns:emit', ns)
                            dest = infNFe.find('ns:dest', ns)
                            
                            n_nf = ide.find('ns:nNF', ns).text if ide is not None else ""
                            dh_emi = ide.find('ns:dhEmi', ns).text[:10] if ide is not None and ide.find('ns:dhEmi', ns) is not None else ""
                            x_nome = dest.find('ns:xNome', ns).text if dest is not None else "CLIENTE DESCONHECIDO"
                            
                            if n_nf:
                                num_nf_xml = str(int(n_nf))
                                
                                # Verifica se a NF pertence ao romaneio
                                if num_nf_xml in nfs_romaneios:
                                    dados_romaneio = nfs_romaneios[num_nf_xml]
                                    
                                    dt_emissao = datetime.strptime(dh_emi, "%Y-%m-%d") if dh_emi else datetime.now()
                                    previsao = (dt_emissao + timedelta(days=5)).strftime("%Y-%m-%d")
                                    
                                    payload_nota = {
                                        "numero_nf": num_nf_xml,
                                        "romaneio": dados_romaneio["romaneio"],
                                        "motorista": dados_romaneio["motorista"],
                                        "cliente": x_nome,
                                        "valor_nota": dados_romaneio["valor"],
                                        "data_emissao": dh_emi,
                                        "previsao_entrega": previsao,
                                        "status_ida": "PENDENTE DE BIPAGEM",
                                        "status_volta": "EM AGUARDO"
                                    }
                                    novos_registros_expedicao.append(payload_nota)
                                else:
                                    # NF Órfã (Inexistente no romaneio carregado)
                                    payload_div = {
                                        "nota_fiscal": num_nf_xml,
                                        "arquivo_xml": xml_file.name,
                                        "cliente": x_nome,
                                        "previsao_entrega": (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d"),
                                        "status_auditoria": "⚠️ XML SEM ROMANEIO",
                                        "justificativa_motivo": "Nota importada via XML porém inexistente no romaneio carregado."
                                    }
                                    lista_divergencias.append(payload_div)
                                    
                        except Exception as xml_err:
                            st.error(f"⚠️ Falha de parseamento no XML {xml_file.name}: {xml_err}")

                    # Salva em lote e limpa as contingências locais
                    sucesso_carga = True
                    if novos_registros_expedicao:
                        for reg in novos_registros_expedicao:
                            fila_contingencia.salvar_offline(reg["numero_nf"], reg, "UPSERT_EXPEDICAO")
                        sucesso_carga = repo_expedicao.upsert_lote(novos_registros_expedicao)

                    if lista_divergencias:
                        for div in lista_divergencias:
                            fila_contingencia.salvar_offline(div["nota_fiscal"], div, "UPSERT_DIVERGENCIA")
                        repo_divergencias.upsert_lote(lista_divergencias)

                    if sucesso_carga:
                        pendentes = fila_contingencia.obter_pendentes()
                        ids_resolvidos = []
                        for item in pendentes:
                            id_nf = item["identificador"]
                            if item["tipo_operacao"] == "UPSERT_EXPEDICAO" and id_nf in [x["numero_nf"] for x in novos_registros_expedicao]:
                                ids_resolvidos.append(item["id_interno"])
                            elif item["tipo_operacao"] == "UPSERT_DIVERGENCIA" and id_nf in [x["nota_fiscal"] for x in lista_divergencias]:
                                ids_resolvidos.append(item["id_interno"])
                                
                        fila_contingencia.resolver_pendentes(ids_resolvidos)
                        st.success("🎉 Injeção de dados executada com sucesso! Duplicatas e registros pré-existentes foram blindados e protegidos.")
                        st.rerun()

                except Exception as e:
                    st.error(f"❌ Falha de processamento geral da carga de arquivos: {e}")

# ==============================================================================
# MODO: DIVERGÊNCIAS DE XML
# ==============================================================================
elif modo_visao == "🚨 Divergências de XML":
    st.title("🚨 Alertas de Auditoria e Divergências de Notas")
    st.subheader("Visualização física de incoerências identificadas")
    
    if df_div.empty:
        st.success("✅ Nenhuma divergência operacional detectada no momento.")
    else:
        st.dataframe(df_div, use_container_width=True)
