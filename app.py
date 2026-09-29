import os
import io
import zipfile
import streamlit as st
import pandas as pd
import requests
from Bio import Entrez
from datetime import datetime
from playwright.sync_api import sync_playwright

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

# --- PESTAÑA 1: BÚSQUEDA ---
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
            st.error("Ingresa un query y correo electrónico válidos.")
        else:
            with st.spinner("Consultando NCBI E-utilities..."):
                Entrez.email = email
                try:
                    final_query = query + (' AND "loattrfree full text"[sb]' if free_only else '')
                    handle = Entrez.esearch(db="pubmed", term=final_query, retmax=max_results, mindate=str(year_range[0]), maxdate=str(year_range[1]), datetype="pdat")
                    record = Entrez.read(handle)
                    handle.close()
                    pmids = record["IdList"]

                    if not pmids:
                        st.warning("No se encontraron resultados.")
                    else:
                        st.info(f"Procesando {len(pmids)} PMIDs...")
                        fetch_handle = Entrez.efetch(db="pubmed", id=",".join(pmids), retmode="xml")
                        articles = Entrez.read(fetch_handle)
                        fetch_handle.close()

                        results = []
                        for article in articles.get('PubmedArticle', []):
                            medline = article['MedlineCitation']
                            data = medline['Article']
                            pmid = str(medline['PMID'])
                            title = data.get('ArticleTitle', 'Sin título')
                            year = data.get('Journal', {}).get('JournalIssue', {}).get('PubDate', {}).get('Year', 'N/A')
                            authors = data.get('AuthorList', [])
                            first_author = f"{authors[0].get('LastName', '')} {authors[0].get('Initials', '')}" if authors else "N/A"
                            doi = next((str(a) for a in article.get('PubmedData', {}).get('ArticleIdList', []) if a.attributes.get('IdType') == 'doi'), "")
                            ev_level = get_evidence_level(data.get('PublicationTypeList', []))

                            if ev_level <= min_evidence:
                                is_oa, pdf_url = check_unpaywall(doi, email)
                                results.append({
                                    "PMID": pmid, "DOI": doi, "Título": title, "Año": year, 
                                    "Autor": first_author, "Nivel": ev_level, 
                                    "Open Access": "Sí" if is_oa or free_only else "No", "PDF URL": pdf_url if pdf_url else "N/A"
                                })

                        if results:
                            df = pd.DataFrame(results)
                            st.session_state['df_results'] = df  # Guardar en RAM para la Fase 2
                            st.dataframe(df, use_container_width=True)
                            st.download_button("Descargar Tabla (CSV)", data=df.to_csv(index=False).encode('utf-8'), file_name="pubmed.csv", mime="text/csv")
                        else:
                            st.warning("Sin resultados bajo estos criterios.")
                except Exception as e:
                    st.error(f"Error: {e}")

# --- PESTAÑA 2: DESCARGAS ---
# --- PESTAÑA 2: DESCARGAS AVANZADAS ---
with tabs[1]:
    st.header("Descarga Automatizada y Extracción DOM")
    
    if 'df_results' not in st.session_state:
        st.info("Primero ejecuta una búsqueda en la 'Fase 1' para obtener artículos.")
    else:
        df = st.session_state['df_results']
        
        # Ahora procesaremos todos los que tengan PDF URL, o intentaremos raspar el DOI
        df_procesables = df[(df['PDF URL'] != "N/A") | (df['DOI'] != "")]
        
        st.metric(label="Artículos viables para extracción", value=len(df_procesables))
        
        if len(df_procesables) > 0:
            if st.button("Iniciar Pipeline de Extracción (v4.1 Cloud)", type="primary"):
                progress_bar = st.progress(0)
                zip_buffer = io.BytesIO()
                
                if 'docs_buffers' not in st.session_state:
                    st.session_state['docs_buffers'] = {} # Para la Fase 3

                with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                    
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        context = browser.new_context(
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                        )
                        
                        # TUS INYECCIONES STEALTH (Aplicadas a todo el contexto)
                        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                        context.add_init_script("window.navigator.chrome = { runtime: {} };")
                        context.add_init_script("Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});")
                        
                        total = len(df_procesables)
                        
                        for i, row in df_procesables.reset_index().iterrows():
                            pmid = row['PMID']
                            url_pdf = row['PDF URL']
                            doi = row['DOI']
                            titulo_limpio = "".join(x for x in str(row['Título'])[:30] if x.isalnum() or x.isspace()).replace(" ", "_")
                            nombre_base = f"{pmid}_{titulo_limpio}"
                            
                            # TU IDEA: UI Expander para logs detallados
                            with st.expander(f"🔄 Procesando: {pmid} - {row['Título'][:40]}...", expanded=(i==0)):
                                pdf_bytes = None
                                texto_plano = None
                                
                                # Pipeline 1: Intento HTTP directo al PDF
                                if url_pdf != "N/A":
                                    st.write(f"🌐 Intentando descarga directa: `{url_pdf}`")
                                    try:
                                        resp = requests.get(url_pdf, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                                        if resp.status_code == 200 and 'pdf' in resp.headers.get('Content-Type', '').lower():
                                            pdf_bytes = resp.content
                                            st.success("✅ PDF binario capturado en memoria.")
                                    except Exception as e:
                                        st.error(f"Fallo HTTP: {str(e)[:50]}")

                                # Pipeline 2: Contingencia DOM -> TXT usando Playwright
                                if not pdf_bytes and doi:
                                    url_web = f"https://doi.org/{doi}"
                                    st.warning(f"⚠️ PDF no disponible. Iniciando raspado DOM en: `{url_web}`")
                                    
                                    page = context.new_page()
                                    try:
                                        page.goto(url_web, wait_until="networkidle", timeout=15000)
                                        
                                        # Tu script inyectado en JS para buscar contenedores de texto
                                        texto_plano = page.evaluate("""() => {
                                            let selectores = ['#body', '.html-content', 'article', '#mc', '.article-wrapper', '[role="main"]', '.FullText'];
                                            let contenedor = null;
                                            for (let sel of selectores) {
                                                contenedor = document.querySelector(sel);
                                                if (contenedor && contenedor.innerText.length > 500) break;
                                            }
                                            if (!contenedor) contenedor = document.body;
                                            return contenedor ? contenedor.innerText : null;
                                        }""")
                                        
                                        if texto_plano and len(texto_plano) > 500:
                                            st.success("✅ Texto plano extraído de la estructura HTML.")
                                        else:
                                            texto_plano = None
                                            st.error("❌ Fallo estructural. DOM ofuscado o contenido paywalled.")
                                            
                                    except Exception as e:
                                        st.error(f"🔌 Error de navegación Playwright: {str(e)[:50]}")
                                    finally:
                                        page.close() # Limpieza estricta de memoria RAM

                                # Guardado en ZIP y Memoria (Stateless)
                                if pdf_bytes:
                                    zip_file.writestr(f"{nombre_base}.pdf", pdf_bytes)
                                    st.session_state['docs_buffers'][pmid] = {"tipo": "pdf", "contenido": pdf_bytes}
                                elif texto_plano:
                                    zip_file.writestr(f"{nombre_base}.txt", texto_plano.encode('utf-8'))
                                    st.session_state['docs_buffers'][pmid] = {"tipo": "txt", "contenido": texto_plano}
                            
                            progress_bar.progress((i + 1) / total)
                            
                        browser.close()
                
                st.success(f"🎉 Pipeline finalizado. Se han procesado {total} artículos.")
                
                st.download_button(
                    label="📦 Descargar todos en ZIP",
                    data=zip_buffer.getvalue(),
                    file_name="extraccion_medica.zip",
                    mime="application/zip"
                )

# --- PESTAÑA 3: MARKDOWN ---
with tabs[2]: 
    st.info("En desarrollo...")
