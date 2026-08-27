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
try:
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"]) 
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
        
        # Tablica argumenata (Tekst je na engleskom zbog prijevoda)
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
            kratki_ip = ip_adresa.split(".")[-1] if "." in ip_adresa else "X"
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
        cursor.execute(
            "INSERT INTO argumenti (korisnik, tema, tekst, datum, ton) VALUES (%s, %s, %s, %s)", 
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
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        if samo_moje and trenutni_korisnik:
            cursor.execute("SELECT tekst, datum, ton, tema, korisnik FROM argumenti WHERE korisnik = %s ORDER BY id DESC", (trenutni_korisnik,))
        else:
            cursor.execute("SELECT tekst, datum, ton, tema, korisnik FROM argumenti ORDER BY id DESC")
        podaci = cursor.fetchall()
        cursor.close()
        conn.close()
        return podaci
    except Exception:
        return []

# Pokretanje baze podataka pri učitavanju skripte
inicijaliziraj_bazu()

# ==============================================================================
# 6. FUNKCIJE ZA PLOTLY VIZUALIZACIJE
# ==============================================================================
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
        height=320,
        margin=dict(l=40, r=40, t=20, b=20)
    )
    return fig

def nacrtaj_indikator_suglasja(postotak):
    fig = go.Figure(go.Indicator(
mode = "gauge+number",
value = postotak,
number = {'suffix': "%", 'font': {'color': "#D4AF37", 'size': 22}},
domain = {'x':, 'y': [0, 1]},
gauge = {
'axis': {'range':, 'tickwidth': 1, 'tickcolor': "rgba(255,255,255,0.2)"},
'bar': {'color': "#D4AF37"},
'bgcolor': "rgba(255,255,255,0.05)",
'borderwidth': 0,
'steps': [
{'range':, 'color': 'rgba(231, 76, 60, 0.1)'},
{'range':, 'color': 'rgba(241, 196, 15, 0.1)'},
{'range':, 'color': 'rgba(46, 204, 113, 0.1)'}
],
}
))
fig.update_layout(
paper_bgcolor="rgba(0,0,0,0)",
plot_bgcolor="rgba(0,0,0,0)",
height=100,
margin=dict(l=10, r=10, t=10, b=10)
)
return fig
==============================================================================
7. VIZUALNO SUČELJE I AUTENTIFIKACIJA PREMA IP ADRESI
==============================================================================
st.title("🏛️ Globalna Agora — Protokol Uma")
st.caption("Web MVP | Centralizirana Cloud Baza | Globalno prevođenje u pozadini")
st.markdown("---")
JavaScript dohvaćanje stvarne IP adrese klijenta
script_ip = 'await fetch("ipify.org").then(r => r.json())'
vratni_ip_objekt = st_javascript(script_ip)
user_ip = "127.0.0.1"
if isinstance(vratni_ip_objekt, dict) and "ip" in vratni_ip_objekt:
user_ip = vratni_ip_objekt["ip"]
trenutni_pseudonim = dohvati_ili_kreiraj_korisnika(user_ip)
Bočna traka (Sidebar) za profil i upravljanje temama
with st.sidebar:
st.markdown("### 👤 Vaš Agora Profil")
st.info(f"📍 IP Autentifikacija: {user_ip}")
st.success(f"🎭 Pseudonim: {trenutni_pseudonim}")
novi_izbor = st.text_input("Promijeni svoj pseudonim:", value=trenutni_pseudonim, max_chars=20)
if st.button("Spremi novi pseudonim", use_container_width=True):
if novi_izbor.strip() and novi_izbor != trenutni_pseudonim:
if azuriraj_pseudonim(user_ip, novi_izbor.strip()):
st.success("Uspješno ažurirano! Osvježavam...")
time.sleep(0.8)
st.rerun()
st.markdown("---")
st.markdown("### 🛠️ Upravljanje Agorom (Admin)")
nova_tema_input = st.text_input("Dodaj novu temu rasprave:")
if st.button("Kreiraj temu ➕", use_container_width=True):
if nova_tema_input.strip():
if dodaj_novu_temu(nova_tema_input):
st.success("Nova tema uspješno stvorena!")
time.sleep(0.8)
st.rerun()
Inicijalizacija stanja
if "ai_tekstualni_dio" not in st.session_state:
st.session_state.ai_tekstualni_dio = ""
if "metrika" not in st.session_state:
st.session_state.metrika = None
if "status" not in st.session_state:
st.session_state.status = "ZAKLJUČANO"
Raspored u dva glavna stupca
col1, col2 = st.columns(2)
with col1:
st.subheader("Vaš doprinos zajednici")
sub_col1, sub_col2 = st.columns([0.7, 0.3])
with sub_col1:
lista_tema = dohvati_aktivne_teme()
izabrana_tema = st.selectbox("🎯 Odaberite temu za raspravu:", lista_tema)
trenutno_suglasje, ukupno_sudionika = dohvati_metriku_teme(izabrana_tema)
with sub_col2:
fig_suglasje = nacrtaj_indikator_suglasja(trenutno_suglasje)
st.plotly_chart(fig_suglasje, use_container_width=True, key=f"sug_chart_{izabrana_tema}")
meta1, meta2 = st.columns(2)
with meta1:
st.markdown(f"Indeks društvenog konsenzusa: {trenutno_suglasje}%")
with meta2:
oznaka_sudionika = "sudionika" if ukupno_sudionika != 1 else "sudionik"
st.markdown(f"👥 Uzorak rasprave: {ukupno_sudionika} {oznaka_sudionika}")
st.markdown("---")
user_input = st.text_area("Upišite svoj argument ili tezu ovdje (bilo koji jezik):", height=180, placeholder="Fokusirajte se na činjenice...")
analiziraj_gumb = st.button("Skeniraj moj um ✨", use_container_width=True)
==============================================================================
8. LOGIKA OBRADE I PROSLJEĐIVANJA (Fallback + Prevođenje + Razdioba)
==============================================================================
if analiziraj_gumb and user_input:
with col2:
with st.spinner("Čuvar Agore analizira vašu misao..."):
pun_izlaz = None
DINAMICKI_SYSTEM_PROMPT = SYSTEM_PROMPT + f"\n\nTRENUTNA ZADANA TEMA: '{izabrana_tema}'." 
f"\nKRITIČNO PRAVILO: Ako tekst korisnika bježi s ove teme, " 
f"ocijeni 'Analitičnost' ocjenom 1, a u sekciji [STATUS] obavezno " 
f"napiši ZAKLJUČANO s objašnjenjem u tonu da je tema promašena."
# --- POKUŠAJ 1: Primarni model (Google Gemini 3.6 Flash) ---
try:
response = client.models.generate_content(
model="gemini-3.6-flash",
contents=user_input,
config={"system_instruction": DINAMICKI_SYSTEM_PROMPT}
)
pun_izlaz = response.text
st.toast("Analiza uspješno izvršena putem Gemini modela.", icon="🚀")
except errors.APIError as e:
if e.code == 429:
st.warning("⏱️ Gemini kvota potrošena. Aktiviram pričuvni OpenAI model...")
# --- POKUŠAJ 2: Pričuvni model (OpenAI gpt-4o-mini) ---
try:
openai_response = openai_client.chat.completions.create(
model="gpt-4o-mini",
messages=[
{"role": "system", "content": DINAMICKI_SYSTEM_PROMPT},
{"role": "user", "content": user_input}
],
temperature=0.3
)
pun_izlaz = openai_response.choices[0].message.content
st.toast("Analiza izvršena putem OpenAI modela.", icon="🔄")
except Exception as openai_err:
st.error(f"Ni pričuvni OpenAI model nije uspio: {openai_err}")
else:
st.error(f"Google GenAI pogreška ({e.code}): {e.message}")
except Exception as e:
st.error(f"Neočekivana pogreška: {e}")
# --- 9. RAŠČLANJIVANJE ODGOVORA I UPIS U BAZU ---
if pun_izlaz:
try:
if "### [METRIKA]" in pun_izlaz:
dijelovi_metrike = pun_izlaz.split("### [METRIKA]")
glavni_tekst = dijelovi_metrike[0]
json_string = dijelovi_metrike[1].strip()
json_string = json_string.replace("json", "").replace("", "").strip()
metrika_data = json.loads(json_string)
st.session_state.metrika = metrika_data
st.session_state.ai_tekstualni_dio = glavni_tekst
if "OTKLJUČANO" in glavni_tekst:
st.session_state.status = "OTKLJUČANO"
engleski_tekst = user_input # Fallback ako prijevod zakaže
if "### [TRANSLATION]" in glavni_tekst:
dijelovi_prijevoda = glavni_tekst.split("### [TRANSLATION]")
st.session_state.ai_tekstualni_dio = dijelovi_prijevoda[0]
engleski_tekst = dijelovi_prijevoda[1].strip()
postotak_suglasja = metrika_data.get("suglasje", 50)
spremi_argument(trenutni_pseudonim, izabrana_tema, engleski_tekst, str(postotak_suglasja))
st.success("🌍 Misao uspješno prevedena i pohranjena u globalnu bazu!")
time.sleep(0.5)
st.rerun()
else:
st.session_state.status = "ZAKLJUČANO"
else:
st.session_state.ai_tekstualni_dio = pun_izlaz
st.session_state.metrika = None
except Exception as parse_err:
st.error(f"Greška prilikom raščlanjivanja AI odgovora: {parse_err}")
Prikaz spremljenih stanja u desnom stupcu (col2)
with col2:
if st.session_state.ai_tekstualni_dio:
st.subheader("💡 Rezultat AI Analize")
st.markdown(st.session_state.ai_tekstualni_dio)
if st.session_state.metrika:
st.subheader("📊 Fraktal Vašeg Uma")
m = st.session_state.metrika
fig = nacrtaj_fraktal_uma(m.get("analitika", 5), m.get("empatija", 5), m.get("sinteza", 5))
st.plotly_chart(fig, use_container_width=True)
if st.session_state.status == "OTKLJUČANO":
st.success("🔓 STATUS: OTKLJUČANO — Vaša misao je dodana u arhivu Agore.")
else:
st.error("🔒 STATUS: ZAKLJUČANO — Misao zahtijeva dodatno pročišćavanje prije objave.")
==============================================================================
10. ARHIVA PROČIŠĆENIH MISLI S BEDŽEVIMA (Na dnu)
==============================================================================
st.markdown("---")
st.subheader("📜 Arhiva pročišćenih misli Agore")
prikazi_samo_moje = st.checkbox("🔍 Prikaži samo moje doprinose", value=False)
arhiva = dohvati_argumente(samo_moje=prikazi_samo_moje, trenutni_korisnik=trenutni_pseudonim)
if arhiva:
for stavka in arhiva:
tekst, datum, ton, tema_zapisa, autor_zapisa = stavka
try:
pojedinacno_suglasje = int(float(ton))
except Exception:
pojedinacno_suglasje = 50
if pojedinacno_suglasje >= 75:
bedz = f"🟢 Konsenzus: {pojedinacno_suglasje}%"
elif pojedinacno_suglasje >= 40:
bedz = f"🟡 Djelomičan: {pojedinacno_suglasje}%"
else:
bedz = f"🔴 Polarizirano: {pojedinacno_suglasje}%"
moj_oznaka = " (Vi) 👤" if autor_zapisa == trenutni_pseudonim else ""
naslov_expandera = f"💬 {autor_zapisa}{moj_oznaka} na temu '{tema_zapisa}' — {bedz} [{datum}]"
with st.expander(naslov_expandera):
st.markdown(f"Udio u društvenom konsenzusu: {pojedinacno_suglasje}%")
st.markdown("---")
st.markdown(f"📝 Globalni zapis (English):")
st.write(tekst)
else:
if prikazi_samo_moje:
st.info("Niste još objavili niti jednu pročišćenu misao s ovog profila.")
else:
st.info("Arhiva je trenutno prazna. Budite prvi čiji će um otključati Agoru!")
