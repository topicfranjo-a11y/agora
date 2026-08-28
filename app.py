# ==============================================================================
# 1. UVOZ BIBLIOTEKA (Uklonjen OpenAI)
# ==============================================================================
import re
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
        ai_klijent = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    except Exception as e:
        st.error(f"Greška pri pokretanju Gemini klijenta: {e}")
else:
    st.error("❌ Kritična greška: 'GEMINI_API_KEY' nije pronađen u Streamlit Secrets postavkama!")

# ==============================================================================
# 5. GLOBALNE AI FUNKCIJE (Moraju biti uz lijevi rub ekrana, iznad UI-ja!)
# ==============================================================================
def analiziraj_tekst_s_gemini(korisnikov_tekst):
    """
    Šalje tekst na analizu. Ako je primarni model (gemini-3.6-flash) nedostupan (503),
    sustav automatski prebacuje na stabilnu alternativu (gemini-1.5-flash).
    """
    if not ai_klijent:
        st.error("AI klijent nije inicijaliziran. Provjerite API ključ.")
        return None

    modeli_za_pokusaj = ['gemini-3.6-flash', 'gemini-1.5-flash']

    for trenutni_model in modeli_za_pokusaj:
        try:
            odgovor = ai_klijent.models.generate_content(
                model=trenutni_model,
                contents=korisnikov_tekst,
                config={
                    'system_instruction': SYSTEM_PROMPT,
                    'temperature': 0.2
                }
            )
            return odgovor.text
        except Exception as e:
            if "503" in str(e) and trenutni_model != modeli_za_pokusaj[-1]:
                continue
            else:
                st.error(f"Greška pri AI analizi ({trenutni_model}): {e}")
                return None
    return None


def parsiraj_metriku_i_status(tekst_odgovora):
    """
    Izvlači JSON metriku i STATUS (ZAKLJUČANO/OTKLJUČANO) iz Gemini odgovora.
    """
    metrika = {"analitika": 0, "empatija": 0, "sinteza": 0, "suglasje": 0}
    status = "ZAKLJUČANO"
    
    if not tekst_odgovora:
        return metrika, status

    try:
        # 1. Izvlačenje JSON-a iz sekcije ### [METRIKA]
        if "### [METRIKA]" in tekst_odgovora:
            dijelovi = tekst_odgovora.split("### [METRIKA]")
            if len(dijelovi) > 1:
                json_tekst = dijelovi[1].strip()
                import re
                json_tekst = re.sub(r"```[a-zA-Z]*", "", json_tekst).strip()
                json_tekst = json_tekst.replace("```", "").strip()
                metrika = json.loads(json_tekst)
            
        # 2. Izvlačenje statusa iz sekcije ### [STATUS]
        import re
        status_meč = re.search(r"### \[STATUS\]\s*\n*(ZAKLJUČANO|OTKLJUČANO)", tekst_odgovora, re.IGNORECASE)
        if status_meč:
            status = status_meč.group(1).upper().strip()
            
    except Exception as e:
        st.warning("⚠️ Čuvar Agore je vratio nestandardan format metrike, ali tekst je obrađen.")
        
    return metrika, status

# ==============================================================================
# 6. GLAVNO IZVRŠAVANJE I STREAMLIT UI
# ==============================================================================
# Inicijalizacija baze na startu
inicijaliziraj_bazu()

# Siguran dohvat IP adrese preko Pythona
try:
    import requests
    ip_adresa = requests.get("https://ipify.org", timeout=2).text
except Exception:
    ip_adresa = "127.0.0.1"

# Dohvaćanje ili kreiranje pseudonima iz baze
trenutni_korisnik = dohvati_ili_creiraj_korisnika(ip_adresa)

# Prikaz glavnog sučelja
st.title("🏛️ Agora Web — Protokol Uma")
st.subheader(f"Dobrodošli natrag, **{trenutni_korisnik}**")

st.markdown("""
Ovaj sustav nadzire **Čuvar Agore**. Svaki uneseni tekst bit će analiziran na analitičnost, 
empatiju i sintezu prije nego što bude trajno zapisan u protokole.
""")

# Izbornik za odabir teme rasprave
aktivne_teme = dohvati_aktivne_teme()
odabrana_tema = st.selectbox(
    "Odaberite temu za raspravu:", 
    aktivne_teme, 
    key="selectbox_izbor_teme_agora"
)

# Polje za unos teksta
korisnikov_unos = st.text_area("Unesite svoj argument ili misao ovdje:", height=150, placeholder="Napišite što mislite...")

# Gumb za pokretanje analize i spremanje (Sve funkcije iznad su sada vidljive!)
if st.button("Pošalji na analizu i pročišćavanje", key="gumb_za_slanje_agora"):
    if korisnikov_unos.strip() == "":
        st.warning("Molimo vas da unesete tekst prije slanja.")
    else:
        with st.spinner("Čuvar Agore analizira vašu misao i provjerava protokole..."):
            rezultat_analize = analiziraj_tekst_s_gemini(korisnikov_unos)
            
            if rezultat_analize:
                st.success("Čuvar Agore je završio analizu!")
                st.markdown(rezultat_analize)
                
                # Parsiranje ocjena i statusa iz teksta
                metrika, status = parsiraj_metriku_i_status(rezultat_analize)
                izracunata_ocjena_tona = metrika.get("suglasje", metrika.get("analitika", 0))
                
                # Trajno spremanje u bazu podataka
                spremi_argument(
                    korisnik=trenutni_korisnik,
                    tema=odabrana_tema,
                    tekst=korisnikov_unos.strip(),
                    ton=izracunata_ocjena_tona
                )
                
                # Prikaz vizualnog statusa pročišćavanja
                st.divider()
                if status == "OTKLJUČANO":
                    st.balloons()
                    st.success("🔓 **PROČIŠĆAVANJE USPJEŠNO (OTKLJUČANO):** Tvoja misao zadovoljava standarde Agore i trajno je zapisana u protokole rasprave!")
                else:
                    st.error("🔒 **BLOKADA (ZAKLJUČANO):** Tvoja misao sadrži blokade uma ili pristranosti. Zapisana je u arhivu radi daljnjeg rada na sebi.")
