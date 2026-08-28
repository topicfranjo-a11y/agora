# ==============================================================================
# 1. UVOZ BIBLIOTEKA
# ==============================================================================
import os
import time
import json
import re
from datetime import datetime
import requests
import streamlit as st
import psycopg2
import plotly.graph_objects as go
from google import genai
from google.genai import errors

# ==============================================================================
# 2. KONFIGURACIJA STRANICE (Mora biti prva Streamlit naredba)
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
# 4. INICIJALIZACIJA GEMINI KLIJENTA
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
# 5. FUNKCIJE ZA POSTGRESQL BAZU PODATAKA
# ==============================================================================
def otvori_vezu():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def inicijaliziraj_bazu():
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        
        # OBIJE REŠENJA U JEDNOM:
        # Automatski dodajemo stupac 'korisnik' ako je tablica kreirana ranije bez njega
        try:
            cursor.execute("ALTER TABLE argumenti ADD COLUMN IF NOT EXISTS korisnik TEXT;")
            conn.commit()
        except Exception:
            conn.rollback() # Ako baza ne podržava 'IF NOT EXISTS' za alter, idemo dalje safely
        
        # 1. Tablica korisnika (IP + Pseudonim)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS korisnici (
                ip_adresa TEXT PRIMARY KEY,
                pseudonim TEXT NOT NULL,
                datum_registracije TEXT NOT NULL
            )
        """)
        
        # 2. Tablica tema rasprava
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS teme (
                id SERIAL PRIMARY KEY,
                naziv TEXT UNIQUE NOT NULL,
                aktivna BOOLEAN DEFAULT TRUE
            )
        """)
        
        # 3. Tablica argumenata (Sada sigurno kreira s novom strukturom)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS argumenti (
                id SERIAL PRIMARY KEY,
                korisnik TEXT NOT NULL,
                tema TEXT NOT NULL DEFAULT 'Općenito',
                tekst TEXT NOT NULL,
                datum TEXT NOT NULL,
                ton TEXT
            )
        """)
        
        # 4. Umetanje početnih tema ako je tablica prazna
        cursor.execute("SELECT COUNT(*) FROM teme")
        rezultat = cursor.fetchone()
        
        if rezultat and rezultat[0] == 0:
            pocetne_teme = [
                ("Etičke granice genetskog inženjeringa",),
                ("Utjecaj umjetne inteligencije na privatnost",),
                ("Budućnost decentraliziranog upravljanja društvom",)
            ]
            cursor.executemany("INSERT INTO teme (naziv) VALUES (%s)", pocetne_teme)
            
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Kritična greška u bazi podataka: {str(e)}")


def dohvati_ili_kreiraj_korisnika(ip_adresa):
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        cursor.execute("SELECT pseudonim FROM korisnici WHERE ip_adresa = %s", (ip_adresa,))
        rezultat = cursor.fetchone()
        
        if rezultat:
            pseudonim = rezultat[0]
        else:
            kratki_ip = ip_adresa.split(".")[-1] if ip_adresa and "." in ip_adresa else "X"
            pseudonim = f"Građanin_{kratki_ip}_{int(time.time()) % 1000}"
            vrijeme = datetime.now().strftime("%d.%m.%Y.")
            cursor.execute(
                "INSERT INTO korisnici (ip_adresa, pseudonim, datum_registracije) VALUES (%s, %s, %s)",
                (ip_adresa, pseudonim, vrijeme)
            )
            conn.commit()
            st.toast(f"🔑 Kreiran privremeni profil: {pseudonim}")
            
        cursor.close()
        conn.close()
        return str(pseudonim)
    except Exception:
        return "Gost_Agore"

def azuriraj_pseudonim(ip_adresa, novi_pseudonim):
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        cursor.execute("UPDATE korisnici SET pseudonim = %s WHERE ip_adresa = %s", (novi_pseudonim, ip_adresa))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception:
        return False

def dohvati_aktivne_teme():
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        cursor.execute("SELECT naziv FROM teme WHERE aktivna = TRUE ORDER BY id ASC")
        teme = [red[0] for red in cursor.fetchall()]
        cursor.close()
        conn.close()
        return teme if teme else ["Općenito"]
    except Exception:
        return ["Općenito"]

def dodaj_novu_temu(naziv_teme):
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO teme (naziv) VALUES (%s) ON CONFLICT DO NOTHING", (naziv_teme.strip(),))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception:
        return False

def spremi_argument(korisnik, tema, tekst, ton):
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        vrijeme = datetime.now().strftime("%d.%m.%Y. u %H:%M")
        cursor.execute(
            "INSERT INTO argumenti (korisnik, tema, tekst, datum, ton) VALUES (%s, %s, %s, %s, %s)", 
            (korisnik, tema, tekst, vrijeme, str(ton))
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        st.error(f"Greška pri spremanju u bazu: {e}")

def dohvati_metriku_teme(tema_naziv):
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        cursor.execute("SELECT ton, korisnik FROM argumenti WHERE tema = %s", (tema_naziv,))
        rezultati = cursor.fetchall()
        cursor.close()
        conn.close()
        
        if not rezultati:
            return 0, 0
            
        broj_sudionika = len(set([r[1] for r in rezultati]))
        vrijednosti = []
        for r in rezultati:
            try:
                if r[0]:
                    vrijednosti.append(float(r[0]))
            except ValueError:
                continue
                
        prosjek = round(sum(vrijednosti) / len(vrijednosti)) if vrijednosti else 0
        return prosjek, broj_sudionika
    except Exception:
        return 0, 0

def dohvati_argumente(samo_moje=False, trenutni_korisnik=None):
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        if samo_moje and trenutni_korisnik:
            cursor.execute("SELECT korisnik, tema, tekst, datum, ton FROM argumenti WHERE korisnik = %s ORDER BY id DESC", (trenutni_korisnik,))
        else:
            cursor.execute("SELECT korisnik, tema, tekst, datum, ton FROM argumenti ORDER BY id DESC")
        
        argumenti = cursor.fetchall()
        cursor.close()
        conn.close()
        return argumenti
    except Exception:
        return []

# ==============================================================================
# 6. GLOBALNE AI FUNKCIJE
# ==============================================================================
def analiziraj_tekst_s_gemini(korisnikov_tekst):
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
                json_tekst = re.sub(r"```[a-zA-Z]*", "", json_tekst).strip()
                json_tekst = json_tekst.replace("```", "").strip()
                metrika = json.loads(json_tekst)
            
        # 2. Izvlačenje statusa iz sekcije ### [STATUS]
        status_mec = re.search(r"### \[STATUS\]\s*\n*(ZAKLJUČANO|OTKLJUČANO)", tekst_odgovora, re.IGNORECASE)
        if status_mec:
            status = status_mec.group(1).upper().strip()
            
    except Exception:
        st.warning("⚠️ Čuvar Agore je vratio nestandardan format metrike, ali tekst je obrađen.")
        
    return metrika, status

# ==============================================================================
# 7. GLAVNO IZVRŠAVANJE I STREAMLIT UI
# ==============================================================================
# Inicijalizacija baze na startu
inicijaliziraj_bazu()

# Siguran dohvat IP adrese
try:
    ip_adresa = requests.get("https://ipify.org", timeout=2).text
except Exception:
    ip_adresa = "127.0.0.1"

# Dohvaćanje ili kreiranje pseudonima iz baze
trenutni_korisnik = dohvati_ili_creiraj_korisnika(ip_adresa) if 'dohvati_ili_creiraj_korisnika' in globals() else dohvati_ili_kreiraj_korisnika(ip_adresa)

# Prikaz glavnog sučelja
st.title("🏛️ Agora Web — Protokol Uma")
st.subheader(f"Dobrodošli natrag, {trenutni_korisnik}")

st.markdown("""
Ovaj sustav nadzire Čuvar Agore. Svaki uneseni tekst bit će analiziran na analitičnost,
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

# Gumb za pokretanje analize i spremanje
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
                    st.success("🔓 PROČIŠĆAVANJE USPJEŠNO (OTKLJUČANO): Tvoja misao zadovoljava standarde Agore i trajno je zapisana u protokole rasprave!")
                else:
                    st.error("🔒 BLOKADA (ZAKLJUČANO): Tvoja misao sadrži blokade uma ili pristranosti. Zapisana je u arhivu radi daljnjeg rada na sebi.")
