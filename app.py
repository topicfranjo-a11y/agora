# ==============================================================================
# 1. UVOZ BIBLIOTEKA (Uklonjen OpenAI)
# ==============================================================================
import requests
import os
import time
import json
from datetime import datetime
import streamlit as st
import psycopg2
import plotly.graph_objects as go
from google import genai
from google.genai import errors
from streamlit_javascript import st_javascript

# ==============================================================================
# 2. KONFIGURACIJA STRANICE
# ==============================================================================
st.set_page_config(page_title="Agora Web — Protokol Uma", page_icon="🏛️", layout="wide")

# ==============================================================================
# 3. GLOBALNI AI PROMPT
# ==============================================================================
SYSTEM_PROMPT = """
Uloga: Ti si "Čuvar Agore", napredni AI sustav zadužen za pročišćavanje ljudske misli. 
Tvoj zadatak NIJE sudjelovati u raspravi. Tvoj jedini zadatak je analizirati tekst korisnika.
Možeš primiti tekst na bilo kojem svjetskom jeziku.

Ocijeni korisnikov tekst u tri dimenzije na skali od 1 do 10:
- Analitičnost (logika, dokazi, dosljednost)
- Empatija (razumijevanje drugih strana, odmjerenost)
- Sinteza (sposobnost nalaženja zajedničkog jezika i mostova)

Format odgovora MORA biti strogo strukturiran u ovom obliku (nemoj koristiti markdown kodne blokove za JSON, samo tekst):
### [1. ANALIZA TONA]
(Rečenica o tonu na hrvatskom jeziku)

### [2. UOČENE BLOKADE UMA]
- **[Naziv pogreške]**: (Kratko objašnjenje na hrvatskom jeziku)

### [3. PRIJEDLOG ZA PROČIŠĆAVANJE]
(Primjer kako prepisati tekst na hrvatskom jeziku)

### [STATUS]
(Napiši isključivo riječ ZAKLJUČANO ili OTKLJUČANO)

### [TRANSLATION]
(Ovdje napiši POTPUNI PRIJEVOD korisnikovog izvornog teksta na ENGLESKI JEZIK, bez ikakvih tvojih komentara. Ako je status ZAKLJUČANO, ostavi ovo polje prazno.)

### [METRIKA]
{"analitika": X, "empatija": Y, "sinteza": Z, "suglasje": S}
"""

# ==============================================================================
# 4. INICIJALIZACIJA GEMINI KLIJENTA (Samo Gemini)
# ==============================================================================
ai_klijent = None

if "GEMINI_API_KEY" in st.secrets:
    try:
        # Inicijalizacija prema novom google-genai SDK-u
        ai_klijent = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    except Exception as e:
        st.error(f"Greška pri pokretanju Gemini klijenta: {e}")
else:
    st.error("❌ Kritična greška: 'GEMINI_API_KEY' nije pronađen u Streamlit Secrets postavkama!")

# ==============================================================================
# 5. FUNKCIJA ZA ANALIZU TEKSTA PREKO GEMINI MODELA
# ==============================================================================
def analiziraj_tekst_s_gemini(korisnikov_tekst):
    """
    Šalje tekst na analizu koristeći novi Google GenAI SDK i model gemini-2.5-flash.
    """
    if not ai_klijent:
        st.error("AI klijent nije inicijaliziran. Provjerite API ključ.")
        return None

    try:
        # Slanje zahtjeva s definiranim system_instruction parametrom
        odgovor = ai_klijent.models.generate_content(
            model='gemini-2.5-flash',
            contents=korisnikov_tekst,
            config={
                'system_instruction': SYSTEM_PROMPT,
                'temperature': 0.2  # Niža temperatura za strogo praćenje strukture formata
            }
        )
        return odgovor.text
    except errors.APIError as e:
        st.error(f"Gemini API greška: {e}")
        return None
    except Exception as e:
        st.error(f"Neočekivana greška pri analizi: {e}")
        return None


# ==============================================================================
# 6. SIGURAN DOHVAT IP ADRESE I KORISNIKA
# ==============================================================================
# Inicijalizacija baze na startu
inicijaliziraj_bazu()

# Pokušavamo dohvatiti IP adresu preko brzog Python API poziva (ne blokira UI)
try:
    ip_adresa = requests.get("https://ipify.org", timeout=2).text
except Exception:
    ip_adresa = "127.0.0.1"  # Rezervna opcija ako mreža ne reagira

# Dohvaćanje ili kreiranje pseudonima iz baze
trenutni_korisnik = dohvati_ili_kreiraj_korisnika(ip_adresa)

# ==============================================================================
# 7. STREAMLIT KORISNIČKO SUČELJE (UI) - Ovo će odmah ukloniti prazan ekran
# ==============================================================================
st.title("🏛️ Agora Web — Protokol Uma")
st.subheader(f"Dobrodošli natrag, **{trenutni_korisnik}**")

# Kratke upute za korisnika
st.markdown("""
Ovaj sustav nadzire **Čuvar Agore**. Svaki uneseni tekst bit će analiziran na analitičnost, 
empatiju i sintezu prije nego što bude trajno zapisan u protokole.
""")

# Izbornik za odabir teme rasprave
aktivne_teme = dohvati_aktivne_teme()
odabrana_tema = st.selectbox("Odaberite temu za raspravu:", aktivne_teme)

# Polje za unos teksta
korisnikov_unos = st.text_area("Unesite svoj argument ili misao ovdje:", height=150, placeholder="Napišite što mislite...")

if st.button("Pošalji na analizu i pročišćavanje", type="primary"):
    if korisnikov_unos.strip() == "":
        st.warning("Molimo vas da unesete tekst prije slanja.")
    else:
        with st.spinner("Čuvar Agore analizira vašu misao..."):
            # Ovdje pozivamo funkciju za Gemini koju smo ranije definirali
            rezultat_analize = analiziraj_tekst_s_gemini(korisnikov_unos)
            
            if rezultat_analize:
                st.success("Analiza uspješno izvršena!")
                st.markdown(rezultat_analize)
                
                # TODO: Ovdje ćemo u idućem koraku dodati parsiranje [METRIKE] i spremanje u bazu!


