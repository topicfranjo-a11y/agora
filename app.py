# Provjera i inicijalizacija pojedinačno
if "GEMINI_API_KEY" in st.secrets:
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.warning("⚠️ Gemini API ključ nije pronađen u Secrets postavkama.")

if "OPENAI_API_KEY" in st.secrets:
    openai_client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.warning("⚠️ OpenAI API ključ nije pronađen u Secrets postavkama.")

# ==============================================================================
# 1. UVOZ BIBLIOTEKA
# ==============================================================================
import os
import time
import json
from datetime import datetime
import streamlit as st
import psycopg2
import plotly.graph_objects as go
from openai import OpenAI
from google import genai
from google.genai import errors
from streamlit_javascript import st_javascript

# ==============================================================================
# 2. KONFIGURACIJA STRANICE (Mora biti prva Streamlit naredba)
# ==============================================================================
st.set_page_config(page_title="Agora Web — Protokol Uma", page_icon="🏛️", layout="wide")

# ==============================================================================
# 3. GLOBALNI AI PROMPT (Višejezičnost + Analiza + Prijevod)
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
# 4. INICIJALIZACIJA AI KLIJENATA
# ==============================================================================
client = None
openai_client = None

try:
    if "GEMINI_API_KEY" in st.secrets:
        client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    if "OPENAI_API_KEY" in st.secrets:
        openai_client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
except Exception as e:
    st.error(f"Problem s učitavanjem API ključeva iz Secrets postavki: {e}")

# ==============================================================================
# 5. FUNKCIJE ZA POSTGRESQL BAZU PODATAKA
# ==============================================================================
def otvori_vezu():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def inicijaliziraj_bazu():
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        
        # Tablica korisnika (IP + Pseudonim)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS korisnici (
                ip_adresa TEXT PRIMARY KEY,
                pseudonim TEXT NOT NULL,
                datum_registracije TEXT NOT NULL
            )
        """)
        
        # Tablica tema rasprava
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS teme (
                id SERIAL PRIMARY KEY,
                naziv TEXT UNIQUE NOT NULL,
                aktivna BOOLEAN DEFAULT TRUE
            )
        """)
        
        # Tablica argumenata
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
        
        # Umetanje početnih tema ako je tablica prazna
        cursor.execute("SELECT COUNT(*) FROM teme")
        if cursor.fetchone()[0] == 0:
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
        st.error(f"Greška pri inicijalizaciji baze podataka: {e}")

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
        return pseudonim
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
    except Exception as e:
        st.error(f"Greška pri promjeni pseudonima: {e}")
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
        # POPRAVLJENO: Dodan peti '%s' placeholder za polje 'ton'
        cursor.execute(
            "INSERT INTO argumenti (korisnik, tema, tekst, datum, ton) VALUES (%s, %s, %s, %s, %s)", 
            (korisnik, tema, tekst, vrijeme, ton)
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
    # POPRAVLJENO: Funkcija je potpuno dovršena i zatvorena logicom
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
# 6. IZVRŠAVANJE I STREAMLIT UI (Primjer integracije IP adrese)
# ==============================================================================
# Inicijalizacija baze na startu
inicijaliziraj_bazu()

# Dohvat IP adrese preko učitane JS komponente
json_ip = st_javascript("https://ipify.org")
ip_adresa = "127.0.0.1"
if json_ip and isinstance(json_ip, dict) and "ip" in json_ip:
    ip_adresa = json_ip["ip"]

trenutni_korisnik = dohvati_ili_kreiraj_korisnika(ip_adresa)
