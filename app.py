import streamlit as st
import psycopg2  # Zamjena za sqlite3 (koristi se za PostgreSQL na serveru)
import plotly.graph_objects as go
import json
from openai import OpenAI
from datetime import datetime
import os

# 1. Konfiguracija stranice i klijenta pomoću Streamlit Secrets (Sigurnost na webu)
st.set_page_config(page_title="Agora Web — Protokol Uma", page_icon="🏛️", layout="wide")

# Podaci se povlače iz tajnih postavki servera, a ne iz koda
try:
    from google import genai
import streamlit as st

client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

# Primjer poziva modela u vašoj funkciji za analizu:
response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents='Vaš upit ili tekst za analizu'
)
print(response.text)

except Exception:
    st.error("Kreirajte 'OPENAI_API_KEY' unutar Streamlit Secrets / Environment Variables.")

SYSTEM_PROMPT = """
Uloga: Ti si "Čuvar Agore", napredni AI sustav zadužen za pročišćavanje ljudske misli. 
Tvoj zadatak NIJE sudjelovati u raspravi. Tvoj jedini zadatak je analizirati tekst korisnika.

Ocijeni korisnikov tekst u tri dimenzije na skali od 1 do 10:
- Analitičnost (logika, dokazi, dosljednost)
- Empatija (razumijevanje drugih strana, odmjerenost)
- Sinteza (sposobnost nalaženja zajedničkog jezika i mostova)

Format odgovora MORA biti strogo strukturiran u ovom obliku (nemoj koristiti markdown kodne blokove za JSON, samo tekst):
### [1. ANALIZA TONA]
(Rečenica o tonu)

### [2. UOČENE BLOKADE UMA]
- **[Naziv pogreške]**: (Kratko objašnjenje)

### [3. PRIJEDLOG ZA PROČIŠĆAVANJE]
(Primjer kako prepisati tekst)

### [STATUS]
(Napiši isključivo riječ ZAKLJUČANO ili OTKLJUČANO)

### [METRIKA]
{"analitika": X, "empatija": Y, "sinteza": Z}
"""

# 2. Funkcije za rad s PostgreSQL bazom podataka na serveru
def otvori_vezu():
    # Povezivanje preko baze podataka na serveru pomoću Connection Stringa
    # Primjer stringa: postgres://user:password@host:port/dbname
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def inicijaliziraj_bazu():
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        # PostgreSQL koristi SERIAL umjesto AUTOINCREMENT
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS argumenti (
                id SERIAL PRIMARY KEY,
                tekst TEXT NOT NULL,
                datum TEXT NOT NULL,
                ton TEXT
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        st.error(f"Greška pri inicijalizaciji baze: {e}")

def spremi_argument(tekst, ton):
    conn = otvori_vezu()
    cursor = conn.cursor()
    vrijeme = datetime.now().strftime("%d.%m.%Y. u %H:%M")
    cursor.execute("INSERT INTO argumenti (tekst, datum, ton) VALUES (%s, %s, %s)", (tekst, vrijeme, ton))
    conn.commit()
    cursor.close()
    conn.close()

def dohvati_sve_argumente():
    conn = otvori_vezu()
    cursor = conn.cursor()
    cursor.execute("SELECT tekst, datum, ton FROM argumenti ORDER BY id DESC")
    podaci = cursor.fetchall()
    cursor.close()
    conn.close()
    return podaci

# Pokretanje provjere tablice pri svakom učitavanju stranice
inicijaliziraj_bazu()

# 3. Funkcija za crtanje "Fraktala uma"
def nacrtaj_fraktal_uma(analitika, empatija, sinteza):
    kategorije = ['Analitički um (Logika)', 'Empatijski um (Razumijevanje)', 'Sintetički um (Mostovi)']
    vrijednosti = [analitika, empatija, sinteza]
    
    kategorije.append(kategorije[0])
    vrijednosti.append(vrijednosti[0])
    
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=vrijednosti,
        theta=kategorije,
        fill='toself',
        fillcolor='rgba(212, 175, 55, 0.2)',
        line=dict(color='#D4AF37', width=2),
        name='Vaš Fraktal'
    ))
    
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 10], gridcolor="rgba(255,255,255,0.1)"),
            angularaxis=dict(gridcolor="rgba(255,255,255,0.1)"),
            bgcolor="rgba(0,0,0,0)"
        ),
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=350,
        margin=dict(l=40, r=40, t=20, b=20)
    )
    return fig

# 4. Vizualno sučelje
st.title("🏛️ Globalna Agora — Protokol Uma")
st.caption("Web MVP | Centralizirana Cloud Baza | Tema tjedna: Etičke granice genetskog inženjeringa")
st.markdown("---")

if "status" not in st.session_state:
    st.session_state.status = "ZAKLJUČANO"
if "pročišćeni_tekst" not in st.session_state:
    st.session_state.pročišćeni_tekst = ""
if "metrika" not in st.session_state:
    st.session_state.metrika = None
if "ai_refleksija" not in st.session_state:
    st.session_state.ai_refleksija = ""

col1, col2 = st.columns(2)

with col1:
    st.subheader("Vaš doprinos zajednici")
    user_input = st.text_area("Upišite svoj argument ili tezu ovdje:", height=200, placeholder="Fokusirajte se na činjenice...")
    analiziraj_gumb = st.button("Skeniraj moj um ✨", use_container_width=True)

# 5. Logika i raščlanjivanje AI odgovora
if analiziraj_gumb and user_input:
    with col2:
        with st.spinner("Čuvar Agore analizira vašu misao..."):
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_input}
                    ],
                    temperature=0.3
                )
                
                pun_izlaz = response.choices.message.content
                dijelovi = pun_izlaz.split("### [METRIKA]")
                st.session_state.ai_refleksija = dijelovi[0]
                
                if len(dijelovi) > 1:
                    try:
                        metrika_json = json.loads(dijelovi[1].strip())
                        st.session_state.metrika = metrika_json
                    except Exception:
                        st.session_state.metrika = {"analitika": 5, "empatija": 5, "sinteza": 5}
                
                if "OTKLJUČANO" in st.session_state.ai_refleksija:
                    st.session_state.status = "OTKLJUČANO"
                    st.session_state.pročišćeni_tekst = user_input
                else:
                    st.session_state.status = "ZAKLJUČANO"
                    st.session_state.pročišćeni_tekst = ""
                    
            except Exception as e:
                st.error(f"Pogreška prilikom AI analize: {e}")

with col2:
    if st.session_state.ai_refleksija:
        st.subheader("Ogledalo uma (AI Refleksija)")
        st.markdown(st.session_state.ai_refleksija)
        
    if st.session_state.metrika is not None:
        st.markdown("### Vaša trenutna Aura doprinosa")
        m = st.session_state.metrika
        fig = nacrtaj_fraktal_uma(m.get("analitika", 5), m.get("empatija", 5), m.get("sinteza", 5))
        st.plotly_chart(fig, use_container_width=True)

with col1:
    st.markdown("---")
    if st.session_state.status == "OTKLJUČANO":
        st.success("🔓 Vaš um je pročišćen i spreman za kolektivnu mudrost.")
        if st.button("Pošalji argument u globalnu Agoru 🚀", type="primary", use_container_width=True):
            spremi_argument(st.session_state.pročišćeni_tekst, "Uravnotežen um")
            st.balloons()
            st.session_state.status = "ZAKLJUČANO"
            st.session_state.pročišćeni_tekst = ""
            st.session_state.metrika = None
            st.session_state.ai_refleksija = ""
            st.rerun()
    else:
        st.warning("🔒 Gumb za slanje je zaključan. Ispravite uočene blokade uma u desnom stupcu.")
        st.button("Pošalji argument u globalnu Agoru 🚀", disabled=True, use_container_width=True)

# 6. Riznica mudrosti dohvaća se sinkronizirano sa servera
st.markdown("---")
st.header("📚 Kolektivna riznica mudrosti")
try:
    svi_argumenti = dohvati_sve_argumente()
    if not svi_argumenti:
        st.info("Riznica je prazna. Otključajte ulaz!")
    else:
        for tekst, datum, ton in svi_argumenti:
            st.markdown(f"**Zapisano: {datum}** | *Arhetip: {ton}*")
            st.info(tekst)
except Exception as db_err:
    st.error(f"Problem s bazom podataka na serveru: {db_err}")
