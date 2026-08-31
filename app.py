import os
import time
import json
import re
import random
from datetime import datetime
import streamlit as st
import psycopg2
import plotly.graph_objects as go
from google import genai
from google.genai import errors
from streamlit_javascript import st_javascript

# ==============================================================================
# 1. KONFIGURACIJA STRANICE (Mora biti prva Streamlit naredba)
# ==============================================================================
st.set_page_config(page_title="Agora Web — Protokol Uma", page_icon="🏛️", layout="wide")

# ==============================================================================
# 2. GLOBALNI AI PROMPT
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
# 3. INICIJALIZACIJA AI KLIJENATA
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
# 4. POMOĆNE FUNKCIJE ZA PLOTLY VIZUALIZACIJE
# ==============================================================================
def nacrtaj_indikator_suglasja(trenutno_suglasje):
    """Crta polukružni indikator (Gauge) za postotak društvenog suglasja."""
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=trenutno_suglasje,
        domain={'x':, 'y': [0, 1]},
        gauge={
            'axis': {'range': [0, 100]},
            'bar': {'color': "#1f77b4"},
            'steps': [
                {'range':, 'color': "#ff9999"},     # Crveno za nisko suglasje
                {'range':, 'color': "#ffffcc"},    # Žuto za srednje suglasje
                {'range':, 'color': "#d9f2d9"}    # Zeleno za visoko suglasje
            ]
        }
    ))
    fig.update_layout(height=150, margin=dict(l=10, r=10, t=10, b=10))
    return fig

def nacrtaj_fraktal_uma(analitika, empatija, sinteza):
    """Crta radarni grafikon za analitičke ocjene uma."""
    kategorije = ['Analitičnost', 'Empatija', 'Sinteza']
    vrijednosti = [analitika, empatija, sinteza]
    
    fig = go.Figure(data=go.Scatterpolar(
        r=vrijednosti + [vrijednosti[0]],
        theta=kategorije + [kategorije[0]],
        fill='toself',
        line_color='#1f77b4'
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 10])),
        showlegend=False,
        height=250,
        margin=dict(l=20, r=20, t=20, b=20)
    )
    return fig
# ==============================================================================
# 5. FUNKCIJE ZA OBRADU TEKSTA I EKSTRAKCIJU
# ==============================================================================
def ekstrahiraj_podatke_iz_odgovora(ai_odgovor):
    """Ekstrahira ton i metričke podatke iz strukturiranog AI odgovora."""
    trenutni_ton = "Neutralan"
    metrički_podaci = {"analitika": 5, "empatija": 5, "sinteza": 5, "suglasje": 50}
    
    if not ai_odgovor:
        return trenutni_ton, metrički_podaci
    try:
        json_match = re.search(r'\{.*\}', ai_odgovor, re.DOTALL)
        if json_match:
            podaci = json.loads(json_match.group(0))
            if "analitika" in podaci:
                metrički_podaci = podaci
            elif "metrika" in podaci:
                metrički_podaci = podaci["metrika"]
                
        if "### [1. ANALIZA TONA]" in ai_odgovor:
            dijelovi = ai_odgovor.split("### [1. ANALIZA TONA]")
            if len(dijelovi) > 1:
                tekst_tona = dijelovi[1].split("###")[0].strip()
                if tekst_tona:
                    trenutni_ton = tekst_tona
    except Exception:
        pass
        
    return trenutni_ton, metrički_podaci

# ==============================================================================
# 6. FUNKCIJE ZA POSTGRESQL BAZU PODATAKA
# ==============================================================================
def otvori_vezu():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def inicijaliziraj_bazu():
    conn = None
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS korisnici (
                ip_adresa TEXT PRIMARY KEY,
                pseudonim TEXT NOT NULL,
                datum_registracije TEXT NOT NULL
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS teme (
                id SERIAL PRIMARY KEY,
                naziv TEXT UNIQUE NOT NULL,
                aktivna BOOLEAN DEFAULT TRUE
            )
        """)
        
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
    except Exception as e:
        st.error(f"Greška pri inicijalizaciji baze podataka: {e}")
    finally:
        if conn:
            conn.close()

def dohvati_ili_creiraj_korisnika(ip_adresa):
    conn = None
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        cursor.execute("SELECT pseudonim FROM korisnici WHERE ip_adresa = %s", (ip_adresa,))
        rezultat = cursor.fetchone()
        
        if rezultat:
            pseudonim = rezultat[0]
        else:
            kratki_ip = ip_adresa.split(".")[-1] if ip_adresa and "." in ip_adresa else "X"
            pseudonim = f"Građanin_{kratki_ip}_{random.randint(100, 999)}"
            vrijeme = datetime.now().strftime("%d.%m.%Y.")
            cursor.execute(
                "INSERT INTO korisnici (ip_adresa, pseudonim, datum_registracije) VALUES (%s, %s, %s)",
                (ip_adresa, pseudonim, vrijeme)
            )
            conn.commit()
            st.toast(f"🔑 Kreiran privremeni profil: {pseudonim}")
            
        cursor.close()
        return str(pseudonim)
    except Exception:
        if conn:
            conn.rollback()
        return "Gost_Agore"
    finally:
        if conn:
            conn.close()

def azuriraj_pseudonim(ip_adresa, novi_pseudonim):
    conn = None
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        cursor.execute("UPDATE korisnici SET pseudonim = %s WHERE ip_adresa = %s", (novi_pseudonim, ip_adresa))
        conn.commit()
        cursor.close()
        return True
    except Exception:
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def dohvati_aktivne_teme():
    conn = None
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        cursor.execute("SELECT naziv FROM teme WHERE aktivna = TRUE ORDER BY id ASC")
        teme = [red[0] for red in cursor.fetchall()]
        cursor.close()
        return teme if teme else ["Općenito"]
    except Exception:
        return ["Općenito"]
    finally:
        if conn:
            conn.close()

def dodaj_novu_temu(naziv_teme):
    conn = None
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO teme (naziv) VALUES (%s) ON CONFLICT DO NOTHING", (naziv_teme.strip(),))
        conn.commit()
        cursor.close()
        return True
    except Exception:
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def obrisi_temu(naziv_teme):
    if not naziv_teme or str(naziv_teme).strip() in ["", "Općenito"]:
        return False, "Nije moguće obrisati zadanu temu 'Općenito'!"
        
    conn = None
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        cisti_naziv = str(naziv_teme).strip()
        
        cursor.execute("DELETE FROM argumenti WHERE tema = %s", (cisti_naziv,))
        cursor.execute("DELETE FROM teme WHERE naziv = %s", (cisti_naziv,))
        broj_obrisanih = cursor.rowcount
        
        conn.commit()
        cursor.close()
        
        if broj_obrisanih == 0:
            return False, f"Tema '{cisti_naziv}' nije pronađena u bazi."
        return True, f"Uspješno obrisana tema '{cisti_naziv}'."
    except Exception as e:
        if conn:
            conn.rollback()
        return False, f"Greška pri brisanju: {str(e)}"
    finally:
        if conn:
            conn.close()

def spremi_argument(korisnik, tema, tekst, ton):
    conn = None
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        vrijeme = datetime.now().strftime("%d.%m.%Y. u %H:%M")
        cursor.execute(
            "INSERT INTO argumenti (korisnik, tema, tekst, datum, ton) VALUES (%s, %s, %s, %s, %s)", 
            (korisnik, tema, tekst, vrijeme, ton)
        )
        conn.commit()
        cursor.close()
    except Exception as e:
        st.error(f"Greška pri spremanju u bazu: {e}")
    finally:
        if conn:
            conn.close()

def dohvati_metriku_teme(tema_naziv):
    conn = None
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        cursor.execute("SELECT ton, korisnik FROM argumenti WHERE tema = %s", (tema_naziv,))
        rezultati = cursor.fetchall()
        cursor.close()
        
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
    finally:
        if conn:
            conn.close()

def dohvati_argumente(samo_moje=False, trenutni_korisnik=None):
    conn = None
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        if samo_moje and trenutni_korisnik:
            cursor.execute("SELECT tekst, datum, ton, tema, korisnik FROM argumenti WHERE korisnik = %s ORDER BY id DESC", (trenutni_korisnik,))
        else:
            cursor.execute("SELECT tekst, datum, ton, tema, korisnik FROM argumenti ORDER BY id DESC")
        argumenti = cursor.fetchall()
        cursor.close()
        return argumenti
    except Exception:
        return []
    finally:
        if conn:
            conn.close()

def spremi_analizirani_argument(korisnik, tema, tekst, ton, metrika_dict):
    try:
        if "baza_argumenata" not in st.session_state:
            st.session_state.baza_argumenata = []
        novi_zapis = {
            "korisnik": korisnik,
            "tema": tema,
            "tekst": tekst,
            "ton": ton,
            "metrika": metrika_dict
        }
        st.session_state.baza_argumenata.append(novi_zapis)
        return True
    except Exception as e:
        st.error(f"Greška pri lokalnom spremanju: {e}")
        return False

# Pokretanje inicijalizacije baze podataka
inicijaliziraj_bazu()
# ==============================================================================
# 7. KORISNIČKO SUČELJE (UI) & JAVASCRIPT IDENTIFIKACIJA
# ==============================================================================
st.title("🏛️ AGORA")
st.caption("Web MVP | Centralizirana Cloud Baza | Globalno prevođenje u pozadini")
st.markdown("---")

script_ip = 'await fetch("https://ipify.org").then(r => r.json())'
vratni_ip_objekt = st_javascript(script_ip)
user_ip = "127.0.0.1"

if isinstance(vratni_ip_objekt, dict) and "ip" in vratni_ip_objekt:
    user_ip = vratni_ip_objekt["ip"]

trenutni_pseudonim = dohvati_ili_creiraj_korisnika(user_ip)

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
                
    st.markdown("### 🗑️ Ukloni temu (Admin)")
    lista_za_brisanje = dohvati_aktivne_teme()
    tema_za_uklanjanje = st.selectbox("Odaberi temu za brisanje:", lista_za_brisanje, key="del_tema")
    if st.button("Obriši temu ❌", use_container_width=True):
        uspjeh, poruka = obrisi_temu(tema_za_uklanjanje)
        if uspjeh:
            st.success(poruka)
            time.sleep(0.8)
            st.rerun()
        else:
            st.error(poruka)

if "ai_tekstualni_dio" not in st.session_state:
    st.session_state.ai_tekstualni_dio = ""
if "metrika" not in st.session_state:
    st.session_state.metrika = None
if "status" not in st.session_state:
    st.session_state.status = "ZAKLJUČANO"

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

# ==============================================================================
# 8. LOGIKA OBRADE I PROSLJEĐIVANJA (AI Analiza)
# ==============================================================================
if analiziraj_gumb and user_input:
    with col2:
        with st.spinner("Čuvar Agore analizira vašu misao..."):
            pun_izlaz = None
            
            DINAMICKI_SYSTEM_PROMPT = (
                SYSTEM_PROMPT + 
                f"\n\nTRENUTNA ZADANA TEMA: '{izabrana_tema}'." +
                f"\nKRITIČNO PRAVILO: Ako tekst korisnika bježi s ove teme, " +
                f"ocijeni 'Analitičnost' ocjenom 1, a u sekciji [STATUS] obavezno " +
                f"napiši ZAKLJUČANO s objašnjenjem u tonu da je tema promašena."
            )
            
            if ai_klijent:
                try:
                    response = ai_klijent.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=user_input,
                        config={"system_instruction": DINAMICKI_SYSTEM_PROMPT}
                    )
                    pun_izlaz = response.text
                    st.toast("Analiza uspješno izvršena putem Gemini modela.", icon="🚀")
                except Exception as e:
                    st.warning(f"Primarni model nedostupan ({e}). Pokušavam alternativne resurse...")

            if pun_izlaz:
                try:
                    if "### [METRIKA]" in pun_izlaz:
                        dijelovi_metrike = pun_izlaz.split("### [METRIKA]")
                        glavni_tekst = dijelovi_metrike[0]
                        
                        izvuceni_ton, metrika_data = ekstrahiraj_podatke_iz_odgovora(pun_izlaz)
                        st.session_state.metrika = metrika_data
                        st.session_state.ai_tekstualni_dio = glavni_tekst
                        
                        if "OTKLJUČANO" in glavni_tekst:
                            st.session_state.status = "OTKLJUČANO"
                            engleski_tekst = user_input
                            
                            if "### [TRANSLATION]" in glavni_tekst:
                                dijelovi_prijevoda = glavni_tekst.split("### [TRANSLATION]")
                                st.session_state.ai_tekstualni_dio = dijelovi_prijevoda[0]
                                engleski_tekst = dijelovi_prijevoda[1].strip()
                                
                            postotak_suglasja = metrika_data.get("suglasje", 50)
                            
                            spremi_argument(trenutni_pseudonim, izabrana_tema, engleski_tekst, str(postotak_suglasja))
                            spremi_analizirani_argument(trenutni_pseudonim, izabrana_tema, user_input, izvuceni_ton, metrika_data)
                            
                            st.success("🌍 Misao uspješno prevedena i pohranjena!")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.session_state.status = "ZAKLJUČANO"
                    else:
                        st.session_state.ai_tekstualni_dio = pun_izlaz
                        st.session_state.metrika = None
                except Exception as parse_err:
                    st.error(f"Greška prilikom raščlanjivanja AI odgovora: {parse_err}")

with col2:
    if "status" in st.session_state:
        if st.session_state.status == "OTKLJUČANO":
            st.balloons()
            st.success("🔓 PROČIŠĆAVANJE USPJEŠNO (OTKLJUČANO): Tvoja misao zadovoljava standarde Agore!")
            st.session_state.status = "PRIKAZANO"
        elif st.session_state.status == "ZAKLJUČANO":
            st.error("🔒 BLOKADA (ZAKLJUČANO): Tvoja misao sadrži blokade uma ili pristranosti.")

    if st.session_state.ai_tekstualni_dio:
        st.subheader("💡 Rezultat AI Analize")
        st.markdown(st.session_state.ai_tekstualni_dio)
        
    if st.session_state.metrika:
        st.subheader("📊 Fraktal Vašeg Uma")
        m = st.session_state.metrika
        fig = nacrtaj_fraktal_uma(m.get("analitika", 5), m.get("empatija", 5), m.get("sinteza", 5))
        st.plotly_chart(fig, use_container_width=True)

# ==============================================================================
# 10. ARHIVA PROČIŠĆENIH MISLI S BEDŽEVIMA (Na dnu)
# ==============================================================================
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
