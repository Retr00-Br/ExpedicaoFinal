# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from supabase import create_client, Client

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

# --- FUNÇÕES DE INTERAÇÃO COM O BANCO ---
def carregar_dados_principais():
    try:
        # Garante a busca correta dos dados
        resposta = supabase.table("bd_expedicao").select("*").execute()
        if resposta.data and len(resposta.data) > 0:
            return pd.DataFrame(resposta.data)
        # Se retornar uma lista vazia, monta a estrutura padrão vazia
        return pd.DataFrame(columns=["numero_nf", "romaneio", "motorista", "cliente", "valor_nota", "data_emissao", "previsao_entrega", "status_ida", "status_volta"])
    except Exception as e:
        st.sidebar.error(f"⚠️ Erro ao ler Expedição: {e}")
        return pd.DataFrame(columns=["numero_nf", "romaneio", "motorista", "cliente", "valor_nota", "data_emissao", "previsao_entrega", "status_ida", "status_volta"])

def carregar_divergencias():
    try:
        resposta = supabase.table("bd_divergencias").select("*").execute()
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
                supabase.table("bd_expedicao").upsert(nota).execute()
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
                supabase.table("bd_divergencias").upsert(div_sql).execute()
        return True
    except Exception as e:
        st.error(f"Erro ao salvar dados no Supabase: {e}")
        return False

def atualizar_status_bipagem(numero_nf, coluna_status, novo_status):
    try:
        resposta = supabase.table("bd_expedicao").update({coluna_status: novo_status}).eq("numero_nf", numero_nf).execute()
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
    st.title("📤 Controle de Portaria - Saída de Veículos")
    
    if df_principal.empty:
        st.warning("📋 Sistema vazio no Supabase. Realize a primeira carga de planilhas para sincronizar.")
    else:
        # --- TRATAMENTO SEGURO PARA O MOTOR DE BUSCA DA IDA ---
        valores_romaneio_ida = df_principal['romaneio'].dropna().unique() if 'romaneio' in df_principal.columns else []
        
        if len(valores_romaneio_ida) == 0:
            st.warning("📋 Nenhum romaneio ativo para saída encontrado no banco de dados.")
        else:
            romaneios_disponiveis_ida = sorted(valores_romaneio_ida)
            romaneio_selecionado = st.selectbox("📋 Selecione o Romaneio para conferência:", romaneios_disponiveis_ida, key="rom_ida")
            
            df_viagem = df_principal[df_principal['romaneio'] == romaneio_selecionado]
            
            if not df_viagem.empty:
                st.info(f"🚚 Motorista Associado: {df_viagem['motorista'].iloc[0]} | Quantidade de Notas: {len(df_viagem)}")
                
                st.markdown("---")
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.markdown("### 🔍 Leitura de Chaves de Acesso (XML)")
                    nf_bipada = st.text_input("Aponte o Leitor de Código de Barras:", key="txt_bipagem", placeholder="Bipa a chave de 44 dígitos...")
                    
                    if nf_bipada:
                        # Extrai os 9 dígitos da NF se for uma chave completa de 44, ou limpa o texto inserido
                        nf_limpa = str(int(nf_bipada[-9:])) if len(nf_bipada) == 44 else str(int(nf_bipada.strip()))
                        
                        if nf_limpa in df_viagem['numero_nf'].values:
                            if atualizar_status_bipagem(nf_limpa, "status_ida", "PROCESSO DE EMBARQUE OK"):
                                st.success(f"✅ NF {nf_limpa} validada e carregada no veículo com sucesso!")
                                st.rerun()
                        else:
                            st.error(f"❌ Alerta de Desvio! A NF {nf_limpa} NÃO pertence ao Romaneio {romaneio_selecionado}!")
                
                with col2:
                    st.markdown("### 📊 Status da Carga")
                    total_notas = len(df_viagem)
                    # Tratamento seguro caso a coluna 'status_ida' ainda não tenha registros
                    notas_ok = len(df_viagem[df_viagem['status_ida'] == "PROCESSO DE EMBARQUE OK"]) if 'status_ida' in df_viagem.columns else 0
                    notas_em_aguardo = total_notas - notas_ok
                    
                    st.metric("Notas Roteirizadas", total_notas)
                    st.metric("✅ Bipadas/Embarcadas", notas_ok)
                    st.metric("⏳ Aguardando Bipagem", notas_em_aguardo)
                
                st.markdown("---")
                st.subheader("📋 Grid de Conferência da Viagem")
                st.dataframe(df_viagem[["numero_nf", "cliente", "status_ida", "status_volta"]], use_container_width=True)

# ==============================================================================
# MODO: BIPAGEM - RETORNO CARGA
# ==============================================================================
elif modo_visao == "📥 Bipagem - Retorno Carga":
    st.title("📥 Prestação de Contas - Retorno de Motoristas")
    
    if df_principal.empty:
        st.warning("⚠️ Nenhuma base carregada no Supabase.")
    else:
        # --- PROTEÇÃO DO MOTOR DE BUSCA DA VOLTA ---
        valores_romaneio_volta = df_principal['romaneio'].dropna().unique() if 'romaneio' in df_principal.columns else []
        
        if len(valores_romaneio_volta) == 0:
            st.warning("📋 Nenhum romaneio ativo para retorno no banco de dados.")
        else:
            romaneios_disponiveis_ret = sorted(valores_romaneio_volta)
            romaneio_selecionado = st.selectbox("📋 Selecione o Romaneio que está retornando:", romaneios_disponiveis_ret, key="rom_ret")
            
            df_viagem = df_principal[df_principal['romaneio'] == romaneio_selecionado]
            
            if not df_viagem.empty:
                st.info(f"🚚 Motorista: {df_viagem['motorista'].iloc[0]} | Notas do Romaneio: {len(df_viagem)}")
                
                st.markdown("---")
                col_baixa, col_dev = st.columns(2)
                
                with col_baixa:
                    st.markdown("### 🟢 Baixa de Canhotos (Entregues)")
                    nf_bipada_ret = st.text_input("Aponte o Leitor (Canhoto):", key="txt_retorno", placeholder="Bipa o canhoto...")
                    
                    if nf_bipada_ret:
                        nf_limpa = str(int(nf_bipada_ret[-9:])) if len(nf_bipada_ret) == 44 else str(int(nf_bipada_ret.strip()))
                        
                        if nf_limpa in df_viagem['numero_nf'].values:
                            if atualizar_status_bipagem(nf_limpa, "status_volta", "ENTREGUE / CANHOTO OK"):
                                st.success(f"✅ Baixa confirmada para a NF {nf_limpa} no banco de dados!")
                                st.rerun()
                        else:
                            st.error(f"❌ Erro de Roteiro: NF {nf_limpa} não pertence a esta viagem!")

                with col_dev:
                    st.markdown("### 🔴 Registro de Ocorrências / Não Retorno")
                    # Protege a listagem de notas pendentes daquela viagem específica
                    notas_pendentes_volta = list(df_viagem[df_viagem['status_volta'] == "EM AGUARDO"]['numero_nf'].unique()) if 'status_volta' in df_viagem.columns else []
                    nf_problema = st.selectbox("Selecione a NF com Ocorrência:", ["-"] + notas_pendentes_volta)
                    motivo_nao_retorno = st.selectbox("Motivo do Não Retorno do Canhoto:", [
                        "🚨 DEVOLUÇÃO TOTAL", 
                        "❌ RECUSADO PELO CLIENTE", 
                        "🔄 REENTREGA SOLICITADA", 
                        "🔍 CANHOTO EM ANÁLISE"
                    ])
                    
                    if st.button("Registrar Ocorrência") and nf_problema != "-":
                        if atualizar_status_bipagem(nf_problema, "status_volta", motivo_nao_retorno):
                            nova_div_ret = [{
                                "Nota Fiscal": nf_problema,
                                "Arquivo XML": f"RETORNO_OCORRENCIA_{nf_problema}.xml",
                                "Cliente": df_viagem[df_viagem['numero_nf'] == nf_problema]['cliente'].iloc[0],
                                "Previsão Entrega": df_viagem[df_viagem['numero_nf'] == nf_problema]['previsao_entrega'].iloc[0],
                                "Status Auditoria": f"🚨 RETORNO COM ERRO ({motivo_nao_retorno.replace('🚨 ', '').replace('❌ ', '').replace('🔄 ', '').replace('🔍 ', '')})",
                                "Justificativa / Motivo": f"Problema relatado no retorno do motorista: {motivo_nao_retorno}"
                            }]
                            salvar_dados_consolidados(None, nova_div_ret)
                            st.error(f"📌 Ocorrência gravada na auditoria do Supabase para a NF {nf_problema}.")
                            st.rerun()

                st.markdown("---")
                st.subheader("📋 Controle de Entrega Física da Viagem")
                st.dataframe(df_viagem[["numero_nf", "cliente", "status_ida", "status_volta"]], use_container_width=True)

# ==============================================================================
# MODO: INJEÇÃO DE PLANILHAS (CARGA REAL NO BANCO)
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
            with st.spinner("⏳ Processando e gravando dados na nuvem..."):
                try:
                    nfs_romaneios = {}
                    romaneio_atual = "-"
                    motorista_atual = "-"
                    
                    conteudo_csv = romaneio_file.getvalue().decode("utf-8", errors="ignore").splitlines()
                    
                    for linha in conteudo_csv:
                        linha_limpa = linha.strip()
                        if not linha_limpa: continue
                        colunas = linha_limpa.split(";")

                        if colunas[0] != "" and " - " in colunas[0]:
                            romaneio_atual = colunas[0].split("-")[0].strip()
                            motorista_atual = colunas[4].strip() if len(colunas) > 4 else "-"
                            continue

                        if len(colunas) >= 11:
                            num_nf_raw = colunas[10].strip()
                            if num_nf_raw and num_nf_raw.isdigit() and num_nf_raw != "Num.NF":
                                num_nf_limpo = str(int(num_nf_raw))
                                nfs_romaneios[num_nf_limpo] = {
                                    "romaneio": romaneio_atual,
                                    "motorista": motorista_atual,
                                    "valor": float(colunas[8].replace(",", ".")) if len(colunas) > 8 and colunas[8].replace(",", ".").replace(".", "").isdigit() else 0.0
                                }

                    lista_divergencias = []
                    notas_validadas = []

                    for xml_file in xml_files:
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
                                except: pass

                            if nf_limpa in nfs_romaneios:
                                notas_validadas.append({
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

                    if salvar_dados_consolidados(notas_validadas, lista_divergencias):
                        st.success(f"📊 Sucesso! {len(notas_validadas)} Notas e {len(lista_divergencias)} Divergências integradas ao Supabase.")
                        st.rerun()
                except Exception as e:
                    st.error(f"⚠️ Erro ao salvar dados no banco de dados: {e}")

# ==============================================================================
# MODO: DIVERGÊNCIAS DE XML (LENDO DIRETAMENTE DO SUPABASE)
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
