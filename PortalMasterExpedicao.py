# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from supabase import create_client, Client
import re

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Master Expedição - Painel Central",
    page_icon="🚚",
    layout="wide"
)

# --- CONEXÃO COM O SUPABASE (VIA SECRETS SEGURO) ---
@st.cache_resource
def iniciar_conexao_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = iniciar_conexao_supabase()

# --- FUNÇÃO DE ENGENHARIA DEFENSIVA (SANATIZAÇÃO DE ENTRADA DO LEITOR) ---
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

# --- FUNÇÕES DE INTERAÇÃO COM O BANCO ---
def carregar_dados_principais():
    try:
        resposta = supabase.table("tb_expedicao").select("*").execute()
        if resposta.data and len(resposta.data) > 0:
            return pd.DataFrame(resposta.data)
        return pd.DataFrame(columns=["numero_nf", "romaneio", "motorista", "cliente", "valor_nota", "data_emissao", "previsao_entrega", "status_ida", "status_volta"])
    except Exception as e:
        st.sidebar.error(f"⚠️ Erro ao ler Expedição: {e}")
        return pd.DataFrame(columns=["numero_nf", "romaneio", "motorista", "cliente", "valor_nota", "data_emissao", "previsao_entrega", "status_ida", "status_volta"])

def carregar_divergencias():
    try:
        resposta = supabase.table("tb_divergencias").select("*").execute()
        if resposta.data and len(resposta.data) > 0:
            df = pd.DataFrame(resposta.data)
            df = df.rename(columns={
                "arquivo_xml": "Arquivo XML",
                "nota_fiscal": "Nota Fiscal",
                "cliente": "Cliente",
                "previsao_entrega": "Previsão Entrega",
                "status_auditoria": "Status Auditoria",
                "justificativa_motivo": "Justificativa / Motivo"
            })
            return df
        return pd.DataFrame(columns=["Arquivo XML", "Nota Fiscal", "Cliente", "Previsão Entrega", "Status Auditoria", "Justificativa / Motivo"])
    except Exception as e:
        st.sidebar.error(f"⚠️ Erro ao ler Divergências: {e}")
        return pd.DataFrame(columns=["Arquivo XML", "Nota Fiscal", "Cliente", "Previsão Entrega", "Status Auditoria", "Justificativa / Motivo"])

def salvar_dados_consolidados(dados_notas, dados_divergencias):
    try:
        if dados_notas:
            for nota in dados_notas:
                supabase.table("tb_expedicao").upsert(nota, on_conflict="numero_nf").execute()
        if dados_divergencias:
            for div in dados_divergencias:
                div_sql = {
                    "nota_fiscal": div["Nota Fiscal"],
                    "arquivo_xml": div["Arquivo XML"],
                    "cliente": div["Cliente"],
                    "previsao_entrega": div["Previsão Entrega"],
                    "status_auditoria": div["Status Auditoria"],
                    "justificativa_motivo": div["Justificativa / Motivo"]
                }
                supabase.table("tb_divergencias").upsert(div_sql).execute()
        return True
    except Exception as e:
        st.error(f"Erro ao salvar dados no Supabase: {e}")
        return False

def atualizar_status_bipagem(numero_nf, coluna_status, novo_status):
    try:
        nf_sanitizada = str(int(str(numero_nf).strip()))
        resposta = supabase.table("tb_expedicao").update({coluna_status: novo_status}).eq("numero_nf", nf_sanitizada).execute()
        return len(resposta.data) > 0
    except Exception as e:
        st.error(f"Erro ao atualizar status: {e}")
        return False

# --- CARREGAMENTO DE DADOS INICIAIS ---
df_principal = carregar_dados_principais()
df_div = carregar_divergencias()

# --- MENU LATERAL ---
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
                st.markdown("### 🔍 Validação de Saída Física")
                nf_bipada_saida = st.text_input("Aponte o Leitor para o Código de Barras (Saída):", key="txt_saida", placeholder="Bipa a nota fiscal...")
                
                if nf_bipada_saida:
                    nf_limpa = extrair_nf_da_bipagem(nf_bipada_saida)
                    if nf_limpa and nf_limpa in df_viagem["numero_nf"].astype(str).values:
                        if atualizar_status_bipagem(nf_limpa, "status_ida", "CONFERIDO NA DOCA / EM TRÂNSITO"):
                            st.success(f"✅ NF {nf_limpa} liberada e embarcada com sucesso!")
                            st.rerun()
                    else:
                        st.error(f"❌ Erro de Carregamento: O código lido não corresponde a nenhuma NF pendente deste romaneio!")
                
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
                        if atualizar_status_bipagem(nf_limpa, "status_volta", "ENTREGUE / CANHOTO OK"):
                            st.success(f"✅ Baixa confirmada para a NF {nf_limpa} no banco de dados!")
                            st.rerun()
                    else:
                        st.error(f"❌ Erro de Roteiro: O código lido não pertence a esta viagem!")

            with col_dev:
                st.markdown("### 🔴 Registro de Ocorrências / Não Retorno")
                status_col = "status_volta"
                notas_pendentes_volta = list(df_viagem[df_viagem[status_col] == "EM AGUARDO"]["numero_nf"].astype(str).unique())
                
                nf_problema = st.selectbox("Selecione a NF com Ocorrência:", ["-"] + notas_pendentes_volta)
                motivo_nao_retorno = st.selectbox("Motivo do Não Retorno do Canhoto:", [
                    "🚨 DEVOLUÇÃO TOTAL", 
                    "❌ RECUSADO PELO CLIENTE", 
                    "🔄 REENTREGA SOLICITADA", 
                    "🔍 CANHOTO EM ANÁLISE"
                ])
                
                if st.button("Registrar Ocorrência") and nf_problema != "-":
                    if atualizar_status_bipagem(nf_problema, "status_volta", motivo_nao_retorno):
                        nome_cliente = df_viagem[df_viagem["numero_nf"].astype(str) == nf_problema]["cliente"].iloc[0] if "cliente" in df_viagem.columns else "Cliente Não Identificado"
                        data_prev = df_viagem[df_viagem["numero_nf"].astype(str) == nf_problema]["previsao_entrega"].iloc[0] if "previsao_entrega" in df_viagem.columns else "N/A"

                        nova_div_ret = [{
                            "Nota Fiscal": nf_problema,
                            "Arquivo XML": f"RETORNO_OCORRENCIA_{nf_problema}.xml",
                            "Cliente": nome_cliente,
                            "Previsão Entrega": str(data_prev),
                            "Status Auditoria": f"🚨 RETORNO WITH ERROR ({motivo_nao_retorno})",
                            "Justificativa / Motivo": f"Problema relatado no retorno do motorista: {motivo_nao_retorno}"
                        }]
                        salvar_dados_consolidados(None, nova_div_ret)
                        st.error(f"📌 Ocorrência gravada na auditoria do Supabase para a NF {nf_problema}.")
                        st.rerun()

            st.markdown("---")
            st.subheader("📋 Grid de Controle de Entrega Física da Viagem")
            st.dataframe(df_viagem, use_container_width=True)

# ==============================================================================
# MODO: INJEÇÃO DE PLANILHAS (SISTEMA DE CAPTURA CORRIGIDO PARA ARQUIVOS GRANDES)
# ==============================================================================
elif modo_visao == "⚙️ Injeção de Planilhas (Carga)":
    st.title("⚙️ Painel de Carga e Cruzamento de Dados")
    st.subheader("Alimente e sincronize a base de dados do Supabase")

    col1, col2 = st.columns(2)
    with col1:
        romaneio_file = st.file_uploader("1. Carregar Romaneios.csv", type=["csv"])
    with col2:
        xml_files = st.file_uploader("2. Selecionar Arquivos XML", type=["xml"], accept_multiple_files=True)

    if st.button("🚀 Processar e Sincronizar com Supabase", use_container_width=True):
        if not romaneio_file or not xml_files:
            st.error("❌ Carregue ambos os arquivos para executar o processamento.")
        else:
            with st.spinner("⏳ Analisando e processando grandes volumes de dados..."):
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
                        
                        # --- MOTOR DE EXTRAÇÃO REFEITO ---
                        # Evita falhar se o separador mudar ou se houver espaços ocultos no cabeçalho
                        primeira_celula = colunas[0]
                        
                        # Se contiver a expressão regular de romaneio ex: "11250 -" ou similar, captura
                        if re.match(r'^\d+\s*-', primeira_celula):
                            romaneio_atual = primeira_celula.split("-")[0].strip()
                            if len(colunas) > 4 and colunas[4]:
                                motorista_atual = colunas[4].strip()
                            continue
                        
                        if "Nr. Romaneio" in primeira_celula or "Filial" in primeira_celula:
                            continue
                        
                        # Captura as Notas Fiscais dinamicamente sem limite posicional rígido
                        if len(colunas) >= 12:
                            # Tenta ler a NF na coluna 10 (Índice padrão do ERP)
                            num_nf_raw = colunas[10].strip()
                            valor_raw = colunas[11].strip()
                            
                            if num_nf_raw.isdigit() and num_nf_raw != "0":
                                num_nf_limpo = str(int(num_nf_raw))
                                valor_limpo = valor_raw.replace("R$", "").replace(".", "").replace(",", ".").strip()
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
                    notes_validadas = []

                    # 3. CRUZAMENTO COM OS ARQUIVOS XML
                    for xml_file in xml_files:
                        try:
                            tree = ET.parse(xml_file)
                            root = tree.getroot()
                            ns = {'ns': 'http://www.portalfiscal.inf.br/nfe'}

                            num_nf_xml = root.find('.//ns:ide/ns:nNF', ns)
                            cliente_xml = root.find('.//ns:dest/ns:xNome', ns)
                            dhEmi_xml = root.find('.//ns:ide/ns:dhEmi', ns)
                            vNF_xml = root.find('.//ns:total/ns:ICMSTot/ns:vNF', ns)

                            if num_nf_xml is not None:
                                nf_limpa = str(int(num_nf_xml.text.strip()))
                                nome_cliente = cliente_xml.text.strip() if cliente_xml is not None else "Não Identificado"
                                valor_nota = float(vNF_xml.text) if vNF_xml is not None else 0.0
                                
                                data_previsao_xml = "-"
                                data_emissao_str = "-"
                                if dhEmi_xml is not None and dhEmi_xml.text:
                                    try:
                                        data_iso = dhEmi_xml.text.split("T")[0]
                                        data_obj = datetime.strptime(data_iso, "%Y-%m-%d")
                                        data_emissao_str = data_obj.strftime("%d/%m/%Y")
                                        data_previsao_xml = (data_obj + timedelta(days=2)).strftime("%d/%m/%Y")
                                    except: 
                                        pass

                                if nf_limpa in nfs_romaneios:
                                    notes_validadas.append({
                                        "numero_nf": nf_limpa,
                                        "romaneio": nfs_romaneios[nf_limpa]["romaneio"],
                                        "motorista": nfs_romaneios[nf_limpa]["motorista"],
                                        "cliente": nome_cliente,
                                        "valor_nota": valor_nota if valor_nota > 0 else nfs_romaneios[nf_limpa]["valor"],
                                        "data_emissao": data_emissao_str,
                                        "previsao_entrega": data_previsao_xml,
                                        "status_ida": "PENDENTE DE BIPAGEM",
                                        "status_volta": "EM AGUARDO"
                                    })
                                else:
                                    lista_divergencias.append({
                                        "Arquivo XML": xml_file.name,
                                        "Nota Fiscal": nf_limpa,
                                        "Cliente": nome_cliente,
                                        "Previsão Entrega": data_previsao_xml,
                                        "Status Auditoria": "🚨 FORA DO ROMANEIO (ÓRFÃ)",
                                        "Justificativa / Motivo": "🗺️ Erro de Roteirização (Faturado sem Viagem)"
                                    })
                        except Exception as xml_err:
                            continue

                    # --- SUBIDA EM LOTE (BULK UPSERT) OTIMIZADO ---
                    # Dividimos em blocos de 200 registros para garantir que o Supabase/PostgreSQL 
                    # processe tudo sem estourar o buffer de memória ou dar timeout.
                    tamanho_lote = 200
                    sucesso_salvamento = True
                    
                    try:
                        if notes_validadas:
                            for i in range(0, len(notes_validadas), tamanho_lote):
                                lote = notes_validadas[i:i + tamanho_lote]
                                supabase.table("tb_expedicao").upsert(lote, on_conflict="numero_nf").execute()
                        
                        if lista_divergencias:
                            div_sql_list = []
                            for div in lista_divergencias:
                                div_sql_list.append({
                                    "nota_fiscal": div["Nota Fiscal"],
                                    "arquivo_xml": div["Arquivo XML"],
                                    "cliente": div["Cliente"],
                                    "previsao_entrega": div["Previsão Entrega"],
                                    "status_auditoria": div["Status Auditoria"],
                                    "justificativa_motivo": div["Justificativa / Motivo"]
                                })
                            for i in range(0, len(div_sql_list), tamanho_lote):
                                lote_div = div_sql_list[i:i + tamanho_lote]
                                supabase.table("tb_divergencias").upsert(lote_div).execute()
                    except Exception as db_err:
                        st.error(f"Falha na gravação dos dados: {db_err}")
                        sucesso_salvamento = False

                    if sucesso_salvamento:
                        st.success(f"📊 Processamento completo! {len(notes_validadas)} notas integradas e {len(lista_divergencias)} divergências salvas.")
                        st.rerun()
                except Exception as e:
                    st.error(f"⚠️ Erro no processamento global: {e}")

# ==============================================================================
# MODO: DIVERGÊNCIAS DE XML
# ==============================================================================
elif modo_visao == "🚨 Divergências de XML":
    st.title("🚨 Central Única de Auditoria e Divergências")
    st.subheader("Todas as inconsistências de faturamento, ocorrências de retorno e notas retidas")

    if df_div.empty:
        st.success("✅ Tudo limpo! Nenhuma divergência operacional ou nota retida ativa no banco de dados.")
    else:
        st.warning(f"Atenção: Existem {len(df_div)} ocorrências ativas exigindo tratativa da supervisão.")
        st.dataframe(df_div[[
            "Arquivo XML", "Nota Fiscal", "Cliente", "Previsão Entrega", "Status Auditoria", "Justificativa / Motivo"
        ]], use_container_width=True)
