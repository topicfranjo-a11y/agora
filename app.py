from flask import Flask, render_template, request, redirect, url_for, session, abort, flash
import os
import json
import secrets
import uuid
from datetime import datetime, date

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ADMIN_SESSION_KEY = "admin_authenticated_v563"

# Rich content preserved from V4.1.1. The actual topic list still comes from Neon/Agora.
TOPIC_CONTENT = {
    "Budućnost demokracije": {
        "intro": "Demokracija nije samo pravo birati vlast nego i sposobnost društva da ispravlja vlastite pogreške.",
        "question": "Može li demokracija dugoročno preživjeti pad povjerenja, dezinformacije i politički konformizam?",
        "goal": "Razdvojiti činjenice, pretpostavke i vrijednosne sudove.",
        "key_questions": "Što mjerimo?\nKoje su pretpostavke?\nŠto bi moglo pobiti tvrdnju?",
        "sources": "",
        "rules": "Napadaj argument, ne osobu. Jasno razlikuj činjenice od mišljenja.",
        "ai_criteria": "Posebno provjeri izvore, uzročnost i predviđanja.",
    },
    "Umjetna inteligencija i čovjek": {
        "intro": "Ako AI može brže analizirati i stvarati, što ostaje kao posebna vrijednost ljudskog mišljenja?",
        "question": "Treba li AI prvenstveno ograničavati ili učiti odgovornosti?",
        "goal": "Ispitati korist, rizik i ljudsku odgovornost.",
        "key_questions": "Koji je konkretan rizik?\nTko snosi odgovornost?\nKako se tvrdnja može provjeriti?",
        "sources": "",
        "rules": "Ne pripisuj AI-ju sposobnosti bez dokaza.",
        "ai_criteria": "Provjeri razlikovanje činjenica, procjena i predviđanja.",
    },
    "Odgovornost prema budućim generacijama": {
        "intro": "Ljudi koji još nisu rođeni ne mogu sudjelovati u današnjim odlukama.",
        "question": "Koliku odgovornost imamo prema svijetu koji ćemo im ostaviti?",
        "goal": "Učiniti dugoročne posljedice vidljivima.",
        "key_questions": "Koja je posljedica?\nKoliko je izvjesna?\nTko plaća cijenu odluke?",
        "sources": "",
        "rules": "Argumentiraj posljedice, ne namjere.",
        "ai_criteria": "Provjeri vremenski horizont i pretpostavke o budućnosti.",
    },
}

def now_iso():
    return datetime.now().isoformat(timespec="seconds")

def db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL nije postavljen.")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(24)
    return session["csrf_token"]

def validate_csrf():
    return secrets.compare_digest(
        request.form.get("csrf_token", ""),
        session.get("csrf_token", "")
    )

def client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()

def current_user(create=True):
    """Return the anonymous Agora profile, without ever breaking page rendering."""
    ip = client_ip() or "unknown"
    try:
        with db() as conn:
            u = conn.execute(
                "SELECT ip_adresa, pseudonim, datum_registracije "
                "FROM korisnici WHERE ip_adresa=%s",
                (ip,)
            ).fetchone()
        if u or not create:
            return u or {"ip_adresa": ip, "pseudonim": "Gost"}

        pseudonym = "Mislioc-" + uuid.uuid4().hex[:5].upper()
        with db() as conn:
            u = conn.execute("""
                INSERT INTO korisnici (ip_adresa, pseudonim, datum_registracije)
                VALUES (%s,%s,%s)
                ON CONFLICT (ip_adresa) DO UPDATE
                SET pseudonim = korisnici.pseudonim
                RETURNING ip_adresa, pseudonim, datum_registracije
            """, (ip, pseudonym, now_iso())).fetchone()
        return u
    except Exception:
        app.logger.exception("current_user failed")
        return {"ip_adresa": ip, "pseudonim": "Gost"}


@app.context_processor
def globals_for_templates():
    # Do not touch PostgreSQL here. The homepage must remain renderable even if
    # the anonymous-profile table is temporarily unavailable.
    return {
        "current_user": {"pseudonym": "Gost", "pseudonim": "Gost"},
        "admin_logged": bool(session.get(ADMIN_SESSION_KEY, False)),
        "csrf_token": csrf_token(),
    }


def topic_view(row, persisted_content=None):
    if not row:
        return None
    d = dict(row)
    # Default/editorial content lives in code, while admin edits are persisted
    # in Neon (rasprave.provokacija) as JSON. Database content always wins.
    extra = dict(TOPIC_CONTENT.get(d.get("naziv"), {}))
    if persisted_content:
        extra.update(persisted_content)
    for k, v in extra.items():
        if not d.get(k):
            d[k] = v
    d["title"] = d.get("naziv", "")
    return d

def topic_content_payload(form):
    return {
        "intro": form.get("intro", "").strip(),
        "question": form.get("question", "").strip(),
        "goal": form.get("goal", "").strip(),
        "key_questions": form.get("key_questions", "").strip(),
        "rules": form.get("rules", "").strip(),
        "ai_criteria": form.get("ai_criteria", "").strip(),
        "sources": form.get("sources", "").strip(),
    }

def load_topic_content(conn, topic_name):
    """Load the latest admin-edited rich content without changing the schema."""
    row = conn.execute(
        "SELECT provokacija FROM rasprave WHERE tema=%s",
        (topic_name,)
    ).fetchone()
    if not row or not row.get("provokacija"):
        return {}
    raw = row["provokacija"]
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        # Backward compatibility if an older row stored only the prompt text.
        return {"question": raw}

def save_topic_content(conn, topic_name, payload):
    """Trajno spremi urednički sadržaj teme u postojeću tablicu rasprave.

    Ne mijenja Neon shemu. Namjerno koristimo UPDATE pa INSERT umjesto
    ON CONFLICT kako bi radilo i na postojećim instalacijama gdje je
    UNIQUE ograničenje na rasprave.tema drugačije definirano.
    Funkcija također odmah provjerava što je stvarno zapisano u bazi.
    """
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    updated = conn.execute(
        "UPDATE rasprave SET provokacija=%s WHERE tema=%s",
        (encoded, topic_name)
    ).rowcount

    if updated == 0:
        conn.execute(
            "INSERT INTO rasprave (tema, provokacija) VALUES (%s,%s)",
            (topic_name, encoded)
        )

    # Provjera prije commita: Render ne smije prijaviti uspjeh ako zapis
    # nije stvarno spremljen u PostgreSQL.
    check = conn.execute(
        "SELECT provokacija FROM rasprave WHERE tema=%s",
        (topic_name,)
    ).fetchone()
    if not check or check.get("provokacija") != encoded:
        raise RuntimeError("Neuspjelo trajno spremanje sadržaja teme u Neon bazu.")

    app.logger.info(
        "Sadržaj teme trajno spremljen u Neon: tema=%r, duljina=%d",
        topic_name, len(encoded)
    )

# =========================
# ANALITIČKI KLJUČ SVJETIONIKA (AKS) — V5.7.1
# =========================
# AKS nije presuda o istini. Njegova je svrha utvrditi ima li izričaj
# dovoljno određenu misao za ozbiljnu analizu te kako se odnosi prema
# prethodnom izričaju u lancu rasprave.

ANALITICKI_KLJUC_NAZIV = "Analitički ključ Svjetionika"
ANALITICKI_KLJUC_VERZIJA = "AKS-1.0"


def _contains_any(text, terms):
    return any(t in text for t in terms)


def analyze(text, topic=None, previous_text=None):
    """Procjena izričaja prema Analitičkom ključu Svjetionika (AKS).

    Ovo je trenutno transparentna heuristika, a ne generativni AI model.
    Razdvaja smislenost od istinitosti i daje strukturni rezultat koji se
    kasnije može zamijeniti/pojačati stvarnim AI modelom bez promjene koncepta.
    """
    text = (text or "").strip()
    lower = text.lower()
    words = len(text.split())

    # 1) SMISLENOST: postoji li prepoznatljiva tvrdnja/misao?
    filler = ["bla bla", "asdf", "qwerty", "lol", "😂😂", "haha"]
    sentence_markers = ["je", "nije", "može", "treba", "mora", "ljudi", "tehnolog", "demokr", "pitanje"]
    meaningful = words >= 3 and not _contains_any(lower, filler)
    smislenost = min(10, 2 + int(meaningful) * 4 + min(4, words // 12) + int(_contains_any(lower, sentence_markers)))

    # 2) PRECIZNOST: konkretni subjekti, glagoli, uvjeti i manje praznih generalizacija.
    vague = ["sve", "ništa", "uvijek", "nikad", "svi", "oni", "nešto", "bez veze"]
    precise_markers = ["ako", "dok", "kada", "zato što", "jer", "pod uvjetom", "%", "godina", "broj"]
    preciznost = min(10, max(2, 4 + int(_contains_any(lower, precise_markers)) + int(any(c.isdigit() for c in text)) - int(_contains_any(lower, vague))))

    # 3) RELEVANTNOST prema temi: terminološka povezanost + pitanje teme.
    topic_text = " ".join(str((topic or {}).get(k, "")) for k in ("title", "question", "goal", "key_questions", "ai_criteria")).lower()
    topic_words = {w.strip(".,;:!?()[]\"'") for w in topic_text.split() if len(w.strip(".,;:!?()[]\"'")) >= 5}
    text_words = {w.strip(".,;:!?()[]\"'") for w in lower.split() if len(w.strip(".,;:!?()[]\"'")) >= 5}
    overlap = len(topic_words & text_words)
    relevant_markers = ["pitanje", "tema", "problem", "zbog", "jer", "utjec", "posljed", "moral", "tehnolog", "ljudi"]
    relevant_score = 3 + min(5, overlap) + int(_contains_any(lower, relevant_markers))
    relevantnost = min(10, relevant_score)

    # 4) LOGIČKA VEZA: razlog, uvjet, posljedica, usporedba ili jasno suprotstavljanje.
    logic_terms = ["jer", "zato", "stoga", "dakle", "ako", "onda", "uzrok", "posljedica", "zbog", "dok", "ali", "međutim", "nego", "zato što"]
    logic = min(10, 3 + min(6, sum(1 for t in logic_terms if t in lower)))

    # 5) UTEMELJENOST / DOKAZI: ne znači istinitost; samo prisutnost oslonca.
    evidence_terms = ["izvor", "podat", "studij", "istraživ", "dokaz", "statistik", "prema", "mjeren", "eksperiment", "broj"]
    dokazi = min(10, 3 + 4 * int(_contains_any(lower, evidence_terms)) + int("http" in lower))

    # 6) PRETPOSTAVKE: eksplicitne ili očite uvjetne konstrukcije.
    assumption_terms = ["ako", "dok god", "pod pretpostavkom", "pretpostav", "vjerojat", "nužno", "sigurno", "mora"]
    pretpostavke = min(10, 3 + min(6, sum(1 for t in assumption_terms if t in lower)))

    # 7) PROVJERLJIVOST: postoje li elementi koje je moguće naknadno provjeriti.
    verifiable_terms = ["postot", "%", "godin", "datum", "broj", "statistik", "studij", "istraživ", "mjeren"]
    provjerljivost = min(10, 3 + min(6, sum(1 for t in verifiable_terms if t in lower)))

    # 8) INFORMACIJSKA VRIJEDNOST: koliko izričaj daje konkretnog materijala.
    info = 2 + min(5, words // 8) + int(_contains_any(lower, logic_terms + evidence_terms + assumption_terms))
    if lower in {"to je glupost", "bez veze", "ma to je bez veze pitanje"}:
        info = 2
    informacijska_vrijednost = min(10, info)

    # 9) ODNOS prema prethodnom izričaju.
    odnos = "početna_premisa"
    if previous_text:
        pl = previous_text.lower()
        if _contains_any(lower, ["slažem", "podržavam", "upravo", "točno", "također"]):
            odnos = "podržava"
        elif _contains_any(lower, ["ali", "međutim", "problem", "nije", "ne slažem", "suprotno", "pogrešno"]):
            odnos = "dovodi_u_pitanje"
        elif _contains_any(lower, ["osim", "uz to", "dodatno", "također", "šire"]):
            odnos = "proširuje"
        else:
            odnos = "povezan_ali_neodređen"

    # Ukupna vrijednost za kazaljku namjerno ne uključuje istinitost.
    ukupna = round(sum([smislenost, preciznost, relevantnost, logic, dokazi, pretpostavke, provjerljivost, informacijska_vrijednost]) / 8, 1)
    return {
        # Novi AKS kriteriji
        "smislenost": float(smislenost),
        "preciznost": float(preciznost),
        "relevantnost": float(relevantnost),
        "logicka_veza": float(logic),
        "dokazi": float(dokazi),
        "pretpostavke": float(pretpostavke),
        "provjerljivost": float(provjerljivost),
        "informacijska_vrijednost": float(informacijska_vrijednost),
        "odnos_prema_prethodnom": odnos,
        "ukupna_ocjena": ukupna,
        # Kompatibilni nazivi za postojeće DB stupce / prikaz.
        "jasnoća": float(preciznost),
        "logika": float(logic),
        "kontraargumenti": float(relevantnost),
        "prag_relevantnosti": False,
    }


def analysis_average(scores):
    return round(float(scores.get("ukupna_ocjena") or 0), 1)


def relevance_threshold(scores):
    """Prag odlučuje je li izričaj dovoljno oblikovan za ozbiljnu analizu."""
    return (
        scores.get("smislenost", 0) >= 5 and
        scores.get("preciznost", 0) >= 4 and
        scores.get("relevantnost", 0) >= 4 and
        scores.get("logicka_veza", 0) >= 4
    )


def add_analysis_view(row):
    if not row:
        return row
    d = dict(row)
    raw = d.get("sirovi_rezultat") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    d.update({k: raw[k] for k in ("smislenost", "preciznost", "relevantnost", "logicka_veza", "informacijska_vrijednost", "odnos_prema_prethodnom") if k in raw})
    d["pocetna_ocjena"] = float(raw.get("ukupna_ocjena") or round(sum(float(d.get(k) or 0) for k in ("jasnoca", "logika", "dokazi", "pretpostavke", "provjerljivost")) / 5, 1))
    return d


def add_critique_view(row):
    if not row:
        return row
    d = dict(row)
    d["ukupna_ocjena"] = float(d.get("ukupna_ocjena") or 0)
    raw = d.get("sirovi_rezultat") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    d.update({k: raw[k] for k in ("smislenost", "preciznost", "relevantnost", "logicka_veza", "informacijska_vrijednost", "odnos_prema_prethodnom") if k in raw})
    return d

def admin_guard():
    if not session.get(ADMIN_SESSION_KEY):
        return redirect(url_for("admin_login"))
    return None

@app.get("/about")
def about():
    return render_template("about.html")

@app.get("/health")
def health():
    required = [
        "teme", "argumenti", "korisnici",
        "svjetionik_misljenja", "svjetionik_odgovori",
        "svjetionik_analize", "svjetionik_predvidjanja",
        "svjetionik_verzije_misljenja", "svjetionik_ai_dogadaji", "svjetionik_kritike", "svjetionik_analize_kritika"
    ]
    try:
        with db() as conn:
            present = conn.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema='public' AND table_name = ANY(%s)
            """, (required,)).fetchall()
            names = {r["table_name"] for r in present}
            missing = [x for x in required if x not in names]
        if missing:
            return {"status": "error", "database": "connected", "missing_tables": missing}, 500
        return {"status": "ok", "database": "connected", "schema": "v5.7.1"}
    except Exception as exc:
        app.logger.exception("Health check failed")
        return {"status": "error", "database": "unavailable", "detail": str(exc)}, 500

@app.get("/")
def index():
    with db() as conn:
        topics_raw = conn.execute("""
            SELECT t.id, t.naziv, COALESCE(t.aktivna, TRUE) AS aktivna,
                   r.provokacija AS topic_content,
                   (SELECT COUNT(*) FROM svjetionik_misljenja m WHERE m.tema_id=t.id) AS opinion_count
            FROM teme t
            LEFT JOIN rasprave r ON r.tema=t.naziv
            WHERE COALESCE(t.aktivna, TRUE)=TRUE
            ORDER BY t.id
        """).fetchall()

        opinions = conn.execute("""
            SELECT m.id, m.tema_naziv, m.tvrdnja, m.korisnik_pseudonim, m.stvoreno_at,
                   (SELECT COUNT(*) FROM svjetionik_odgovori r WHERE r.misljenje_id=m.id) AS reply_count
            FROM svjetionik_misljenja m
            JOIN teme t ON t.id=m.tema_id
            WHERE COALESCE(t.aktivna, TRUE)=TRUE
            ORDER BY m.id DESC
            LIMIT 12
        """).fetchall()

    topics = []
    for x in topics_raw:
        persisted = {}
        if x.get("topic_content"):
            try:
                parsed = json.loads(x["topic_content"])
                if isinstance(parsed, dict):
                    persisted = parsed
            except (TypeError, ValueError):
                persisted = {"question": x["topic_content"]}
        tv = topic_view(x, persisted)
        tv["title"] = tv["naziv"]
        tv["participants"] = tv.get("opinion_count", 0)
        tv["avg_score"] = None
        topics.append(tv)
    return render_template("index.html", topics=topics, opinions=opinions)

@app.get("/topic/<int:topic_id>")
def topic(topic_id):
    with db() as conn:
        t = conn.execute("""
            SELECT t.id, t.naziv, COALESCE(t.aktivna, TRUE) AS aktivna,
                   r.provokacija AS topic_content
            FROM teme t
            LEFT JOIN rasprave r ON r.tema=t.naziv
            WHERE t.id=%s
        """, (topic_id,)).fetchone()
        if not t or not t["aktivna"]:
            abort(404)

        opinions = conn.execute("""
            SELECT m.*,
                   (SELECT COUNT(*) FROM svjetionik_odgovori r WHERE r.misljenje_id=m.id) AS reply_count
            FROM svjetionik_misljenja m
            WHERE m.tema_id=%s
            ORDER BY m.id DESC
        """, (topic_id,)).fetchall()

        replies = {}
        for o in opinions:
            a = conn.execute("""
                SELECT jasnoca, logika, dokazi, pretpostavke, kontraargumenti, provjerljivost, obrazlozenje, sirovi_rezultat
                FROM svjetionik_analize
                WHERE misljenje_id=%s ORDER BY id DESC LIMIT 1
            """, (o["id"],)).fetchone()
            o["analysis"] = add_analysis_view(a)
            replies[o["id"]] = conn.execute("""
                SELECT k.id, k.korisnik_pseudonim, k.tekst, k.vrsta, k.status_analize, k.stvoreno_at,
                       a.jasnoca, a.logika, a.utemeljenost, a.pretpostavke, a.provjerljivost,
                       a.ukupna_ocjena, a.prag_relevantnosti, a.obrazlozenje, a.sirovi_rezultat
                FROM svjetionik_kritike k
                LEFT JOIN LATERAL (
                    SELECT * FROM svjetionik_analize_kritika ak
                    WHERE ak.kritika_id=k.id ORDER BY ak.id DESC LIMIT 1
                ) a ON TRUE
                WHERE k.misljenje_id=%s ORDER BY k.id
            """, (o["id"],)).fetchall()

    persisted = {}
    if t.get("topic_content"):
        try:
            parsed = json.loads(t["topic_content"])
            if isinstance(parsed, dict):
                persisted = parsed
        except (TypeError, ValueError):
            persisted = {"question": t["topic_content"]}
    tv = topic_view(t, persisted)
    return render_template("topic.html", topic=tv, opinions=opinions, replies=replies)

@app.get("/topic/<int:topic_id>/write")
def write(topic_id):
    with db() as conn:
        t = conn.execute("""
            SELECT t.id, t.naziv, COALESCE(t.aktivna,TRUE) AS aktivna,
                   r.provokacija AS topic_content
            FROM teme t
            LEFT JOIN rasprave r ON r.tema=t.naziv
            WHERE t.id=%s
        """, (topic_id,)).fetchone()
    if not t or not t["aktivna"]:
        abort(404)
    persisted = {}
    if t.get("topic_content"):
        try:
            parsed = json.loads(t["topic_content"])
            if isinstance(parsed, dict):
                persisted = parsed
        except (TypeError, ValueError):
            persisted = {"question": t["topic_content"]}
    return render_template("write.html", topic=topic_view(t, persisted))

@app.post("/topic/<int:topic_id>/opinion")
def save_opinion(topic_id):
    if not validate_csrf():
        abort(400)

    claim = request.form.get("claim", "").strip()
    if len(claim) < 20:
        flash("Tvrdnja mora imati barem 20 znakova.", "error")
        return redirect(url_for("write", topic_id=topic_id))
    if len(claim) > 500:
        flash("Tvrdnja može imati najviše 500 znakova.", "error")
        return redirect(url_for("write", topic_id=topic_id))

    user = current_user(create=True)
    with db() as conn:
        t = conn.execute("""
            SELECT t.*, r.provokacija AS topic_content
            FROM teme t
            LEFT JOIN rasprave r ON r.tema=t.naziv
            WHERE t.id=%s AND COALESCE(t.aktivna,TRUE)=TRUE
        """, (topic_id,)).fetchone()
        if not t:
            abort(404)
        persisted = {}
        if t.get("topic_content"):
            try:
                parsed = json.loads(t["topic_content"])
                if isinstance(parsed, dict):
                    persisted = parsed
            except (TypeError, ValueError):
                persisted = {"question": t["topic_content"]}
        tv = topic_view(t, persisted)
        scores = analyze(claim, tv)
        scores["prag_relevantnosti"] = relevance_threshold(scores)

        m = conn.execute("""
            INSERT INTO svjetionik_misljenja
            (korisnik_ip, korisnik_pseudonim, tema_id, tema_naziv,
             tvrdnja, argument, dokaz, pretpostavke, kontraargument,
             zakljucak, predvidjanje, datum_predvidjanja)
            VALUES (%s,%s,%s,%s,%s,NULL,NULL,NULL,NULL,NULL,NULL,NULL)
            RETURNING id
        """, (user["ip_adresa"], user["pseudonim"], topic_id, t["naziv"], claim)).fetchone()

        conn.execute("""
            INSERT INTO svjetionik_verzije_misljenja
            (misljenje_id, verzija, sadrzaj, razlog_promjene)
            VALUES (%s,1,%s,%s)
        """, (m["id"], Jsonb({"tvrdnja": claim}), "Početna verzija mišljenja"))

        conn.execute("""
            INSERT INTO svjetionik_analize
            (misljenje_id, model, verzija_modela, jasnoca, logika, dokazi,
             pretpostavke, kontraargumenti, provjerljivost, obrazlozenje, sirovi_rezultat)
            VALUES (%s,'heuristika','v5.6',%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            m["id"], scores["jasnoća"], scores["logika"], scores["dokazi"],
            scores["pretpostavke"], scores["kontraargumenti"], scores["provjerljivost"],
            "Analitički ključ Svjetionika (AKS-1.0): procjenjuje smislenost i strukturu izričaja; ne utvrđuje istinu.",
            Jsonb(scores)
        ))

        conn.execute("""
            INSERT INTO svjetionik_ai_dogadaji (misljenje_id, model, vrsta, ulaz, izlaz)
            VALUES (%s,'heuristika','početna_analiza',%s,%s)
        """, (m["id"], Jsonb({"tema": t["naziv"], "tvrdnja": claim, "ai_criteria": tv.get("ai_criteria", "")}), Jsonb({**scores, "prag_relevantnosti": scores["prag_relevantnosti"], "analiticki_kljuc": ANALITICKI_KLJUC_NAZIV, "verzija_kljuca": ANALITICKI_KLJUC_VERZIJA})))

    flash("Stav je spremljen i otvoren ljudskoj kritici.", "success")
    return redirect(url_for("opinion_detail", opinion_id=m["id"]))

@app.post("/opinion/<int:opinion_id>/reply")
def save_reply(opinion_id):
    if not validate_csrf():
        abort(400)
    text = request.form.get("text", "").strip()
    if len(text) < 20:
        flash("Kritika mora imati barem 20 znakova.", "error")
        return redirect(request.referrer or url_for("index"))
    if len(text) > 500:
        flash("Kritika može imati najviše 500 znakova.", "error")
        return redirect(request.referrer or url_for("index"))

    user = current_user(create=True)
    with db() as conn:
        opinion = conn.execute("""
            SELECT m.id, m.tema_id, m.tema_naziv, m.korisnik_ip, m.tvrdnja, t.aktivna
            FROM svjetionik_misljenja m
            JOIN teme t ON t.id=m.tema_id
            WHERE m.id=%s AND COALESCE(t.aktivna, TRUE)=TRUE
        """, (opinion_id,)).fetchone()
        if not opinion:
            abort(404)

        # Autor može odgovoriti na vlastitu tvrdnju; svi ostali unosi su kontraargumenti.
        vrsta = "odgovor_autora" if user["ip_adresa"] == opinion["korisnik_ip"] else "kontraargument"
        scores = analyze(text, {"title": opinion["tema_naziv"], "question": opinion["tvrdnja"], "ai_criteria": "Analitički ključ Svjetionika."}, previous_text=opinion["tvrdnja"])
        relevant = relevance_threshold(scores)
        status = "relevantno" if relevant else "nedovoljno_oblikovano"
        overall = analysis_average(scores)

        k = conn.execute("""
            INSERT INTO svjetionik_kritike
            (misljenje_id, korisnik_ip, korisnik_pseudonim, vrsta, tekst, status_analize)
            VALUES (%s,%s,%s,%s,%s,%s) RETURNING id
        """, (opinion_id, user["ip_adresa"], user["pseudonim"], vrsta, text, status)).fetchone()

        conn.execute("""
            INSERT INTO svjetionik_analize_kritika
            (kritika_id, model, verzija_modela, jasnoca, logika, utemeljenost,
             pretpostavke, provjerljivost, ukupna_ocjena, prag_relevantnosti,
             obrazlozenje, sirovi_rezultat)
            VALUES (%s,'heuristika','v5.7',%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            k["id"], scores["jasnoća"], scores["logika"], scores["dokazi"],
            scores["pretpostavke"], scores["provjerljivost"], overall, relevant,
            "Ista početna logika vrednovanja koristi se za tvrdnju i kritiku. Prag relevantnosti ne znači da je tekst istinit ili netočan.",
            Jsonb({**scores, "prag_relevantnosti": relevant, "analiticki_kljuc": ANALITICKI_KLJUC_NAZIV, "verzija_kljuca": ANALITICKI_KLJUC_VERZIJA})
        ))

        # Zadržavamo stari zapis radi kompatibilnosti s V5.x prikazima, ali nova
        # analitička baza koristi svjetionik_kritike i svjetionik_analize_kritika.
        conn.execute("""
            INSERT INTO svjetionik_odgovori (misljenje_id, korisnik_ip, korisnik_pseudonim, tekst)
            VALUES (%s,%s,%s,%s)
        """, (opinion_id, user["ip_adresa"], user["pseudonim"], text))

    if relevant:
        flash("Kritika je spremljena i analitički vrednovana.", "success")
    else:
        flash("Kritika je spremljena, ali nije dovoljno oblikovana za analizu.", "error")
    return redirect(request.referrer or url_for("index"))


@app.get("/opinion/<int:opinion_id>")
def opinion_detail(opinion_id):
    with db() as conn:
        m = conn.execute("""
            SELECT m.*
            FROM svjetionik_misljenja m
            JOIN teme t ON t.id=m.tema_id
            WHERE m.id=%s AND COALESCE(t.aktivna, TRUE)=TRUE
        """, (opinion_id,)).fetchone()
        if not m:
            abort(404)
        analyses = conn.execute("""
            SELECT model, verzija_modela, jasnoca, logika, dokazi, pretpostavke,
                   kontraargumenti, provjerljivost, obrazlozenje, sirovi_rezultat, stvoreno_at
            FROM svjetionik_analize WHERE misljenje_id=%s ORDER BY id DESC
        """, (opinion_id,)).fetchall()
        analyses = [add_analysis_view(a) for a in analyses]
        replies = conn.execute("""
            SELECT k.id, k.korisnik_pseudonim, k.tekst, k.vrsta, k.status_analize, k.stvoreno_at,
                   a.jasnoca, a.logika, a.utemeljenost, a.pretpostavke, a.provjerljivost,
                   a.ukupna_ocjena, a.prag_relevantnosti, a.obrazlozenje, a.sirovi_rezultat
            FROM svjetionik_kritike k
            LEFT JOIN LATERAL (SELECT * FROM svjetionik_analize_kritika ak WHERE ak.kritika_id=k.id ORDER BY ak.id DESC LIMIT 1) a ON TRUE
            WHERE k.misljenje_id=%s ORDER BY k.id
        """, (opinion_id,)).fetchall()
        predictions = conn.execute("""
            SELECT * FROM svjetionik_predvidjanja
            WHERE misljenje_id=%s ORDER BY id DESC
        """, (opinion_id,)).fetchall()
    return render_template("opinion.html", opinion=m, analyses=analyses,
                           replies=replies, predictions=predictions)

@app.get("/topic/<int:topic_id>/rasprava")
def topic_discussion_database(topic_id):
    """Javna baza tvrdnji i kontraargumenata jedne aktivne teme."""
    with db() as conn:
        topic_row = conn.execute("""
            SELECT t.id, t.naziv, COALESCE(t.aktivna,TRUE) AS aktivna, r.provokacija AS topic_content
            FROM teme t LEFT JOIN rasprave r ON r.tema=t.naziv WHERE t.id=%s
        """, (topic_id,)).fetchone()
        if not topic_row or not topic_row["aktivna"]:
            abort(404)
        rows = conn.execute("""
            SELECT * FROM svjetionik_baza_rasprave
            WHERE tema_id=%s ORDER BY misljenje_id DESC, kritika_id ASC
        """, (topic_id,)).fetchall()
    persisted = {}
    if topic_row.get("topic_content"):
        try:
            parsed=json.loads(topic_row["topic_content"])
            if isinstance(parsed,dict): persisted=parsed
        except (TypeError,ValueError):
            persisted={"question":topic_row["topic_content"]}
    return render_template("discussion_db.html", topic=topic_view(topic_row,persisted), rows=rows)

@app.get("/topic/<int:topic_id>/izvjestaj")
def topic_report(topic_id):
    """Javni analitički izvještaj teme iz trenutno prikupljene rasprave."""
    with db() as conn:
        topic_row = conn.execute("""
            SELECT t.id, t.naziv, COALESCE(t.aktivna,TRUE) AS aktivna,
                   r.provokacija AS topic_content
            FROM teme t LEFT JOIN rasprave r ON r.tema=t.naziv
            WHERE t.id=%s
        """, (topic_id,)).fetchone()
        if not topic_row or not topic_row["aktivna"]:
            abort(404)
        opinions = conn.execute("""
            SELECT m.id, m.tvrdnja, m.korisnik_pseudonim, m.stvoreno_at,
                   a.sirovi_rezultat
            FROM svjetionik_misljenja m
            LEFT JOIN LATERAL (
                SELECT * FROM svjetionik_analize WHERE misljenje_id=m.id ORDER BY id DESC LIMIT 1
            ) a ON TRUE
            WHERE m.tema_id=%s ORDER BY m.id
        """, (topic_id,)).fetchall()
        critiques = conn.execute("""
            SELECT k.id, k.misljenje_id, k.vrsta, k.tekst, a.sirovi_rezultat,
                   a.ukupna_ocjena, a.prag_relevantnosti
            FROM svjetionik_kritike k
            LEFT JOIN LATERAL (
                SELECT * FROM svjetionik_analize_kritika WHERE kritika_id=k.id ORDER BY id DESC LIMIT 1
            ) a ON TRUE
            JOIN svjetionik_misljenja m ON m.id=k.misljenje_id
            WHERE m.tema_id=%s ORDER BY k.id
        """, (topic_id,)).fetchall()
    persisted={}
    if topic_row.get("topic_content"):
        try:
            x=json.loads(topic_row["topic_content"])
            if isinstance(x,dict): persisted=x
        except Exception: persisted={"question":topic_row["topic_content"]}
    # Aggregati su deskriptivni; ne tvrde da je većina u pravu.
    def raw_json(v):
        if isinstance(v, dict): return v
        try: return json.loads(v) if v else {}
        except Exception: return {}
    relevant = [c for c in critiques if c.get("prag_relevantnosti")]
    return render_template("report.html", topic=topic_view(topic_row,persisted),
                           opinions=opinions, critiques=critiques, relevant_critiques=relevant,
                           raw_json=raw_json, key_name=ANALITICKI_KLJUC_NAZIV,
                           key_version=ANALITICKI_KLJUC_VERZIJA)

@app.get("/predictions")
def predictions():
    topic_id = request.args.get("tema_id", type=int)
    with db() as conn:
        if topic_id:
            rows = conn.execute("""
                SELECT p.id, p.misljenje_id, p.predvidjanje, p.rok, p.status,
                       p.ishod, p.provjereno_at, p.biljeska,
                       m.korisnik_pseudonim AS pseudonim,
                       m.tema_naziv AS topic_title,
                       m.tvrdnja AS claim
                FROM svjetionik_predvidjanja p
                JOIN svjetionik_misljenja m ON m.id=p.misljenje_id
                WHERE m.tema_id=%s
                ORDER BY p.rok ASC NULLS LAST, p.id DESC
            """, (topic_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT p.id, p.misljenje_id, p.predvidjanje, p.rok, p.status,
                       p.ishod, p.provjereno_at, p.biljeska,
                       m.korisnik_pseudonim AS pseudonim,
                       m.tema_naziv AS topic_title,
                       m.tvrdnja AS claim
                FROM svjetionik_predvidjanja p
                JOIN svjetionik_misljenja m ON m.id=p.misljenje_id
                ORDER BY p.rok ASC NULLS LAST, p.id DESC
            """).fetchall()
    return render_template("predictions.html", predictions=rows, topic_id=topic_id)

@app.post("/pseudonym")
def change_pseudonym():
    if not validate_csrf():
        abort(400)
    name = request.form.get("pseudonym", "").strip()
    user = current_user(create=True)
    if 3 <= len(name) <= 30:
        with db() as conn:
            conn.execute("UPDATE korisnici SET pseudonim=%s WHERE ip_adresa=%s", (name, user["ip_adresa"]))
        flash("Pseudonim je promijenjen.", "success")
    else:
        flash("Pseudonim mora imati 3–30 znakova.", "error")
    return redirect(request.referrer or url_for("index"))

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    # Namjerno uvijek traži ponovnu lozinku pri ulasku u Admin.
    # Time se ne koristi prethodna administratorska sesija kao prečac.
    if request.method == "GET":
        session.pop(ADMIN_SESSION_KEY, None)
    if request.method == "POST":
        if not validate_csrf():
            abort(400)
        if ADMIN_PASSWORD and secrets.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session[ADMIN_SESSION_KEY] = True
            return redirect(url_for("admin"))
        if not ADMIN_PASSWORD:
            flash("Administratorska lozinka nije postavljena u Renderu (ADMIN_PASSWORD).", "error")
        else:
            flash("Pogrešna administratorska lozinka.", "error")
    return render_template("admin_login.html")

@app.post("/admin/logout")
def admin_logout():
    if not validate_csrf():
        abort(400)
    session[ADMIN_SESSION_KEY] = False
    return redirect(url_for("index"))


# =========================
# ADMIN V5.4 — SVJETIONIK
# =========================

def admin_required_v54():
    return bool(session.get(ADMIN_SESSION_KEY, False))

def admin_redirect_v54():
    return redirect(url_for("admin_login"))

@app.get("/admin/v54")
def admin_v54():
    if not admin_required_v54():
        return admin_redirect_v54()
    try:
        with db() as conn:
            topics = conn.execute("""
                SELECT t.*,
                       (SELECT COUNT(*) FROM svjetionik_misljenja m WHERE m.tema_id=t.id) AS opinion_count,
                       (SELECT COUNT(*) FROM svjetionik_odgovori r
                        JOIN svjetionik_misljenja m ON m.id=r.misljenje_id
                        WHERE m.tema_id=t.id) AS reply_count
                FROM teme t ORDER BY t.id
            """).fetchall()
            stats = {
                "topics": conn.execute("SELECT COUNT(*) AS n FROM teme").fetchone()["n"],
                "opinions": conn.execute("SELECT COUNT(*) AS n FROM svjetionik_misljenja").fetchone()["n"],
                "replies": conn.execute("SELECT COUNT(*) AS n FROM svjetionik_odgovori").fetchone()["n"],
                "predictions": conn.execute("SELECT COUNT(*) AS n FROM svjetionik_predvidjanja").fetchone()["n"],
                "participants": conn.execute("SELECT COUNT(*) AS n FROM korisnici").fetchone()["n"],
                "analyses": conn.execute("SELECT COUNT(*) AS n FROM svjetionik_analize").fetchone()["n"],
            }
        return render_template("admin_v54.html", topics=topics, stats=stats)
    except Exception:
        app.logger.exception("Admin V5.4.1 nije uspio")
        return render_template("error.html", message="Admin trenutno nije mogao učitati podatke."), 500

@app.route("/admin/topic/new", methods=["GET", "POST"])
def admin_topic_new_v54():
    if not admin_required_v54():
        return admin_redirect_v54()

    if request.method == "POST":
        if not validate_csrf():
            abort(400)

        name = request.form.get("title", "").strip()
        if not name:
            flash("Naziv teme je obavezan.", "error")
            return redirect(url_for("admin_topic_new_v54"))

        # 'teme' ostaje nepromijenjena; bogati urednički sadržaj
        # trajno spremamo u postojeću tablicu 'rasprave' kao JSON tekst.
        try:
            with db() as conn:
                existing = conn.execute(
                    "SELECT id FROM teme WHERE naziv=%s",
                    (name,)
                ).fetchone()

                if existing:
                    flash("Tema s tim nazivom već postoji.", "error")
                    return redirect(url_for("admin_topic_new_v54"))

                row = conn.execute(
                    """INSERT INTO teme (naziv, aktivna)
                       VALUES (%s, TRUE)
                       RETURNING id, naziv, aktivna""",
                    (name,)
                ).fetchone()
                save_topic_content(conn, name, topic_content_payload(request.form))
                conn.commit()

            TOPIC_CONTENT[name] = topic_content_payload(request.form)

            app.logger.info("Nova tema dodana: id=%s naziv=%s", row["id"], row["naziv"])
            flash("Tema je uspješno dodana.", "success")
            return redirect(url_for("admin_v54"))

        except Exception as exc:
            app.logger.exception("Dodavanje teme nije uspjelo: %s", exc)
            flash(f"Greška pri dodavanju teme: {exc}", "error")
            return redirect(url_for("admin_topic_new_v54"))

    return render_template("admin_topic_v54.html", mode="new", topic=None)


@app.route("/admin/topic/<int:topic_id>/edit", methods=["GET", "POST"])
def admin_topic_edit_v54(topic_id):
    if not admin_required_v54():
        return admin_redirect_v54()

    try:
        with db() as conn:
            topic = conn.execute(
                "SELECT id,naziv,aktivna FROM teme WHERE id=%s",
                (topic_id,)
            ).fetchone()

            if not topic:
                abort(404)

            if request.method == "POST":
                if not validate_csrf():
                    abort(400)

                name = request.form.get("title", "").strip()
                if not name:
                    flash("Naziv teme je obavezan.", "error")
                    return redirect(url_for("admin_topic_edit_v54", topic_id=topic_id))

                duplicate = conn.execute(
                    "SELECT id FROM teme WHERE naziv=%s AND id<>%s",
                    (name, topic_id)
                ).fetchone()
                if duplicate:
                    flash("Druga tema već koristi taj naziv.", "error")
                    return redirect(url_for("admin_topic_edit_v54", topic_id=topic_id))

                old_name = topic["naziv"]
                active = bool(request.form.get("active"))

                conn.execute(
                    "UPDATE teme SET naziv=%s, aktivna=%s WHERE id=%s",
                    (name, active, topic_id)
                )
                if old_name != name:
                    conn.execute("DELETE FROM rasprave WHERE tema=%s", (old_name,))
                save_topic_content(conn, name, topic_content_payload(request.form))
                conn.commit()

                TOPIC_CONTENT[name] = topic_content_payload(request.form)

                if old_name != name:
                    TOPIC_CONTENT.pop(old_name, None)

                app.logger.info(
                    "Tema uređena: id=%s stari_naziv=%s novi_naziv=%s",
                    topic_id, old_name, name
                )
                flash("Tema je spremljena.", "success")
                return redirect(url_for("admin_v54"))

            persisted = load_topic_content(conn, topic["naziv"])
            topic = topic_view(topic, persisted)
            return render_template("admin_topic_v54.html", mode="edit", topic=topic)

    except Exception as exc:
        app.logger.exception("Uređivanje teme nije uspjelo: %s", exc)
        flash(f"Greška pri uređivanju teme: {exc}", "error")
        return redirect(url_for("admin_v54"))


def delete_topic_content(conn, topic_id):
    """Obriši sva mišljenja teme; povezani odgovori, analize, predviđanja,
    verzije i AI događaji brišu se putem ON DELETE CASCADE veza.
    Ne briše samu temu niti njezin urednički sadržaj.
    """
    row = conn.execute(
        "SELECT naziv FROM teme WHERE id=%s", (topic_id,)
    ).fetchone()
    if not row:
        abort(404)

    count = conn.execute(
        "SELECT COUNT(*) AS n FROM svjetionik_misljenja WHERE tema_id=%s",
        (topic_id,)
    ).fetchone()["n"]

    conn.execute(
        "DELETE FROM svjetionik_misljenja WHERE tema_id=%s",
        (topic_id,)
    )
    app.logger.info(
        "Obrisan sadržaj teme: id=%s naziv=%r mišljenja=%s",
        topic_id, row["naziv"], count
    )
    return row["naziv"], count


@app.post("/admin/topic/<int:topic_id>/toggle")
def admin_topic_toggle_v54(topic_id):
    if not admin_required_v54():
        return admin_redirect_v54()
    if not validate_csrf():
        abort(400)
    try:
        with db() as conn:
            topic = conn.execute(
                "SELECT id, naziv, COALESCE(aktivna,FALSE) AS aktivna FROM teme WHERE id=%s",
                (topic_id,)
            ).fetchone()
            if not topic:
                abort(404)

            was_active = bool(topic["aktivna"])
            if was_active:
                # Deaktivacija automatski uklanja sva javna mišljenja teme.
                # Povezani odgovori i ostali izvedeni zapisi nestaju kaskadno.
                _, deleted = delete_topic_content(conn, topic_id)
                conn.execute(
                    "UPDATE teme SET aktivna=FALSE WHERE id=%s",
                    (topic_id,)
                )
                conn.commit()
                flash(
                    f"Tema je deaktivirana. Uklonjeno je {deleted} mišljenja i pripadajući sadržaj.",
                    "success"
                )
            else:
                conn.execute(
                    "UPDATE teme SET aktivna=TRUE WHERE id=%s",
                    (topic_id,)
                )
                conn.commit()
                flash("Tema je ponovno aktivirana. Novi sadržaj može se objavljivati.", "success")
    except Exception as exc:
        app.logger.exception("Promjena statusa teme nije uspjela: %s", exc)
        flash(f"Greška: {exc}", "error")
    return redirect(url_for("admin_v54"))

@app.post("/admin/topic/<int:topic_id>/delete-content")
def admin_topic_delete_content_v54(topic_id):
    if not admin_required_v54():
        return admin_redirect_v54()
    if not validate_csrf():
        abort(400)
    try:
        with db() as conn:
            topic = conn.execute(
                "SELECT id, naziv, COALESCE(aktivna,FALSE) AS aktivna FROM teme WHERE id=%s",
                (topic_id,)
            ).fetchone()
            if not topic:
                abort(404)
            if topic["aktivna"]:
                flash("Sadržaj se može brisati samo kada je tema neaktivna.", "error")
                return redirect(url_for("admin_v54"))

            name, deleted = delete_topic_content(conn, topic_id)
            conn.commit()
            flash(
                f"Sadržaj teme '{name}' je obrisan. Uklonjeno je {deleted} mišljenja i pripadajući sadržaj.",
                "success"
            )
    except Exception as exc:
        app.logger.exception("Brisanje sadržaja teme nije uspjelo: %s", exc)
        flash(f"Greška pri brisanju sadržaja: {exc}", "error")
    return redirect(url_for("admin_v54"))

@app.get("/admin/opinions")
def admin_opinions_v54():
    if not admin_required_v54():
        return admin_redirect_v54()
    topic_id = request.args.get("topic_id", type=int)
    try:
        with db() as conn:
            if topic_id:
                opinions = conn.execute("""SELECT m.*,t.naziv AS topic_title
                    FROM svjetionik_misljenja m LEFT JOIN teme t ON t.id=m.tema_id
                    WHERE m.tema_id=%s ORDER BY m.stvoreno_at DESC""", (topic_id,)).fetchall()
            else:
                opinions = conn.execute("""SELECT m.*,t.naziv AS topic_title
                    FROM svjetionik_misljenja m LEFT JOIN teme t ON t.id=m.tema_id
                    ORDER BY m.stvoreno_at DESC""").fetchall()
            topics = conn.execute("SELECT id,naziv,aktivna FROM teme ORDER BY naziv").fetchall()
        return render_template("admin_opinions_v54.html", opinions=opinions, topics=topics, selected_topic=topic_id)
    except Exception as exc:
        flash(f"Greška: {exc}", "error")
        return redirect(url_for("admin_v54"))

@app.get("/admin/opinion/<int:opinion_id>")
def admin_opinion_detail_v54(opinion_id):
    if not admin_required_v54():
        return admin_redirect_v54()
    try:
        with db() as conn:
            opinion = conn.execute("""SELECT m.*,t.naziv AS topic_title
                FROM svjetionik_misljenja m LEFT JOIN teme t ON t.id=m.tema_id WHERE m.id=%s""",
                (opinion_id,)).fetchone()
            if not opinion:
                abort(404)
            analyses = conn.execute("SELECT * FROM svjetionik_analize WHERE misljenje_id=%s ORDER BY stvoreno_at DESC", (opinion_id,)).fetchall()
            replies = conn.execute("SELECT * FROM svjetionik_odgovori WHERE misljenje_id=%s ORDER BY stvoreno_at DESC", (opinion_id,)).fetchall()
            predictions = conn.execute("SELECT * FROM svjetionik_predvidjanja WHERE misljenje_id=%s ORDER BY rok", (opinion_id,)).fetchall()
            critiques = conn.execute("""
                SELECT k.*, a.jasnoca, a.logika, a.utemeljenost, a.pretpostavke,
                       a.provjerljivost, a.ukupna_ocjena, a.prag_relevantnosti, a.obrazlozenje, a.sirovi_rezultat
                FROM svjetionik_kritike k
                LEFT JOIN LATERAL (SELECT * FROM svjetionik_analize_kritika ak WHERE ak.kritika_id=k.id ORDER BY ak.id DESC LIMIT 1) a ON TRUE
                WHERE k.misljenje_id=%s ORDER BY k.id
            """, (opinion_id,)).fetchall()
        return render_template("admin_opinion_detail_v54.html", opinion=opinion, analyses=analyses,
                               replies=replies, critiques=critiques, predictions=predictions)
    except Exception as exc:
        flash(f"Greška: {exc}", "error")
        return redirect(url_for("admin_opinions_v54"))

@app.get("/admin/predictions")
def admin_predictions_v54():
    if not admin_required_v54():
        return admin_redirect_v54()
    topic_id = request.args.get("tema_id", type=int)
    try:
        with db() as conn:
            if topic_id:
                predictions = conn.execute("""SELECT p.*,m.tvrdnja,m.korisnik_pseudonim,t.naziv AS topic_title
                    FROM svjetionik_predvidjanja p JOIN svjetionik_misljenja m ON m.id=p.misljenje_id
                    LEFT JOIN teme t ON t.id=m.tema_id
                    WHERE t.id=%s
                    ORDER BY CASE WHEN p.status='otvoreno' THEN 0 ELSE 1 END,p.rok ASC NULLS LAST""", (topic_id,)).fetchall()
            else:
                predictions = conn.execute("""SELECT p.*,m.tvrdnja,m.korisnik_pseudonim,t.naziv AS topic_title
                    FROM svjetionik_predvidjanja p JOIN svjetionik_misljenja m ON m.id=p.misljenje_id
                    LEFT JOIN teme t ON t.id=m.tema_id
                    ORDER BY CASE WHEN p.status='otvoreno' THEN 0 ELSE 1 END,p.rok ASC NULLS LAST""").fetchall()
        return render_template("admin_predictions_v54.html", predictions=predictions, topic_id=topic_id)
    except Exception as exc:
        flash(f"Greška: {exc}", "error")
        return redirect(url_for("admin_v54"))

@app.post("/admin/prediction/<int:prediction_id>/status")
def admin_prediction_status_v54(prediction_id):
    if not admin_required_v54():
        return admin_redirect_v54()
    status = request.form.get("status", "otvoreno")
    allowed = {"otvoreno","ostvareno","nije_ostvareno","djelomicno","neprovjerljivo"}
    if status not in allowed:
        flash("Nevažeći status.", "error")
        return redirect(url_for("admin_predictions_v54"))
    try:
        with db() as conn:
            conn.execute("""UPDATE svjetionik_predvidjanja
                SET status=%s,ishod=%s,biljeska=%s,
                    provjereno_at=CASE WHEN %s='otvoreno' THEN NULL ELSE %s END
                WHERE id=%s""",
                (status, request.form.get("ishod","").strip() or None,
                 request.form.get("biljeska","").strip() or None,
                 status, now_iso(), prediction_id))
        flash("Predviđanje je ažurirano.", "success")
    except Exception as exc:
        flash(f"Greška: {exc}", "error")
    return redirect(url_for("admin_predictions_v54"))

@app.get("/admin/participants")
def admin_participants_v54():
    if not admin_required_v54():
        return admin_redirect_v54()
    try:
        with db() as conn:
            participants = conn.execute("""SELECT k.ip_adresa,k.pseudonim,k.datum_registracije,
                COUNT(DISTINCT m.id) opinions_count,COUNT(DISTINCT r.id) replies_count,
                COUNT(DISTINCT p.id) predictions_count
                FROM korisnici k
                LEFT JOIN svjetionik_misljenja m ON m.korisnik_ip=k.ip_adresa
                LEFT JOIN svjetionik_odgovori r ON r.korisnik_ip=k.ip_adresa
                LEFT JOIN svjetionik_predvidjanja p ON p.misljenje_id=m.id
                GROUP BY k.ip_adresa,k.pseudonim,k.datum_registracije
                ORDER BY k.datum_registracije DESC""").fetchall()
        return render_template("admin_participants_v54.html", participants=participants)
    except Exception as exc:
        flash(f"Greška: {exc}", "error")
        return redirect(url_for("admin_v54"))

@app.get("/admin/ai")
def admin_ai_v54():
    if not admin_required_v54():
        return admin_redirect_v54()
    try:
        with db() as conn:
            analyses = conn.execute("""SELECT a.*,m.tvrdnja,m.korisnik_pseudonim,t.naziv AS topic_title
                FROM svjetionik_analize a JOIN svjetionik_misljenja m ON m.id=a.misljenje_id
                LEFT JOIN teme t ON t.id=m.tema_id ORDER BY a.stvoreno_at DESC""").fetchall()
        return render_template("admin_ai_v54.html", analyses=analyses)
    except Exception as exc:
        flash(f"Greška: {exc}", "error")
        return redirect(url_for("admin_v54"))

@app.get("/admin")
def admin():
    if not admin_required_v54():
        return admin_redirect_v54()
    return redirect(url_for("admin_v54"))

@app.get("/admin/legacy")
def admin_legacy():
    guard = admin_guard()
    if guard:
        return guard
    with db() as conn:
        topics = conn.execute("""
            SELECT t.id,t.naziv,COALESCE(t.aktivna,TRUE) aktivna,
                   (SELECT COUNT(*) FROM svjetionik_misljenja m WHERE m.tema_id=t.id) opinion_count,
                   (SELECT COUNT(*) FROM svjetionik_predvidjanja p JOIN svjetionik_misljenja m ON m.id=p.misljenje_id WHERE m.tema_id=t.id) prediction_count
            FROM teme t ORDER BY t.id
        """).fetchall()
        pending = conn.execute("""
            SELECT p.id,p.predvidjanje,p.rok,p.status,m.tema_naziv,m.korisnik_pseudonim
            FROM svjetionik_predvidjanja p
            JOIN svjetionik_misljenja m ON m.id=p.misljenje_id
            ORDER BY p.rok ASC NULLS LAST
        """).fetchall()
    # V4.1.1 topic editor is intentionally not enabled because the existing `teme`
    # table does not contain its rich editorial fields. We preserve the rich defaults
    # in TOPIC_CONTENT and avoid altering the established Agora schema.
    return render_template("admin.html", topics=topics, pending=pending)

@app.post("/admin/prediction/<int:prediction_id>")
def admin_prediction(prediction_id):
    guard = admin_guard()
    if guard:
        return guard
    if not validate_csrf():
        abort(400)

    status = request.form.get("status", "").strip()
    allowed = {"otvoreno", "ostvareno", "nije_ostvareno", "djelomicno", "neprovjerljivo"}
    if status not in allowed:
        abort(400)

    outcome = request.form.get("ishod", "").strip()
    note = request.form.get("biljeska", "").strip()

    with db() as conn:
        conn.execute("""
            UPDATE svjetionik_predvidjanja
            SET status=%s, ishod=%s, biljeska=%s, provjereno_at=%s
            WHERE id=%s
        """, (status, outcome or None, note or None, now_iso() if status != "otvoreno" else None, prediction_id))
    return redirect(url_for("admin"))

@app.errorhandler(500)
def internal_error(error):
    app.logger.exception("Interna greška: %s", error)
    return render_template("error.html", code=500,
                           message="Aplikacija je naišla na internu grešku. Provjerite Render logove."), 500

@app.errorhandler(400)
def bad_request(error):
    return render_template("error.html", code=400,
                           message="Zahtjev nije valjan ili sigurnosna provjera nije prošla."), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
