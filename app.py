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
def ekstrahiraj_podatke_iz_odgovora(ai_odgovor):
    """Ekstrahira ton i metričke podatke iz strukturiranog AI odgovora."""
    trenutni_ton = "Neutralan"
    metrički_podaci = {"Logika": 5, "Retorika": 5, "Objektivnost": 5}
    
    if not ai_odgovor:
        return trenutni_ton, metrički_podaci
    try:
        json_match = re.search(r'\{.*\}', ai_odgovor, re.DOTALL)
        if json_match:
            podaci = json.loads(json_match.group(0))
            trenutni_ton = podaci.get("ton", podaci.get("Ton", trenutni_ton))
            metrički_podaci = podaci.get("metrika", podaci.get("metrike", metrički_podaci))
            return trenutni_ton, metrički_podaci
        
        lines = ai_odgovor.split("\n")
        for line in lines:
            if "ton:" in line.lower():
                trenutni_ton = line.split(":")[-1].strip().strip('"').strip("'")
            for kljuc in metrički_podaci.keys():
                if kljuc.lower() in line.lower():
                    brojevi = re.findall(r'\d+', line)
                    if brojevi:
                        metrički_podaci[kljuc] = int(brojevi[0])
    except Exception:
        pass
        
    return trenutni_ton, metrički_podaci


def spremi_analizirani_argument(korisnik, tema, tekst, ton, metrika_dict):
    """
    Sprema analizirani argument u Streamlit Session State (ili bazu podataka).
    Prilagodite ovaj kod ako koristite pravu bazu podataka (SQL, Firebase i sl.).
    """
    try:
        # Inicijalizacija baze u session state-u ako ne postoji
        if "baza_argumenata" not in st.session_state:
            st.session_state.baza_argumenata = []
            
        # Kreiranje zapisa
        novi_zapis = {
            "korisnik": korisnik,
            "tema": tema,
            "tekst": tekst,
            "ton": ton,
            "metrika": metrika_dict
        }
        
        # Spremanje zapisa
        st.session_state.baza_argumenata.append(novi_zapis)
        return True
    except Exception as e:
        st.error(f"Greška pri spremanju argumenta: {e}")
        return False
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
 

def obrisi_temu(naziv_teme):
    """Briše selektiranu temu i njezine argumente iz baze podataka."""
    # Prvo pokrećemo automatsko čišćenje anomalija
    ocisti_prazne_teme()
    
    if not naziv_teme or str(naziv_teme).strip() in ["", "Općenito"]:
        return False, "Nije moguće obrisati zadanu temu 'Općenito' ili praznu temu na ovaj način!"
        
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        
        # Slanje čistog stringa bez skrivenih razmaka
        cisti_naziv = str(naziv_teme).strip()
        
        # 1. Brisanje argumenata
        cursor.execute("DELETE FROM argumenti WHERE tema = %s", (cisti_naziv,))
        # 2. Brisanje teme
        cursor.execute("DELETE FROM teme WHERE naziv = %s", (cisti_naziv,))
        
        conn.commit()
        
        # Provjera je li išta stvarno obrisano
        broj_obrisanih = cursor.rowcount
        cursor.close()
        conn.close()
        
        if broj_obrisanih == 0:
            return False, f"Tema '{cisti_naziv}' nije pronađena u bazi pod tim točnim nazivom."
            
        return True, f"Uspješno obrisana tema '{cisti_naziv}'."
    except Exception as e:
        return False, f"Greška pri brisanju: {str(e)}"


def dodaj_novu_temu(naziv_teme):
    """Sigurno upisuje novu temu i strogo odbija prazne i neispravne unose."""
    if naziv_teme is None:
        return False, "Naziv teme ne može biti prazan!"
        
    # Čišćenje ulaza
    naziv_teme = str(naziv_teme).strip()
    
    # Blokada za prazne tekstove ili ostatke softverskih grešaka
    if naziv_teme in ["", "()", "None", "('',)"]:
        return False, "Unijeli ste nevažeći ili prazan naziv teme!"
        
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM teme WHERE LOWER(naziv) = LOWER(%s)", (naziv_teme,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return False, "Ova tema već postoji u izborniku!"
            
        cursor.execute("INSERT INTO teme (naziv, aktivna) VALUES (%s, TRUE)", (naziv_teme,))
        conn.commit()
        cursor.close()
        conn.close()
        return True, f"Uspješno dodana tema: '{naziv_teme}'"
    except Exception as e:
        return False, f"Greška u bazi podataka: {str(e)}"


def otvori_vezu():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def inicijaliziraj_bazu():
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        
        # ... (ostatak vašeg koda za kreiranje tablica korisnici, teme, argumenti) ...
        
        # POPRAVAK: Čišćenje anomalija izvršavamo isključivo OVDJE, unutar inicijalizacije
        neispravni_nazivi = ['', ' ', '()', "('',)", "()", "None"]
        cursor.execute("""
            DELETE FROM teme 
            WHERE TRIM(naziv) = '' 
               OR naziv IS NULL 
               OR naziv IN %s
        """, (tuple(neispravni_nazivi),))
        
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Kritična greška u bazi podataka: {str(e)}")

        st.error("Upozorenje: Poteškoće pri povezivanju ili inicijalizaciji baze podataka.")

        
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
                ("Religija kao zabluda ili izvor nade",) 
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
    """Dohvaća isključivo tekstualne nazive tema iz baze."""
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        cursor.execute("SELECT naziv FROM teme WHERE aktivna = TRUE ORDER BY id ASC")
        # POPRAVAK: Uzimamo prvi element red[0] kako bismo dobili čisti tekst, a ne tuple (red,)
        teme = [red[0] for red in cursor.fetchall()]
        cursor.close()
        conn.close()
        return teme
    except Exception:
        return ["Općenito"]

def dodaj_novu_temu(naziv_teme):
    """Upisuje novu temu u bazu podataka uz provjeru tipa podataka."""
    # POPRAVAK: Ako je iz bilo kojeg razloga proslijeđen tuple ili krivac, pretvaramo ga u string
    if isinstance(naziv_teme, (tuple, list)) and len(naziv_teme) > 0:
        naziv_teme = str(naziv_teme[0])
    else:
        naziv_teme = str(naziv_teme)

    if not naziv_teme.strip():
        return False, "Naziv teme ne može biti prazan!"
        
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        
        # Provjera postoji li već tema
        cursor.execute("SELECT id FROM teme WHERE naziv = %s", (naziv_teme.strip(),))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return False, "Ova tema već postoji u izborniku!"
            
        # Unos nove teme
        cursor.execute("INSERT INTO teme (naziv, aktivna) VALUES (%s, TRUE)", (naziv_teme.strip(),))
        conn.commit()
        cursor.close()
        conn.close()
        return True, f"Uspješno dodana tema: '{naziv_teme.strip()}'"
    except Exception as e:
        return False, f"Greška u bazi podataka: {str(e)}"


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
    """
    Šalje tekst na analizu koristeći službeno dostupne modele najnovije generacije.
    Ako je primarni model (gemini-3.7-flash) preopterećen, automatski se prebacuje 
    na stabilni zamjenski model (gemini-3.6-flash).
    """
    if not ai_klijent:
        st.error("AI klijent nije inicijaliziran. Provjerite API ključ.")
        return None

    # POPRAVLJENO: Uklonjen umirovljeni gemini-1.5-flash i postavljeni aktualni modeli generacije 3
    modeli_za_pokusaj = ['gemini-3.7-flash', 'gemini-3.6-flash']

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
            # Ako je greška 503 (visoka potražnja) ili privremeni prekid, a imamo još modela, nastavi petlju
            if ("503" in str(e) or "404" in str(e)) and trenutni_model != modeli_za_pokusaj[-1]:
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


# 1. Polje za unos mora definirati varijablu pod nazivom 'korisnikov_tekst'
korisnikov_tekst = st.text_area(
    "Unesite svoju misao za Čuvara Agore:", 
    placeholder="Napišite svoj argument ovdje..."
)

# 2. Gumb za slanje na analizu
if st.button("Uputi na analizu"):
    if korisnikov_tekst.strip() and ai_klijent:
        with st.spinner("Čuvar Agore pročišćava vašu misao..."):
            try:
                # Poziv Gemini API-ja
                response = ai_klijent.models.generate_content(
                    model='gemini-3.6-flash',
                    contents=korisnikov_tekst,
                    config={"system_instruction": SYSTEM_PROMPT}
                )
                
                ai_odgovor = response.text
                st.write(ai_odgovor) # Prikaz strukturiranog teksta korisniku
                
                # Ekstrakcija tona i metričkih podataka
                trenutni_ton, metrički_podaci = ekstrahiraj_podatke_iz_odgovora(ai_odgovor)
                
                # Poziv funkcije za spremanje
                uspjeh = spremi_analizirani_argument(
                    korisnik=trenutni_korisnik,
                    tema=odabrana_tema,
                    tekst=korisnikov_tekst,
                    ton=trenutni_ton,
                    metrika_dict=metrički_podaci
                )
                
                if uspjeh:
                    st.success("Vaša misao je uspješno obrađena i upisana u kolektivnu analitiku!")
                    time.sleep(1)
                    st.rerun() # Osvježava ekran
                    
            except Exception as e:
                st.error(f"Greška tijekom komunikacije s AI: {e}")

 # Osvježava ekran kako bi povukao nove grafikone
                    
            except Exception as e:
                st.error(f"Greška tijekom komunikacije s AI: {e}")
# 2. Gumb za slanje na analizu
# 2. Gumb za slanje na analizu
if st.button("Uputi na analizu sada"):
    if korisnikov_tekst.strip() and ai_klijent:
        with st.spinner("Čuvar Agore pročišćava vašu misao..."):
            try:
                # Poziv Gemini API-ja
                response = ai_klijent.models.generate_content(
                    model='gemini-3.6-flash',
                    contents=korisnikov_tekst,
                    config={"system_instruction": SYSTEM_PROMPT}
                )
                
                ai_odgovor = response.text
                
                # Privremeno spremamo odgovor u session state da ne nestane nakon st.rerun()
                st.session_state.zadnji_ai_odgovor = ai_odgovor 
                
                # Ekstrakcija tona i metričkih podataka
                trenutni_ton, metrički_podaci = ekstrahiraj_podatke_iz_odgovora(ai_odgovor)
                
                # Određivanje statusa na temelju metričkih podataka
                procijenjena_logika = metrički_podaci.get("Logika", 5)
                status = "OTKLJUČANO" if procijenjena_logika >= 5 else "ZAKLJUČANO"
                
                # Poziv funkcije za spremanje (rješava NameError za 'uspjeh')
                uspjeh = spremi_analizirani_argument(
                    trenutni_korisnik, 
                    odabrana_tema, 
                    korisnikov_tekst, 
                    trenutni_ton, 
                    metrički_podaci
                )
                
                if uspjeh:
                    st.success("Vaša misao je uspješno obrađena i upisana u kolektivnu analitiku!")
                    
                    st.divider()
                    if status == "OTKLJUČANO":
                        st.balloons()
                        st.success("🔓 PROČIŠĆAVANJE USPJEŠNO (OTKLJUČANO): Tvoja misao zadovoljava standarde Agore!")
                    else:
                        st.error("🔒 BLOKADA (ZAKLJUČANO): Tvoja misao sadrži blokade uma ili pristranosti.")
                    
                    time.sleep(2)
                    st.rerun()
                    
            except Exception as e:
                st.error(f"Greška tijekom komunikacije s AI: {e}")


if status == "OTKLJUČANO":
        st.balloons()
        st.success("🔓 PROČIŠĆAVANJE USPJEŠNO (OTKLJUČANO): Tvoja misao zadovoljava standarde Agore i trajno je zapisana u protokole rasprave!")
else:
        st.error("🔒 BLOKADA (ZAKLJUČANO): Tvoja misao sadrži blokade uma ili pristranosti. Zapisana je u arhivu radi daljnjeg rada na sebi.")

# Prikaz povijesti i analitike (izvan gumba, vidljivo uvijek)
                
if "baza_argumenata" in st.session_state and st.session_state.baza_argumenata:
       st.subheader("📊 Kolektivna analitika i povijest misli")
    
    # Prikazujemo zadnju unesenu misao i njezinu analizu
       zadnji_zapis = st.session_state.baza_argumenata[-1]
    
with st.expander("🔍 Pogledaj zadnju analizu", expanded=True):
     st.write(f"**Ton:** {zadnji_zapis['ton']}")
     st.write("**Metrike:**", zadnji_zapis['metrika'])
        
    # Ovdje možete dodati vaš postojeći kod za iscrtavanje grafikona
    # koji koristi podatke iz st.session_state.baza_argumenata


# ==============================================================================
# 8. ADMINISTRATORSKI PANEL (Upravljanje temama - Nadograđeno)
# ==============================================================================
st.sidebar.markdown("---")
with st.sidebar.expander("🔐 Administratorske postavke", expanded=False):
    admin_lozinka = st.text_input("Unesite administratorsku lozinku:", type="password")
    
    if admin_lozinka == "agora2026":
        st.success("Pristup odobren!")
        
               # --- SEKCIJA 1: DODAVANJE NOVE TEME ---
        st.write("### ➕ Dodaj novu temu")
        nova_tema_input = st.text_input("Naziv nove teme:", placeholder="Npr. Sloboda govora vs. Govor mržnje")
        
        if st.button("Spremi temu", use_container_width=True):
            # Sve linije ispod moraju biti uvučene za točno 4 razmaka više od 'if' izjave
            uspjeh, poruka = dodaj_novu_temu(nova_tema_input)
            if uspjeh:
                st.toast(poruka, icon="✅")
                time.sleep(1)
                st.rerun()
            else:
                st.error(poruka)


                
        st.write("---")
        
        # --- SEKCIJA 2: BRISANJE POSTOJEĆE TEME ---
        st.write("### 🗑️ Obriši temu")
        sve_teme_za_brisanje = dohvati_aktivne_teme()
        
        # Filtriramo privremenu/glavnu temu ako ne želimo da se slučajno obriše
        opcije_brisanja = [t for t in sve_teme_za_brisanje if t != "Općenito"]
        
        if opcije_brisanja:
            tema_za_uklanjanje = st.selectbox("Odaberite temu za trajno brisanje:", opcije_brisanja, key="delete_select")
            
            # Sigurnosna kvačica kako se ne bi obrisalo slučajnim klikom
            potvrda_brisanja = st.checkbox("Potvrđujem da želim trajno obrisati ovu temu i sve njezine poruke.")
            
            if st.button("🚨 TRAJNO OBRIŠI", use_container_width=True, type="primary"):
                if potvrda_brisanja:
                    uspjeh, poruka = obrisi_temu(tema_za_uklanjanje)
                    if uspjeh:
                        st.toast(poruka, icon="🗑️")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(poruka)
                else:
                    st.warning("Morate označiti kućicu za potvrdu prije brisanja!")
        else:
            st.info("Nema tema dostupnih za brisanje.")
            
    elif admin_lozinka != "":
        st.error("Pogrešna lozinka. Pristup odbijen.")
