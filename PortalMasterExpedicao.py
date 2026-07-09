# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import os

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Master Expedição - Painel Central",
    page_icon="🚚",
    layout="wide"
)

# --- SIMULAÇÃO DO BANCO DE DADOS (SUPABASE PRE-ADAPTADO) ---
# Amanhã, estas funções farão o `st.connection("supabase")` ou `supabase.table().insert()`
if 'bd_simulado' not in st.session_state:
    st.session_state['bd_simulado'] = pd.DataFrame(columns=[
        "numero_nf", "romaneio", "cliente", "valor_nota", "data_emissao", "previsao_entrega", "status_ida",
        "status_volta"
    ])

if 'divergencias_simuladas' not in st.session_state:
    st.session_state['divergencias_simuladas'] = pd.DataFrame(columns=[
        "Arquivo XML", "Nota Fiscal", "Cliente", "Previsão Entrega", "Status Auditoria"
    ])


def salvar_nota_no_banco(dados_lista):
    """ Envia a lista de dicionários direto para o banco de dados """
    df_novos = pd.DataFrame(dados_lista)
    # Simulação: Substitui/Adiciona no estado da sessão
    st.session_state['bd_simulado'] = pd.concat([st.session_state['bd_simulado'], df_novos]).drop_duplicates(
        subset=['numero_nf'], keep='last')


def salvar_divergencias_no_banco(df_div):
    """ Atualiza a tabela de divergências/órfãs na nuvem """
    st.session_state['divergencias_simuladas'] = df_div


# --- BARRA LATERAL: NAVEGAÇÃO & INJEÇÃO DE DADOS ---
st.sidebar.title("🚚 Controle de Logística")
st.sidebar.markdown("---")
modo_visao = st.sidebar.radio(
    "Selecione o Painel:",
    ["📊 Dashboard Geral", "📥 Injeção Automatizada (Doca)", "🚨 Divergências de XML"]
)

st.sidebar.markdown("---")
st.sidebar.info(
    "💡 Dica: Na sexta-feira, use a aba 'Injeção Automatizada' para carregar os arquivos gerados pela expedição.")

# ==============================================================================
# MODO: INJEÇÃO AUTOMATIZADA (O CORAÇÃO DA AUTOMAÇÃO DIRETO NO SITE)
# ==============================================================================
if modo_visao == "📥 Injeção Automatizada (Doca)":
    st.title("📥 Central de Injeção de Dados Automatizada")
    st.subheader("Faça o upload dos arquivos da doca para atualizar o painel público")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 1. Base de Romaneios")
        romaneio_file = st.file_uploader("Arraste o Romaneios.csv aqui", type=["csv"])

    with col2:
        st.markdown("### 2. Notas Fiscais (Físicas)")
        xml_files = st.file_uploader("Arraste todos os arquivos .XML da pasta aqui", type=["xml"],
                                     accept_multiple_files=True)

    if st.button("🚀 Processar Cruzamento e Injetar no Painel", use_container_width=True):
        if not romaneio_file:
            st.error("❌ Por favor, insira o arquivo Romaneios.csv para iniciar.")
        elif not xml_files:
            st.error("❌ Por favor, selecione ao menos um arquivo XML para cruzamento.")
        else:
            with st.spinner("⏳ Processando dados e realizando auditoria jurídica de chaves..."):
                try:
                    # 1. Processando o CSV de Romaneios na memória
                    nfs_romaneios = {}
                    romaneio_atual = "-"
                    motorista_atual = "-"

                    # Lendo o arquivo enviado como texto
                    conteudo_csv = romaneio_file.getvalue().decode("utf-8", errors="ignore").splitlines()

                    for linha in conteudo_csv:
                        linha_limpa = linha.strip()
                        if not linha_limpa:
                            continue
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
                                    "cliente": colunas[3].strip() if len(colunas) > 3 else "Não Identificado",
                                    # Se houver valor na planilha, captura (Exemplo: coluna 8)
                                    "valor": float(colunas[8].replace(",", ".")) if len(colunas) > 8 and colunas[
                                        8].replace(",", ".").replace(".", "").isdigit() else 0.0
                                }

                    # 2. Processando os XMLs enviados na memória
                    lista_auditoria = []
                    notas_para_banco = []

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

                            # Tratamento da data de previsão baseada na emissão
                            data_previsao_xml = "-"
                            data_emissao_str = "-"
                            if dhEmi_xml is not None and dhEmi_xml.text:
                                try:
                                    data_iso = dhEmi_xml.text.split("T")[0]
                                    data_obj = datetime.strptime(data_iso, "%Y-%m-%d")
                                    data_emissao_str = data_obj.strftime("%d/%m/%Y")
                                    # Regra de Projeção logística padrão: +2 dias
                                    previsao_calculada = data_obj + timedelta(days=2)
                                    data_previsao_xml = previsao_calculada.strftime("%d/%m/%Y")
                                except:
                                    pass

                            # Cruzamento analítico
                            if nf_limpa in nfs_romaneios:
                                status_cruzamento = "VINCULADA OK"
                                romaneio_banco = nfs_romaneios[nf_limpa]["romaneio"]
                                # Alimenta a lista que vai para a base principal
                                notas_para_banco.append({
                                    "numero_nf": nf_limpa,
                                    "romaneio": romaneio_banco,
                                    "cliente": nome_cliente,
                                    "valor_nota": valor_nota if valor_nota > 0 else nfs_romaneios[nf_limpa]["valor"],
                                    "data_emissao": data_emissao_str,
                                    "previsao_entrega": data_previsao_xml,
                                    "status_ida": "EM ROTA",
                                    "status_volta": "PENDENTE"
                                })
                            else:
                                status_cruzamento = "🚨 FORA DO ROMANEIO (ÓRFÃ)"
                                romaneio_banco = "-"

                                # Adiciona na lista de divergências
                                lista_auditoria.append({
                                    "Arquivo XML": xml_file.name,
                                    "Nota Fiscal": nf_limpa,
                                    "Cliente": nome_cliente,
                                    "Previsão Entrega": data_previsao_xml,
                                    "Status Auditoria": status_cruzamento
                                })

                    # 3. Injetando os dados processados nos destinos corretos
                    if notas_para_banco:
                        salvar_nota_no_banco(notas_para_banco)

                    df_divergencias = pd.DataFrame(lista_auditoria)
                    salvar_divergencias_no_banco(df_divergencias)

                    st.success(
                        f"✅ Sucesso! {len(notas_para_banco)} Notas vinculadas atualizadas e {len(lista_auditoria)} Divergências mapeadas em nuvem!")

                except Exception as e:
                    st.error(f"⚠️ Falha estrutural no processamento: {e}")

# ==============================================================================
# MODO: DASHBOARD GERAL
# ==============================================================================
elif modo_visao == "📊 Dashboard Geral":
    st.title("📊 Painel Central de Controle de Entregas")

    df_principal = st.session_state['bd_simulado']

    # Indicadores KPI superiores
    st.subheader("📈 Indicadores Operacionais da Doca")
    kpi1, kpi2, kpi3 = st.columns(3)

    total_notas = len(df_principal)
    financeiro_total = df_principal["valor_nota"].sum() if total_notas > 0 else 0.0
    total_orfas = len(st.session_state['divergencias_simuladas'])

    kpi1.metric("Volume de Notas Ativas", f"{total_notas} NFs")
    kpi2.metric("Faturamento Roteirizado",
                f"R$ {financeiro_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    kpi3.metric("Alertas de Divergência", f"{total_orfas} XMLs Soltos",
                delta="- ocorrências" if total_orfas == 0 else "Atenção necessária", delta_color="inverse")

    st.markdown("---")
    st.subheader("📋 Visão Consolidada de Notas em Trânsito")

    if df_principal.empty:
        st.info("ℹ️ Aguardando primeira injeção de dados para exibir a malha de transporte.")
    else:
        st.dataframe(df_principal, use_container_width=True)

# ==============================================================================
# MODO: DIVERGÊNCIAS DE XML (A FAMOSA TABELA AMARELA)
# ==============================================================================
elif modo_visao == "🚨 Divergências de XML":
    st.title("🚨 Auditoria Fiscal de XMLs Órfãos")
    st.subheader("Notas localizadas fisicamente na pasta de XMLs que não foram associadas a nenhum Romaneio")

    df_div = st.session_state['divergencias_simuladas']

    if df_div.empty:
        st.success(
            "✅ Perfeito! Nenhum arquivo de divergência encontrado na nuvem. Todos os XMLs possuem amarração jurídica com os romaneios!")
    else:
        st.warning(
            f"Atenção: Foram localizadas {len(df_div)} notas fiscais fora do romaneio logístico. Ação de checagem exigida.")

        # Exibição organizada com a coluna "Previsão Entrega" integrada na tabela amarela
        colunas_exibicao = ["Arquivo XML", "Nota Fiscal", "Cliente", "Previsão Entrega", "Status Auditoria"]
        st.dataframe(df_div[colunas_exibicao], use_container_width=True)