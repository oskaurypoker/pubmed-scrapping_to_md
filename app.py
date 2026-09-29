import os
import streamlit as st
import pandas as pd
import requests
from Bio import Entrez

# --- INYECCIÓN PARA STREAMLIT CLOUD ---
# Esto asegura que el navegador se descargue al encender el servidor.
# st.cache_resource evita que se ejecute cada vez que el usuario hace clic.
@st.cache_resource
def install_playwright():
    os.system("playwright install chromium")

install_playwright()
# --------------------------------------

# 1. Configuración inicial de Streamlit
st.set_page_config(page_title="Procesador Médico", layout="wide")
st.title("Procesador de Literatura Médica")

tabs = st.tabs(["Fase 1: Búsqueda", "Fase 2: Descargas", "Fase 3: Markdown"])

def get_evidence_level(pub_types):
    """Mapea tipos de publicación a Nivel de Evidencia (1=Más alto, 5=Más bajo)"""
    types = [str(pt).lower() for pt in pub_types]
    if any("meta-analysis" in t or "systematic review" in t for t in types):
        return 1
    elif any("randomized controlled trial" in t for t in types):
        return 2
    elif any("cohort" in t for t in types):
        return 3
    elif any("case-control" in t for t in types):
        return 4
    return 5

def check_unpaywall(doi, email):
    """Consulta Unpaywall para verificar acceso abierto y obtener link al PDF"""
    if not doi:
        return False, None
    try:
        url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            is_oa = data.get("is_oa", False)
            pdf_url = data.get("best_oa_location", {}).get("url_for_pdf") if is_oa else None
            return is_oa, pdf_url
    except Exception:
        pass
    return False, None

# 2. Pestaña de Búsqueda (Fase 1)
with tabs[0]:
    st.header("Búsqueda en PubMed")
    
    with st.form("search_form"):
        query = st.text_input("Query de PubMed", value="Anterior Cruciate Ligament Reconstruction[MeSH]")
        email = st.text_input("Correo electrónico (Requerido por APIs)")
        min_evidence = st.slider("Nivel de Evidencia Mínimo (1=Meta-análisis, 5=Reportes de caso)", 1, 5, 5)
        submit = st.form_submit_button("Buscar Artículos")

    if submit:
        if not query or not email:
            st.error("Por favor, completa el query y el correo electrónico.")
        else:
            with st.spinner("Conectando con PubMed..."):
                Entrez.email = email
                try:
                    handle = Entrez.esearch(db="pubmed", term=query, retmax=50)
                    record = Entrez.read(handle)
                    handle.close()
                    pmids = record["IdList"]

                    if not pmids:
                        st.warning("No se encontraron resultados.")
                    else:
                        fetch_handle = Entrez.efetch(db="pubmed", id=",".join(pmids), retmode="xml")
                        articles = Entrez.read(fetch_handle)
                        fetch_handle.close()

                        results = []
                        for article in articles.get('PubmedArticle', []):
                            medline = article['MedlineCitation']
                            article_data = medline['Article']

                            pmid = str(medline['PMID'])
                            title = article_data.get('ArticleTitle', 'Sin título')
                            year = article_data.get('Journal', {}).get('JournalIssue', {}).get('PubDate', {}).get('Year', 'N/A')
                            
                            authors = article_data.get('AuthorList', [])
                            first_author = f"{authors[0].get('LastName', '')} {authors[0].get('Initials', '')}" if authors else "N/A"

                            doi = ""
                            for a_id in article.get('PubmedData', {}).get('ArticleIdList', []):
                                if a_id.attributes.get('IdType') == 'doi':
                                    doi = str(a_id)
                                    break

                            ev_level = get_evidence_level(article_data.get('PublicationTypeList', []))

                            if ev_level <= min_evidence:
                                is_oa, pdf_url = check_unpaywall(doi, email)
                                results.append({
                                    "PMID": pmid,
                                    "DOI": doi,
                                    "Título": title,
                                    "Año": year,
                                    "Primer Autor": first_author,
                                    "Nivel Evidencia": ev_level,
                                    "Open Access": "Sí" if is_oa else "No",
                                    "PDF URL": pdf_url if pdf_url else "N/A"
                                })

                        if results:
                            df = pd.DataFrame(results)
                            st.dataframe(df, use_container_width=True)

                            csv = df.to_csv(index=False).encode('utf-8')
                            st.download_button(
                                label="Descargar Tabla (CSV)",
                                data=csv,
                                file_name="pubmed_resultados.csv",
                                mime="text/csv"
                            )
                        else:
                            st.warning("Los resultados no cumplen con el nivel de evidencia filtrado.")

                except Exception as e:
                    st.error(f"Error de conexión: {e}")

# 3. Pestañas en Desarrollo
with tabs[1]:
    st.info("En desarrollo...")

with tabs[2]:
    st.info("En desarrollo...")
