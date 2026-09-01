# ==============================================================================
# 1. UVOZ BIBLIOTEKA
# ==============================================================================
import os
import time
import json
import re
import uuid
from datetime import datetime
import streamlit as st
import psycopg2
import plotly.graph_objects as go
from google import genai
from google.genai import errors
def ekstrahiraj_podatke_iz_odgovora(ai_odgovor):
    """Ekstrahira ton i metričke podatke iz strukturiranog AI odgovora."""
    trenutni_ton = "Neutralan"
    metrički_podaci = {"analitika": 0, "empatija": 0, "sinteza": 0, "suglasje": 0}
    
    if not ai_odgovor:
        return trenutni_ton, metrički_podaci
    try:
        ton_mec = re.search(r"### \[1\. (?:ANALIZA TONA|TONE ANALYSIS)\]\s*\n+(.+)", ai_odgovor)
        if ton_mec:
            trenutni_ton = ton_mec.group(1).strip()
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
    """Trajno sprema argument u PostgreSQL te ga dodaje u trenutnu sesiju."""
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO argumenti (korisnik, tema, tekst, datum, ton, metrika)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                korisnik,
                tema,
                tekst,
                datetime.now().strftime("%d.%m.%Y. %H:%M"),
                ton,
                json.dumps(metrika_dict),
            ),
        )
        conn.commit()
        cursor.close()
        conn.close()

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
        st.error(f"Greška pri spremanju argumenta: {e}")
        return False
# ==============================================================================
# 2. KONFIGURACIJA STRANICE (Mora biti prva Streamlit naredba)
# ==============================================================================
st.set_page_config(page_title="Agora Web — Protokol Uma", page_icon="🏛️", layout="wide")

PRIJEVOIDI = {
    "hr": {
        "title": "🏛️ Agora Web — Protokol Uma",
        "quote": "Čim si se rodio postao si prošlost, ako imaš sreće da tvoj prezent potraje iskoristi ga da humano oblkuje budućnost.",
        "welcome": "Dobrodošli natrag, {user}",
        "intro": "Ovaj sustav nadzire Čuvar Agore. Svaki uneseni tekst bit će analiziran na analitičnost, empatiju i sintezu prije nego što bude trajno zapisan u protokole.",
        "topic": "Odaberite temu za raspravu:", "thought": "Unesite svoju misao za Čuvara Agore:",
        "placeholder": "Napišite svoj argument ovdje...", "submit": "Uputi na analizu",
        "empty": "Najprije unesite tekst za analizu.", "processing": "Čuvar Agore pročišćava vašu misao...",
        "saved": "Vaša misao je uspješno obrađena i trajno zapisana u protokole.",
        "confirmed": "#### 🔓 Zapis potvrđen", "confirmed_text": "Pročišćavanje je uspješno. Misao zadovoljava standarde Agore i trajno je zapisana u protokole rasprave.",
        "locked": "🔒 BLOKADA: Tvoja misao sadrži blokade uma ili pristranosti. Zapisana je u arhivu radi daljnjeg rada na sebi.",
        "history": "📊 Kolektivna analitika i povijest misli", "last": "### 🔍 Zadnja analiza Čuvara Agore",
        "global_agreement": "🌍 Globalno suglasje", "agreement_description": "Prosjek svih analiziranih misli kroz aktivne teme", "no_agreement_data": "Za globalni pokazatelj suglasja još nema analiziranih misli.", "records": "zapisa",
        "submitted": "Unesena misao:", "tone": "Emocionalni ton:", "scores": "Analitičke ocjene:",
        "no_metrics": "Metrički podaci nisu dostupni za ovaj zapis.", "archive": "📚 Pregledaj cjelokupnu arhivu misli",
        "thought_number": "### 🧠 Misao #{number}", "author": "Autor", "topic_label": "Tema", "argument": "Argument:", "anonymous": "Anonimno",
        "admin": "🔐 Administratorske postavke", "password": "Unesite administratorsku lozinku:", "access": "Pristup odobren!",
        "add_topic": "### ➕ Dodaj novu temu", "topic_name": "Naziv nove teme:", "topic_example": "Npr. Sloboda govora vs. Govor mržnje",
        "save_topic": "Spremi temu", "delete_topic": "### 🗑️ Obriši temu", "choose_delete": "Odaberite temu za trajno brisanje:",
        "confirm_delete": "Potvrđujem da želim trajno obrisati ovu temu i sve njezine poruke.", "delete": "🚨 TRAJNO OBRIŠI",
        "must_confirm": "Morate označiti kućicu za potvrdu prije brisanja!", "no_topics": "Nema tema dostupnih za brisanje.",
        "wrong_password": "Pogrešna lozinka. Pristup odbijen.", "admin_secret": "Administratorski panel zahtijeva `ADMIN_PASSWORD` u Streamlit Secrets.",
    },
    "en": {
        "title": "🏛️ Agora Web — Protocol of Mind", "welcome": "Welcome back, {user}",
        "quote": "The moment you were born, you became the past; if you are lucky enough for your present to last, use it to shape the future humanely.",
        "intro": "This system is overseen by the Guardian of Agora. Each submitted text is analysed for analytical thinking, empathy, and synthesis before it is permanently recorded in the protocols.",
        "topic": "Choose a discussion topic:", "thought": "Submit your thought to the Guardian of Agora:",
        "placeholder": "Write your argument here...", "submit": "Submit for analysis", "empty": "Enter text for analysis first.",
        "processing": "The Guardian of Agora is refining your thought...", "saved": "Your thought has been processed and permanently recorded in the protocols.",
        "confirmed": "#### 🔓 Record confirmed", "confirmed_text": "The refinement was successful. Your thought meets Agora's standards and has been permanently recorded in the discussion protocols.",
        "locked": "🔒 BLOCKED: Your thought contains cognitive barriers or bias. It has been archived for further reflection.",
        "history": "📊 Collective analytics and thought history", "last": "### 🔍 Latest Guardian analysis", "submitted": "Submitted thought:",
        "global_agreement": "🌍 Global agreement", "agreement_description": "Average of all analysed thoughts across active topics", "no_agreement_data": "There are no analysed thoughts yet for the global agreement indicator.", "records": "records",
        "tone": "Emotional tone:", "scores": "Analytical scores:", "no_metrics": "Metric data is unavailable for this record.",
        "archive": "📚 Browse the complete thought archive", "thought_number": "### 🧠 Thought #{number}", "author": "Author", "topic_label": "Topic", "argument": "Argument:", "anonymous": "Anonymous",
        "admin": "🔐 Administrator settings", "password": "Enter the administrator password:", "access": "Access granted!", "add_topic": "### ➕ Add a new topic",
        "topic_name": "New topic name:", "topic_example": "E.g. Freedom of speech vs. hate speech", "save_topic": "Save topic", "delete_topic": "### 🗑️ Delete a topic",
        "choose_delete": "Choose a topic to permanently delete:", "confirm_delete": "I confirm that I want to permanently delete this topic and all its messages.",
        "delete": "🚨 PERMANENTLY DELETE", "must_confirm": "Select the confirmation box before deleting.", "no_topics": "No topics are available for deletion.",
        "wrong_password": "Incorrect password. Access denied.", "admin_secret": "The administrator panel requires `ADMIN_PASSWORD` in Streamlit Secrets.",
    },
}
jezik = st.sidebar.selectbox("Jezik / Language", ["hr", "en"], format_func=lambda kod: "Hrvatski" if kod == "hr" else "English", key="jezik_agore")
t = PRIJEVOIDI[jezik]
NAZIVI_METRIKA = {
    "hr": {"analitika": "Analitičnost", "empatija": "Empatija", "sinteza": "Sinteza", "suglasje": "Suglasje"},
    "en": {"analitika": "Analysis", "empatija": "Empathy", "sinteza": "Synthesis", "suglasje": "Agreement"},
}
PRIJEVOIDI_TEMA = {
    "Općenito": "General",
    "Etičke granice genetskog inženjeringa": "Ethical boundaries of genetic engineering",
    "Utjecaj umjetne inteligencije na privatnost": "The impact of artificial intelligence on privacy",
    "Budućnost decentraliziranog upravljanja društvom": "The future of decentralized governance in society",
    "Religija kao zabluda ili izvor nade": "Religion: delusion or source of hope",
}


def prikazi_temu(naziv_teme):
    """Prevodi ugrađene teme samo u sučelju; baza koristi izvorni naziv."""
    return PRIJEVOIDI_TEMA.get(naziv_teme, naziv_teme) if jezik == "en" else naziv_teme

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

if jezik == "en":
    SYSTEM_PROMPT = """
Role: You are the "Guardian of Agora", an advanced AI system for refining human thought.
Do not take part in the debate. Analyse only the user's text, which can be in any language.

Rate the text from 1 to 10 for analytical thinking (logic, evidence, consistency),
empathy (understanding other sides and measured language), and synthesis (finding common ground).
Write every explanatory part in English and use exactly this structure. Do not wrap JSON in a code block:

### [1. TONE ANALYSIS]
(One sentence about the tone.)

### [2. OBSERVED COGNITIVE BARRIERS]
- **[Fallacy or barrier]**: (Brief explanation.)

### [3. REFINEMENT SUGGESTION]
(An example of a revised text.)

### [STATUS]
(Write only LOCKED or UNLOCKED.)

### [TRANSLATION]
(A complete English translation of the original text. Leave empty if status is LOCKED.)

### [METRICS]
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
    # Ako nemate definiranu funkciju ocisti_prazne_teme(), 
    # ostavite je zakomentiranu s '#' kako ne biste dobili NameError
    # ocisti_prazne_teme()
    
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
                ton TEXT,
                metrika JSONB
            )
        """)
        cursor.execute("ALTER TABLE argumenti ADD COLUMN IF NOT EXISTS metrika JSONB")
        
        # 4. Umetanje početnih tema ako je tablica prazna
        cursor.execute("SELECT COUNT(*) FROM teme")
        rezultat = cursor.fetchone()
        
        if rezultat and rezultat[0] == 0:
            pocetne_teme = [
                ("Etičke granice genetskog inženjeringa",),
                ("Utjecaj umjetne inteligencije na privatnost",),
                ("Budućnost decentraliziranog upravljanja društvom",),
                ("Religija kao zabluda ili izvor nade",),
            ]
            cursor.executemany("INSERT INTO teme (naziv) VALUES (%s)", pocetne_teme)
        neispravni_nazivi = ('', ' ', '()', "('',)", 'None')
        cursor.execute(
            "DELETE FROM teme WHERE TRIM(naziv) = '' OR naziv IS NULL OR naziv = ANY(%s)",
            (list(neispravni_nazivi),),
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Kritična greška u bazi podataka: {str(e)}")
        st.error("Upozorenje: Poteškoće pri povezivanju ili inicijalizaciji baze podataka.")


def dohvati_ili_kreiraj_korisnika(ip_adresa):
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        cursor.execute("SELECT pseudonim FROM korisnici WHERE ip_adresa = %s", (ip_adresa,))
        rezultat = cursor.fetchone()
        
        if rezultat:
            pseudonim = rezultat[0]
        else:
            kratki_id = str(ip_adresa).rsplit("_", 1)[-1][:6]
            pseudonim = f"Građanin_{kratki_id}"
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

def dohvati_metriku_teme(tema_naziv):
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        cursor.execute("SELECT metrika, korisnik FROM argumenti WHERE tema = %s", (tema_naziv,))
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
                    podaci = r[0] if isinstance(r[0], dict) else json.loads(r[0])
                    vrijednosti.append(sum(podaci.values()) / len(podaci))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
                
        prosjek = round(sum(vrijednosti) / len(vrijednosti)) if vrijednosti else 0
        return prosjek, broj_sudionika
    except Exception:
        return 0, 0


def dohvati_globalno_suglasje(teme):
    """Vraća prosječno suglasje i broj zapisa za sve aktivne teme."""
    if not teme:
        return None, 0
    try:
        conn = otvori_vezu()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT AVG((metrika->>'suglasje')::numeric), COUNT(*)
            FROM argumenti
            WHERE tema = ANY(%s)
              AND metrika ? 'suglasje'
            """,
            (teme,),
        )
        prosjek, broj_zapisa = cursor.fetchone()
        cursor.close()
        conn.close()
        return (round(float(prosjek), 1) if prosjek is not None else None), broj_zapisa
    except Exception:
        return None, 0

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
        # 1. Izvlačenje JSON-a iz sekcije ### [METRIKA] ili ### [METRICS]
        metrika_mec = re.search(r"### \[(?:METRIKA|METRICS)\]\s*(.*)", tekst_odgovora, re.DOTALL)
        if metrika_mec:
            json_tekst = metrika_mec.group(1).strip()
            json_tekst = re.sub(r"```[a-zA-Z]*", "", json_tekst).strip()
            json_tekst = json_tekst.replace("```", "").strip()
            json_mec = re.search(r"\{.*?\}", json_tekst, re.DOTALL)
            if json_mec:
                ucitana_metrika = json.loads(json_mec.group(0))
                for kljuc in metrika:
                    vrijednost = ucitana_metrika.get(kljuc, metrika[kljuc])
                    metrika[kljuc] = max(0, min(10, int(vrijednost)))
            
        # 2. Izvlačenje statusa iz sekcije ### [STATUS]
        status_mec = re.search(r"### \[STATUS\]\s*\n*(ZAKLJUČANO|OTKLJUČANO|LOCKED|UNLOCKED)", tekst_odgovora, re.IGNORECASE)
        if status_mec:
            procitani_status = status_mec.group(1).upper().strip()
            status = "OTKLJUČANO" if procitani_status == "UNLOCKED" else "ZAKLJUČANO" if procitani_status == "LOCKED" else procitani_status
            
    except Exception:
        st.warning("⚠️ Čuvar Agore je vratio nestandardan format metrike, ali tekst je obrađen.")
        
    return metrika, status

# ==============================================================================
# 7. GLAVNO IZVRŠAVANJE I STREAMLIT UI
# ==============================================================================
# Inicijalizacija baze na startu
inicijaliziraj_bazu()

# Stabilni anonimni identifikator po Streamlit sesiji. Javni IP poslužitelja ne
# razlikuje stvarne posjetitelje aplikacije i ne treba ga slati vanjskom servisu.
if "anonimni_id" not in st.session_state:
    st.session_state.anonimni_id = f"sesija_{uuid.uuid4()}"
ip_adresa = st.session_state.anonimni_id

# Dohvaćanje ili kreiranje pseudonima iz baze
trenutni_korisnik = dohvati_ili_kreiraj_korisnika(ip_adresa)

# Prikaz glavnog sučelja
st.title(t["title"])
st.markdown(
    "<p style='color: #FFD700; font-size: 1.1rem; font-weight: 700;'>"
    f"{t['quote']}</p>",
    unsafe_allow_html=True,
)
st.subheader(t["welcome"].format(user=trenutni_korisnik))

st.markdown(t["intro"])

# Izbornik za odabir teme rasprave
aktivne_teme = dohvati_aktivne_teme()
teme_za_prikaz = {prikazi_temu(tema): tema for tema in aktivne_teme}
odabrana_tema_prikaz = st.selectbox(
    t["topic"],
    list(teme_za_prikaz),
    key="selectbox_izbor_teme_agora"
)
odabrana_tema = teme_za_prikaz[odabrana_tema_prikaz]


# 1. Polje za unos mora definirati varijablu pod nazivom 'korisnikov_tekst'
korisnikov_tekst = st.text_area(
    t["thought"],
    placeholder=t["placeholder"]
)

# 2. Gumb za slanje na analizu
status = None
if st.button(t["submit"]):
    if not korisnikov_tekst.strip():
        st.warning(t["empty"])
    elif ai_klijent:
        with st.spinner(t["processing"]):
            try:
                ai_odgovor = analiziraj_tekst_s_gemini(korisnikov_tekst)
                if ai_odgovor:
                    st.write(ai_odgovor)
                    trenutni_ton, _ = ekstrahiraj_podatke_iz_odgovora(ai_odgovor)
                    metrički_podaci, analizirani_status = parsiraj_metriku_i_status(ai_odgovor)
                    uspjeh = spremi_analizirani_argument(
                        korisnik=trenutni_korisnik,
                        tema=odabrana_tema,
                        tekst=korisnikov_tekst,
                        ton=trenutni_ton,
                        metrika_dict=metrički_podaci,
                    )
                    if uspjeh:
                        status = analizirani_status
                        st.success(t["saved"])
            except Exception as e:
                st.error(f"Greška tijekom komunikacije s AI: {e}")


if status == "OTKLJUČANO":
    with st.container(border=True):
        st.markdown(t["confirmed"])
        st.caption(t["confirmed_text"])
elif status == "ZAKLJUČANO":
    st.error(t["locked"])

# Prikaz povijesti i analitike (izvan gumba, vidljivo uvijek)
                
if "baza_argumenata" in st.session_state and st.session_state.baza_argumenata:
    st.markdown("---")
    st.subheader(t["history"])
    
    # Dohvaćamo zadnji zapis
    zadnji_zapis = st.session_state.baza_argumenata[-1]
    ton_za_prikaz = zadnji_zapis.get('ton', zadnji_zapis.get('Ton', 'Neutralan'))
    metrike_za_prikaz = zadnji_zapis.get('metrika', zadnji_zapis.get('metrike', {}))
    
    # 1. Zasebna istaknuta sekcija za ZADNJU analizu (Moderni kontejner)
    with st.container(border=True):
        st.markdown(t["last"])
        
        # Prikaz teksta koji je analiziran u obliku citata
        tekst_misli = zadnji_zapis.get('tekst', 'Nema teksta')
        st.markdown(f"**{t['submitted']}**\n> *{tekst_misli}*")
        
        # Prikaz Tona s vizualnom značkom (badge)
        st.markdown(f"**{t['tone']}** `{ton_za_prikaz}`")
        
        # Dinamički prikaz metrika u stupcima pomoću st.metric kartica
        if metrike_za_prikaz:
            st.markdown(f"**{t['scores']}**")
            # Stvaramo onoliko stupaca koliko ima metričkih pokazatelja (Logika, Retorika...)
            stupci = st.columns(len(metrike_za_prikaz))
            
            for i, (kljuc, vrijednost) in enumerate(metrike_za_prikaz.items()):
                with stupci[i]:
                    # Prikazuje lijepu karticu s nazivom metrike i ocjenom (npr. 8/10)
                    st.metric(label=NAZIVI_METRIKA[jezik].get(kljuc, kljuc), value=f"{vrijednost} / 10")
        else:
            st.info(t["no_metrics"])

       # 2. Arhiva/Povijest svih prethodnih misli (Sada uključuje sve zapise)
    with st.expander(t["archive"], expanded=False):
        # Uzimamo sve zapise i okrećemo redoslijed da najnoviji bude na vrhu
        sve_misli = list(reversed(st.session_state.baza_argumenata))
        ukupno_zapisa = len(sve_misli)
        
        for indeks, zapis in enumerate(sve_misli):
            # Računamo stvarni redni broj misli iz baze
            redni_broj = ukupno_zapisa - indeks
            
            # Koristimo st.chat_message ili manji uokvireni kontejner za svaku stariju misao
            with st.container(border=True):
                st.markdown(t["thought_number"].format(number=redni_broj))
                naziv_teme = prikazi_temu(zapis.get('tema', 'Općenito'))
                st.caption(f"👥 **{t['author']}:** {zapis.get('korisnik', t['anonymous'])} | 📌 **{t['topic_label']}:** {naziv_teme}")
                
                st.markdown(f"**{t['argument']}**\n> *{zapis.get('tekst', '')}*")
                
                # Prikaz tona i kratkih rezultata
                t_ton = zapis.get('ton', zapis.get('Ton', 'Neutralan'))
                m_metrike = zapis.get('metrika', zapis.get('metrike', {}))
                metrike_linija = "  •  ".join([f"**{NAZIVI_METRIKA[jezik].get(k, k)}**: {v}/10" for k, v in m_metrike.items()])
                
                st.markdown(f"🎭 **{t['tone']}** `{t_ton}`")
                if metrike_linija:
                    st.markdown(f"📈 **{t['scores']}** {metrike_linija}")


st.markdown("---")
st.subheader(t["global_agreement"])
globalno_suglasje, broj_analiza = dohvati_globalno_suglasje(aktivne_teme)

if globalno_suglasje is None:
    st.info(t["no_agreement_data"])
else:
    pozicija_pokazivaca = max(0, min(100, globalno_suglasje * 10))
    st.caption(f"{t['agreement_description']} · {broj_analiza} {t['records']} · {globalno_suglasje:.1f} / 10")
    st.markdown(
        f"""
        <div style="position: relative; height: 26px; margin: 0.4rem 0 0.2rem; border-radius: 999px;
                    background: linear-gradient(90deg, #b42318 0%, #f2c94c 50%, #228b4e 100%);">
            <div style="position: absolute; left: calc({pozicija_pokazivaca}% - 2px); top: -6px; width: 4px;
                        height: 38px; border-radius: 2px; background: #ffffff;
                        box-shadow: 0 0 0 2px rgba(0, 0, 0, 0.35);"></div>
        </div>
        <div style="display: flex; justify-content: space-between; color: #808495; font-size: 0.8rem;">
            <span>0 · {"Nisko" if jezik == "hr" else "Low"}</span>
            <span>5 · {"Srednje" if jezik == "hr" else "Moderate"}</span>
            <span>10 · {"Visoko" if jezik == "hr" else "High"}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )



        
# ============================================================================== 
# 8. ADMINISTRATORSKI PANEL (Upravljanje temama - Nadograđeno)
# ==============================================================================
st.sidebar.markdown("---")
with st.sidebar.expander(t["admin"], expanded=False):
    admin_lozinka = st.text_input(t["password"], type="password")
    admin_zaporka = st.secrets.get("ADMIN_PASSWORD")

    if admin_zaporka and admin_lozinka == admin_zaporka:
        st.success(t["access"])
        
               # --- SEKCIJA 1: DODAVANJE NOVE TEME ---
        st.write(t["add_topic"])
        nova_tema_input = st.text_input(t["topic_name"], placeholder=t["topic_example"])
        
        if st.button(t["save_topic"], use_container_width=True):
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
        st.write(t["delete_topic"])
        sve_teme_za_brisanje = dohvati_aktivne_teme()
        
        # Filtriramo privremenu/glavnu temu ako ne želimo da se slučajno obriše
        opcije_brisanja = [t for t in sve_teme_za_brisanje if t != "Općenito"]
        
        if opcije_brisanja:
            opcije_brisanja_za_prikaz = {prikazi_temu(tema): tema for tema in opcije_brisanja}
            tema_za_uklanjanje_prikaz = st.selectbox(t["choose_delete"], list(opcije_brisanja_za_prikaz), key="delete_select")
            tema_za_uklanjanje = opcije_brisanja_za_prikaz[tema_za_uklanjanje_prikaz]
            
            # Sigurnosna kvačica kako se ne bi obrisalo slučajnim klikom
            potvrda_brisanja = st.checkbox(t["confirm_delete"])
            
            if st.button(t["delete"], use_container_width=True, type="primary"):
                if potvrda_brisanja:
                    uspjeh, poruka = obrisi_temu(tema_za_uklanjanje)
                    if uspjeh:
                        st.toast(poruka, icon="🗑️")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(poruka)
                else:
                    st.warning(t["must_confirm"])
        else:
            st.info(t["no_topics"])
            
    elif admin_lozinka != "":
        st.error(t["wrong_password"])
    elif not admin_zaporka:
        st.info(t["admin_secret"])
