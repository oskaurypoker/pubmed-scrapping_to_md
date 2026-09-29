import os
import streamlit as st
import pandas as pd
import requests
from Bio import Entrez
from datetime import datetime

# --- INYECCIÓN PARA STREAMLIT CLOUD ---
@st.cache_resource
def install_playwright():
    os.system("playwright install chromium")

install_playwright()
# --------------------------------------

st.set_page_config(page_title="Procesador Médico", layout="wide")
st.title("Procesador de Literatura Médica")

tabs = st.tabs(["Fase 1: Búsqueda", "Fase 2: Descargas", "Fase 3: Markdown"])

def get_evidence_level(pub_types):
    types = [str(pt).lower() for pt in pub_types]
    if any("meta-analysis" in t or "systematic review" in t for t in types): return 1
    elif any("randomized controlled trial" in t for t in types): return 2
    elif any("cohort" in t for t in types): return 3
    elif any("case-control" in t for t in types): return 4
    return 5

def check_unpaywall(doi, email):
    if not doi: return False, None
    try:
        url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            is_oa = data.get("is_oa", False)
            return is_oa, data.get("best_oa_location", {}).get("url_for_pdf") if is_oa else None
    except: pass
    return False, None

with tabs[0]:
    st.header("Búsqueda Avanzada en PubMed")
    
    with st.form("search_form"):
        col1, col2 = st.columns(2)
        with col1:
            query = st.text_input("Query de PubMed", value="Anterior Cruciate Ligament Reconstruction[MeSH]")
            email = st.text_input("Correo electrónico", value="tu_correo@ejemplo.com")
            free_only = st.checkbox("Solo artículos Free Full Text", value=False)
        
        with col2:
            current_year = datetime.now().year
            year_range = st.slider("Rango de Publicación", 2000, current_year, (current_year-5, current_year))
            max_results = st.number_input("Artículos a extraer (Retmax)", min_value=10, max_value=500, value=100, step=10)
            min_evidence = st.slider("Nivel Evidencia Mínimo (1=Meta-análisis, 5=Todos)", 1, 5, 5)
            
        submit = st.form_submit_button("Ejecutar Búsqueda")

    if submit:
        if not query or not email or email == "tu_correo@ejemplo.com":
            st.error("Por favor, ingresa un query válido y tu correo electrónico real.")
        else:
            with st.spinner("Consultando NCBI E-utilities..."):
                Entrez.email = email
                try:
                    # Ensamblaje del query con filtros
                    final_query = query
                    if free_only:
                        final_query += ' AND "loattrfree full text"[sb]'

                    # E-search con parámetros de fecha y límite
                    handle = Entrez.esearch(
                        db="pubmed", 
                        term=final_query, 
                        retmax=max_results,
                        mindate=str(year_range[0]),
                        maxdate=str(year_range[1]),
                        datetype="pdat"
                    )
                    record = Entrez.read(handle)
                    handle.close()
                    pmids = record["IdList"]

                    if not pmids:
                        st.warning("No se encontraron resultados con estos filtros.")
                    else:
                        st.info(f"Se identificaron {len(pmids)} PMIDs. Extrayendo metadatos...")
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

                            doi = next((str(a_id) for a_id in article.get('PubmedData', {}).get('ArticleIdList', []) if a_id.attributes.get('IdType') == 'doi'), "")
                            ev_level = get_evidence_level(article_data.get('PublicationTypeList', []))

                            if ev_level <= min_evidence:
                                is_oa, pdf_url = check_unpaywall(doi, email)
                                results.append({
                                    "PMID": pmid,
                                    "DOI": doi,
                                    "Título": title,
                                    "Año": year,
                                    "Autor": first_author,
                                    "Nivel": ev_level,
                                    "Open Access": "Sí" if is_oa or free_only else "No",
                                    "PDF URL": pdf_url if pdf_url else "N/A"
                                })

                        if results:
                            df = pd.DataFrame(results)
                            st.dataframe(df, use_container_width=True)
                            csv = df.to_csv(index=False).encode('utf-8')
                            st.download_button("Descargar Tabla (CSV)", data=csv, file_name="pubmed_filtrado.csv", mime="text/csv")
                        else:
                            st.warning("Los artículos encontrados no cumplen el Nivel de Evidencia requerido.")

                except Exception as e:
                    st.error(f"Error en la ejecución: {e}")

with tabs[1]: st.info("En desarrollo...")
with tabs[2]: st.info("En desarrollo...")
