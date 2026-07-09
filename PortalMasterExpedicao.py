# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Master Expedição - Painel Central",
    page_icon="🚚",
    layout="wide"
)

# --- SIMULAÇÃO DO BANCO DE DADOS (PRONTO PARA SUPABASE) ---
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
    df_novos = pd.DataFrame(dados_lista)
    st.session_state['bd_simulado'] = pd.concat([st.session_state['bd_simulado'], df_novos]).drop_duplicates(
        subset=['numero_nf'], keep='last')


def atualizar_status_bipagem(numero_nf, coluna_status, novo_status):
    df = st.session_state['bd_simulado']
    if numero_nf in df['numero_nf'].values:
        df.loc[df['numero_nf'] == numero_nf, coluna_status] = novo_status
        st.session_state['bd_simulado'] = df
        return True
    return False


# --- BARRA LATERAL: NAVEGAÇÃO COMPLETA RENOVAVA ---
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

st.sidebar.markdown("---")
st.sidebar.info("💡 Pronto para o leitor de código de barras: clique no campo de texto e bipa a nota fiscal.")

# ==============================================================================
# MODO: DASHBOARD GERAL
# ==============================================================================
if modo_visao == "📊 Dashboard Geral":
    st.title("📊 Painel Central de Controle de Entregas")

    df_principal = st.session_state['bd_simulado']

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
        st.info("ℹ️ Aguardando primeira injeção de dados ou bipagem para exibir a malha de transporte.")
    else:
        st.dataframe(df_principal, use_container_width=True)

# ==============================================================================
# MODO: BIPAGEM - SAÍDA EXPEDIÇÃO (RETORNADO)
# ==============================================================================
elif modo_visao == "📤 Bipagem - Saída Expedição":
    st.title("📤 Bipagem de Saída - Fluxo de Expedição")
    st.subheader("Bipa a nota fiscal física no momento em que ela entra na gaiola/caminhão")

    # Campo otimizado para o leitor de código de barras bipa direto
    nf_bipada_saida = st.text_input("Aponte o Leitor para o Código de Barras (Chave/NF):", key="bip_saida",
                                    placeholder="Bipa o código aqui...")

    if nf_bipada_saida:
        # Extrai os números finais se for uma chave completa de 44 dígitos
        nf_limpa = str(int(nf_bipada_saida[-9:])) if len(nf_bipada_saida) == 44 else str(int(nf_bipada_saida.strip()))

        sucesso = atualizar_status_bipagem(nf_limpa, "status_ida", "CONFERIDO / EXPEDIDO")
        if sucesso:
            st.success(f"✅ Nota Fiscal nº {nf_limpa} alterada para **CONFERIDO / EXPEDIDO** com sucesso!")
        else:
            st.warning(
                f"⚠️ Atenção: A NF {nf_limpa} foi bipada, mas não consta na base de romaneios atual. Verifique na aba de Divergências.")

    st.markdown("---")
    st.subheader("📋 Status da Expedição Atual")
    st.dataframe(st.session_state['bd_simulado'][["numero_nf", "romaneio", "cliente", "status_ida"]],
                 use_container_width=True)

# ==============================================================================
# MODO: BIPAGEM - RETORNO CARGA (RETORNADO)
# ==============================================================================
elif modo_visao == "📥 Bipagem - Retorno Carga":
    st.title("📥 Bipagem de Retorno - Prestação de Contas")
    st.subheader("Bipa o canhoto ou a nota no retorno do motorista para validar a entrega física")

    nf_bipada_retorno = st.text_input("Aponte o Leitor para o Código de Barras (Retorno):", key="bip_retorno",
                                      placeholder="Bipa o código do canhoto aqui...")

    if nf_bipada_retorno:
        nf_limpa = str(int(nf_bipada_retorno[-9:])) if len(nf_bipada_retorno) == 44 else str(
            int(nf_bipada_retorno.strip()))

        sucesso = atualizar_status_bipagem(nf_limpa, "status_volta", "ENTREGUE / CANHOTO OK")
        if sucesso:
            st.success(f"✅ Recebimento da NF nº {nf_limpa} confirmado: **ENTREGUE / CANHOTO OK**!")
        else:
            st.error(f"❌ Erro: NF {nf_limpa} não foi localizada no sistema para baixa de retorno.")

    st.markdown("---")
    st.subheader("📋 Status de Retorno dos Canhotos")
    st.dataframe(st.session_state['bd_simulado'][["numero_nf", "romaneio", "cliente", "status_volta"]],
                 use_container_width=True)

# ==============================================================================
# MODO: INJEÇÃO DE PLANILHAS (CARGA REORGANIZADA)
# ==============================================================================
elif modo_visao == "⚙️ Injeção de Planilhas (Carga)":
    st.title("⚙️ Painel de Carga e Cruzamento de Dados")
    st.subheader("Alimente a inteligência do sistema com os dados diários do faturamento")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 1. Base de Romaneios")
        romaneio_file = st.file_uploader("Arraste o Romaneios.csv aqui", type=["csv"])
    with col2:
        st.markdown("### 2. Notas Fiscais (Físicas)")
        xml_files = st.file_uploader("Arraste todos os arquivos .XML aqui", type=["xml"], accept_multiple_files=True)

    if st.button("🚀 Processar e Sincronizar Tudo", use_container_width=True):
        if not romaneio_file or not xml_files:
            st.error("❌ É obrigatório carregar tanto o Romaneios.csv quanto os XMLs para o cruzamento logístico.")
        else:
            with st.spinner("⏳ Cruzando dados operacionais..."):
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
                                    "cliente": colunas[3].strip() if len(colunas) > 3 else "Não Identificado",
                                    "valor": float(colunas[8].replace(",", ".")) if len(colunas) > 8 and colunas[
                                        8].replace(",", ".").replace(".", "").isdigit() else 0.0
                                }

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

                            data_previsao_xml = "-"
                            data_emissao_str = "-"
                            if dhEmi_xml is not None and dhEmi_xml.text:
                                try:
                                    data_iso = dhEmi_xml.text.split("T")[0]
                                    data_obj = datetime.strptime(data_iso, "%Y-%m-%d")
                                    data_emissao_str = data_obj.strftime("%d/%m/%Y")
                                    previsao_calculada = data_obj + timedelta(days=2)
                                    data_previsao_xml = previsao_calculada.strftime("%d/%m/%Y")
                                except:
                                    pass

                            if nf_limpa in nfs_romaneios:
                                romaneio_banco = nfs_romaneios[nf_limpa]["romaneio"]
                                notas_para_banco.append({
                                    "numero_nf": nf_limpa,
                                    "romaneio": romaneio_banco,
                                    "cliente": nome_cliente,
                                    "valor_nota": valor_nota if valor_nota > 0 else nfs_romaneios[nf_limpa]["valor"],
                                    "data_emissao": data_emissao_str,
                                    "previsao_entrega": data_previsao_xml,
                                    "status_ida": "PENDENTE DE BIPAGEM",
                                    "status_volta": "EM AGUARDO"
                                })
                            else:
                                lista_auditoria.append({
                                    "Arquivo XML": xml_file.name,
                                    "Nota Fiscal": nf_limpa,
                                    "Cliente": nome_cliente,
                                    "Previsão Entrega": data_previsao_xml,
                                    "Status Auditoria": "🚨 FORA DO ROMANEIO (ÓRFÃ)"
                                })

                    if notas_para_banco: salvar_nota_no_banco(notas_para_banco)
                    salvar_divergencias_no_banco(pd.DataFrame(lista_auditoria))
                    st.success("✅ Cruzamento executado! Telas de conferência atualizadas.")
                except Exception as e:
                    st.error(f"⚠️ Falha no processamento: {e}")

# ==============================================================================
# MODO: DIVERGÊNCIAS DE XML (A FAMOSA TABELA AMARELA)
# ==============================================================================
elif modo_visao == "🚨 Divergências de XML":
    st.title("🚨 Auditoria Fiscal de XMLs Órfãos")
    st.subheader("Notas localizadas fisicamente que não possuem correspondência nos romaneios logísticos")

    df_div = st.session_state['divergencias_simuladas']

    if df_div.empty:
        st.success("✅ Perfeito! Nenhum arquivo de divergência encontrado.")
    else:
        st.warning(f"Atenção: Existem {len(df_div)} notas fiscais órfãs necessitando de verificação de doca.")
        st.dataframe(df_div[["Arquivo XML", "Nota Fiscal", "Cliente", "Previsão Entrega", "Status Auditoria"]],
                     use_container_width=True)