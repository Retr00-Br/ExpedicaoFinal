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

# --- ESTADO DA SESSÃO (BANCO DE DADOS EM MEMÓRIA PARA TESTES) ---
if 'bd_simulado' not in st.session_state:
    st.session_state['bd_simulado'] = pd.DataFrame(columns=[
        "numero_nf", "romaneio", "motorista", "cliente", "valor_nota", "data_emissao", "previsao_entrega", "status_ida",
        "status_volta"
    ])

if 'divergencias_simuladas' not in st.session_state:
    st.session_state['divergencias_simuladas'] = pd.DataFrame(columns=[
        "Arquivo XML", "Nota Fiscal", "Cliente", "Previsão Entrega", "Status Auditoria", "Justificativa / Motivo"
    ])


# --- FUNÇÕES DE MANIPULAÇÃO DO BANCO ---
def salvar_dados_consolidados(dados_notas, dados_divergencias):
    if dados_notas:
        df_novos = pd.DataFrame(dados_notas)
        st.session_state['bd_simulado'] = pd.concat([st.session_state['bd_simulado'], df_novos]).drop_duplicates(
            subset=['numero_nf'], keep='last')
    if dados_divergencias:
        df_div_novos = pd.DataFrame(dados_divergencias)
        st.session_state['divergencias_simuladas'] = pd.concat(
            [st.session_state['divergencias_simuladas'], df_div_novos]).drop_duplicates(subset=['Nota Fiscal'],
                                                                                        keep='last')


def atualizar_status_bipagem(numero_nf, coluna_status, novo_status):
    df = st.session_state['bd_simulado']
    if numero_nf in df['numero_nf'].values:
        df.loc[df['numero_nf'] == numero_nf, coluna_status] = novo_status
        st.session_state['bd_simulado'] = df
        return True
    return False


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

    df_principal = st.session_state['bd_simulado']

    st.subheader("📈 Indicadores Operacionais da Doca")
    kpi1, kpi2, kpi3 = st.columns(3)

    total_notas = len(df_principal)
    financeiro_total = df_principal["valor_nota"].sum() if total_notas > 0 else 0.0
    total_orfas = len(st.session_state['divergencias_simuladas'])

    kpi1.metric("Volume de Notas Ativas", f"{total_notas} NFs")
    kpi2.metric("Faturamento Roteirizado",
                f"R$ {financeiro_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    kpi3.metric("Alertas de Divergência", f"{total_orfas} Ocorrências")

    st.markdown("---")
    st.subheader("📋 Visão Consolidada de Notas Cruzadas (XML 🔄 Romaneio)")

    if df_principal.empty:
        st.info("ℹ️ Sistema vazio. Realize a carga dos arquivos na aba de configurações.")
    else:
        st.dataframe(df_principal, use_container_width=True)

# ==============================================================================
# MODO: BIPAGEM - SAÍDA EXPEDIÇÃO (COM IDA PARCIAL E ENVIO DIRETO PARA DIVERGÊNCIAS)
# ==============================================================================
elif modo_visao == "📤 Bipagem - Saída Expedição":
    st.title("📤 Fluxo de Expedição - Saída de Veículos")

    df_principal = st.session_state['bd_simulado']

    if df_principal.empty:
        st.warning("⚠️ Nenhuma base carregada. Importe o Romaneio primeiro para selecionar as viagens.")
    else:
        romaneios_disponiveis = df_principal['romaneio'].unique()
        romaneio_selecionado = st.selectbox("📋 Selecione o Romaneio para conferência:", romaneios_disponiveis)

        df_viagem = df_principal[df_principal['romaneio'] == romaneio_selecionado]
        st.info(f"🚚 Motorista Associado: {df_viagem['motorista'].iloc[0]} | Quantidade de Notas: {len(df_viagem)}")

        st.markdown("---")
        col_bip, col_ret = st.columns(2)

        with col_bip:
            st.markdown("### 🟢 Bipagem de Fluxo Normal")
            nf_bipada = st.text_input("Aponte o Leitor (Código de Barras):", key="txt_saida",
                                      placeholder="Bipa a NF aqui...")

            if nf_bipada:
                nf_limpa = str(int(nf_bipada[-9:])) if len(nf_bipada) == 44 else str(int(nf_bipada.strip()))

                if nf_limpa in df_viagem['numero_nf'].values:
                    atualizar_status_bipagem(nf_limpa, "status_ida", "CONFERIDO / EXPEDIDO")
                    st.success(f"✅ NF {nf_limpa} liberada para viagem!")
                else:
                    st.error(f"❌ Erro de Validação: A NF {nf_limpa} NÃO pertence ao Romaneio {romaneio_selecionado}!")

        with col_ret:
            st.markdown("### 🔴 Tratamento de Notas Não Enviadas")
            # Lista apenas as notas que ainda não foram bipadas como OK nesta viagem
            nf_retida = st.selectbox("Selecione a NF Retida:", ["-"] + list(
                df_viagem[df_viagem['status_ida'] == "PENDENTE DE BIPAGEM"]['numero_nf'].unique()))

            # ADICIONADO: Opção de "Ida Parcial" incluída nos motivos solicitados
            motivo_nao_ir = st.selectbox("Motivo da Nota não seguir viagem:",
                                         ["Falta de material", "Nota não realizada", "Nota perdida", "Ida Parcial"])

            if st.button("Gravar Retenção de Saída") and nf_retida != "-":
                atualizar_status_bipagem(nf_retida, "status_ida", f"RETIDA: {motivo_nao_ir}")

                # MODIFICAÇÃO: Joga direto com toda a justificativa detalhada no painel de divergências
                nova_div = {
                    "Arquivo XML": f"RETENCAO_SAIDA_{nf_retida}.xml",
                    "Nota Fiscal": nf_retida,
                    "Cliente": df_viagem[df_viagem['numero_nf'] == nf_retida]['cliente'].iloc[0],
                    "Previsão Entrega": df_viagem[df_viagem['numero_nf'] == nf_retida]['previsao_entrega'].iloc[0],
                    "Status Auditoria": f"🚨 EXPEDIÇÃO RECUSADA ({motivo_nao_ir.upper()})",
                    "Justificativa / Motivo": f"Nota retida na doca de saída por motivo de: {motivo_nao_ir}"
                }
                st.session_state['divergencias_simuladas'] = pd.concat([
                    st.session_state['divergencias_simuladas'], pd.DataFrame([nova_div])
                ]).drop_duplicates(subset=['Nota Fiscal'], keep='last')
                st.warning(
                    f"📌 Alerta: NF {nf_retida} removida do fluxo normal e enviada para análise no Painel de Divergências.")

        st.markdown("---")
        st.subheader("📋 Grid de Conferência da Viagem")
        st.dataframe(
            st.session_state['bd_simulado'][st.session_state['bd_simulado']['romaneio'] == romaneio_selecionado][
                ["numero_nf", "cliente", "valor_nota", "status_ida"]], use_container_width=True)

# ==============================================================================
# MODO: BIPAGEM - RETORNO CARGA
# ==============================================================================
elif modo_visao == "📥 Bipagem - Retorno Carga":
    st.title("📥 Prestação de Contas - Retorno de Motoristas")

    df_principal = st.session_state['bd_simulado']

    if df_principal.empty:
        st.warning("⚠️ Nenhuma base ativa no sistema.")
    else:
        romaneios_disponiveis = df_principal['romaneio'].unique()
        romaneio_selecionado = st.selectbox("📋 Selecione o Romaneio que está retornando:", romaneios_disponiveis,
                                            key="rom_ret")

        df_viagem = df_principal[df_principal['romaneio'] == romaneio_selecionado]
        st.info(f"🚚 Motorista: {df_viagem['motorista'].iloc[0]} | Notas do Romaneio: {len(df_viagem)}")

        st.markdown("---")
        col_baixa, col_dev = st.columns(2)

        with col_baixa:
            st.markdown("### 🟢 Baixa de Canhotos (Entregues)")
            nf_bipada_ret = st.text_input("Aponte o Leitor (Canhoto):", key="txt_retorno",
                                          placeholder="Bipa o canhoto...")

            if nf_bipada_ret:
                nf_limpa = str(int(nf_bipada_ret[-9:])) if len(nf_bipada_ret) == 44 else str(int(nf_bipada_ret.strip()))

                if nf_limpa in df_viagem['numero_nf'].values:
                    atualizar_status_bipagem(nf_limpa, "status_volta", "ENTREGUE / CANHOTO OK")
                    st.success(f"✅ Baixa confirmada para a NF {nf_limpa}!")
                else:
                    st.error(f"❌ Erro de Roteiro: NF {nf_limpa} não pertence a esta viagem!")

        with col_dev:
            st.markdown("### 🔴 Registro de Ocorrências / Não Retorno")
            nf_problema = st.selectbox("Selecione a NF com Ocorrência:", ["-"] + list(
                df_viagem[df_viagem['status_volta'] == "EM AGUARDO"]['numero_nf'].unique()))
            motivo_nao_retorno = st.selectbox("Motivo do Não Retorno do Canhoto:", [
                "🚨 DEVOLUÇÃO TOTAL",
                "❌ RECUSADO PELO CLIENTE",
                "🔄 REENTREGA SOLICITADA",
                "🔍 CANHOTO EM ANÁLISE"
            ])

            if st.button("Registrar Ocorrência") and nf_problema != "-":
                atualizar_status_bipagem(nf_problema, "status_volta", motivo_nao_retorno)

                # MODIFICAÇÃO: Joga a ocorrência detalhada direto no painel de divergências
                nova_div_ret = {
                    "Arquivo XML": f"RETORNO_OCORRENCIA_{nf_problema}.xml",
                    "Nota Fiscal": nf_problema,
                    "Cliente": df_viagem[df_viagem['numero_nf'] == nf_problema]['cliente'].iloc[0],
                    "Previsão Entrega": df_viagem[df_viagem['numero_nf'] == nf_problema]['previsao_entrega'].iloc[0],
                    "Status Auditoria": f"🚨 RETORNO COM ERRO ({motivo_nao_retorno.replace('🚨 ', '').replace('❌ ', '').replace('🔄 ', '').replace('🔍 ', '')})",
                    "Justificativa / Motivo": f"Problema relatado no retorno do motorista: {motivo_nao_retorno}"
                }
                st.session_state['divergencias_simuladas'] = pd.concat([
                    st.session_state['divergencias_simuladas'], pd.DataFrame([nova_div_ret])
                ]).drop_duplicates(subset=['Nota Fiscal'], keep='last')
                st.error(f"📌 Ocorrência enviada para a central de auditoria na aba de Divergências.")

        st.markdown("---")
        st.subheader("📋 Controle de Entrega Física da Viagem")
        st.dataframe(
            st.session_state['bd_simulado'][st.session_state['bd_simulado']['romaneio'] == romaneio_selecionado][
                ["numero_nf", "cliente", "status_ida", "status_volta"]], use_container_width=True)

# ==============================================================================
# MODO: INJEÇÃO DE PLANILHAS
# ==============================================================================
elif modo_visao == "⚙️ Injeção de Planilhas (Carga)":
    st.title("⚙️ Painel de Carga e Cruzamento de Dados")
    st.subheader("Alimente o sistema realizando a conferência automática")

    col1, col2 = st.columns(2)
    with col1:
        romaneio_file = st.file_uploader("1. Carregar Romaneios.csv", type=["csv"])
    with col2:
        xml_files = st.file_uploader("2. Selecionar Arquivos XML", type=["xml"], accept_multiple_files=True)

    if st.button("🚀 Processar e Validar Dados", use_container_width=True):
        if not romaneio_file or not xml_files:
            st.error("❌ Carregue ambos os arquivos para executar a amarração.")
        else:
            with st.spinner("⏳ Rodando validação e cruzamento logístico..."):
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
                                    "valor": float(colunas[8].replace(",", ".")) if len(colunas) > 8 and colunas[
                                        8].replace(",", ".").replace(".", "").isdigit() else 0.0
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
                                except:
                                    pass

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
                                    "Status Auditoria": "🚨 FORA DO ROMANEIO (OÓRFÃ)",
                                    "Justificativa / Motivo": "🗺️ Erro de Roteirização (Faturado sem Viagem)"
                                })

                    salvar_dados_consolidados(notas_validadas, lista_divergencias)
                    st.success(
                        f"📊 Banco alimentado com {len(notas_validadas)} Notas e {len(lista_divergencias)} Divergências fiscais encontradas.")
                except Exception as e:
                    st.error(f"⚠️ Erro estrutural: {e}")

# ==============================================================================
# MODO: DIVERGÊNCIAS DE XML (CENTRALIZANDO TODAS AS JUSTIFICATIVAS DO SISTEMA)
# ==============================================================================
elif modo_visao == "🚨 Divergências de XML":
    st.title("🚨 Central Única de Auditoria e Divergências")
    st.subheader(
        "Todas as ocorrências registradas na Saída, no Retorno ou erros de Roteirização concentrados para análise")

    df_div = st.session_state['divergencias_simuladas']

    if df_div.empty:
        st.success("✅ Excelente! Nenhuma divergência operacional ou nota retida na base até o momento.")
    else:
        st.warning(f"Atenção: Constam {len(df_div)} registros pendentes de tratativa ou justificativa fiscal.")
        st.dataframe(df_div[[
            "Arquivo XML", "Nota Fiscal", "Cliente", "Previsão Entrega", "Status Auditoria", "Justificativa / Motivo"
        ]], use_container_width=True)