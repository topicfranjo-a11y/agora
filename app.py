from flask import Flask, render_template, request, redirect, url_for, session, abort, flash
import os
import secrets
import uuid
from datetime import datetime, date

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

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
        "admin_logged": bool(session.get("admin_logged", False)),
        "csrf_token": csrf_token(),
    }


def topic_view(row):
    if not row:
        return None
    d = dict(row)
    extra = TOPIC_CONTENT.get(d.get("naziv"), {})
    for k, v in extra.items():
        if not d.get(k):
            d[k] = v
    d["title"] = d.get("naziv", "")
    return d

def analyze(text, topic=None):
    lower = text.lower()
    words = len(text.split())
    evidence_terms = ["izvor", "podat", "studij", "istraživ", "dokaz", "statistik", "prema", "mjeren"]
    counter_terms = ["ali", "međutim", "s druge strane", "suprotno", "prigovor", "kritika"]
    logic_terms = ["jer", "zato", "stoga", "dakle", "ako", "onda", "uzrok", "posljedica"]
    prediction_terms = ["predviđ", "očekujem", "do 20", "u budućnosti", "za godinu", "za 5 godina"]

    criteria = ((topic or {}).get("ai_criteria") or "").lower() if topic else ""
    clarity = min(10, max(2, 3 + words // 20 + (1 if "." in text else 0)))
    logic = min(10, 4 + min(4, sum(x in lower for x in logic_terms)))
    evidence = min(10, 3 + 3 * int(any(x in lower for x in evidence_terms)) + int("http" in lower))
    assumptions = min(10, 4 + int("pretpostav" in lower) + int("ako" in lower))
    counter = min(10, 3 + 3 * int(any(x in lower for x in counter_terms)))
    verifiability = min(10, 3 + 4 * int(any(x in lower for x in prediction_terms)) + int("datum" in lower or "%" in lower))

    if criteria:
        if any(k in criteria for k in ["izvor", "dokaz"]):
            evidence = min(10, evidence + 1)
        if any(k in criteria for k in ["predvi", "provjer"]):
            verifiability = min(10, verifiability + 1)

    return {
        "jasnoća": clarity,
        "logika": logic,
        "dokazi": evidence,
        "pretpostavke": assumptions,
        "kontraargumenti": counter,
        "provjerljivost": verifiability,
    }

def admin_guard():
    if not session.get("admin_logged"):
        return redirect(url_for("admin_login"))
    return None

@app.get("/health")
def health():
    required = [
        "teme", "argumenti", "korisnici",
        "svjetionik_misljenja", "svjetionik_odgovori",
        "svjetionik_analize", "svjetionik_predvidjanja",
        "svjetionik_verzije_misljenja", "svjetionik_ai_dogadaji"
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
        return {"status": "ok", "database": "connected", "schema": "v5.3.2"}
    except Exception as exc:
        app.logger.exception("Health check failed")
        return {"status": "error", "database": "unavailable", "detail": str(exc)}, 500

@app.get("/")
def index():
    with db() as conn:
        topics_raw = conn.execute("""
            SELECT t.id, t.naziv, COALESCE(t.aktivna, TRUE) AS aktivna,
                   (SELECT COUNT(*) FROM svjetionik_misljenja m WHERE m.tema_id=t.id) AS opinion_count,
                   (SELECT COUNT(*) FROM argumenti a WHERE a.tema=t.naziv) AS agora_count
            FROM teme t
            WHERE COALESCE(t.aktivna, TRUE)=TRUE
            ORDER BY t.id
        """).fetchall()

        legacy_args = conn.execute("""
            SELECT id, korisnik, tema, tekst, datum, ton,
                   ocjena_analitika, ocjena_empatija, ocjena_sinteza, ocjena_suglasje
            FROM argumenti
            ORDER BY id DESC
            LIMIT 20
        """).fetchall()

        # New Svjetionik opinions, newest first.
        opinions = conn.execute("""
            SELECT m.id, m.tema_naziv, m.tvrdnja, m.korisnik_pseudonim, m.stvoreno_at,
                   (SELECT COUNT(*) FROM svjetionik_odgovori r WHERE r.misljenje_id=m.id) AS reply_count,
                   (SELECT COUNT(*) FROM svjetionik_predvidjanja p WHERE p.misljenje_id=m.id) AS prediction_count
            FROM svjetionik_misljenja m
            ORDER BY m.id DESC
            LIMIT 12
        """).fetchall()

    topics = []
    for x in topics_raw:
        tv = topic_view(x)
        tv["title"] = tv["naziv"]
        tv["participants"] = tv.get("opinion_count", 0) + tv.get("agora_count", 0)
        tv["avg_score"] = None
        topics.append(tv)
    return render_template("index.html", topics=topics, legacy_args=legacy_args, opinions=opinions)

@app.get("/topic/<int:topic_id>")
def topic(topic_id):
    with db() as conn:
        t = conn.execute("""
            SELECT id, naziv, COALESCE(aktivna, TRUE) AS aktivna
            FROM teme WHERE id=%s
        """, (topic_id,)).fetchone()
        if not t or not t["aktivna"]:
            abort(404)

        args = conn.execute("""
            SELECT id, korisnik, tema, tekst, datum, ton,
                   ocjena_analitika, ocjena_empatija, ocjena_sinteza, ocjena_suglasje
            FROM argumenti WHERE tema=%s ORDER BY id DESC
        """, (t["naziv"],)).fetchall()

        opinions = conn.execute("""
            SELECT m.*,
                   m.korisnik_pseudonim AS pseudonym,
                   m.stvoreno_at AS created_at,
                   m.tvrdnja AS claim,
                   m.dokaz AS evidence_text,
                   m.pretpostavke AS assumptions_text,
                   m.kontraargument AS counterargument_text,
                   m.zakljucak AS conclusion,
                   (SELECT COUNT(*) FROM svjetionik_odgovori r WHERE r.misljenje_id=m.id) AS reply_count,
                   (SELECT COUNT(*) FROM svjetionik_predvidjanja p WHERE p.misljenje_id=m.id) AS prediction_count
            FROM svjetionik_misljenja m
            WHERE m.tema_id=%s
            ORDER BY m.id DESC
        """, (topic_id,)).fetchall()

        for o in opinions:
            a = conn.execute("""
                SELECT jasnoća, logika, dokazi, pretpostavke, kontraargumenti, provjerljivost
                FROM svjetionik_analize
                WHERE misljenje_id=%s ORDER BY id DESC LIMIT 1
            """, (o["id"],)).fetchone()
            o["analysis"] = a

        replies = {}
        for o in opinions:
            replies[o["id"]] = conn.execute("""
                SELECT korisnik_pseudonim, tekst, stvoreno_at
                FROM svjetionik_odgovori
                WHERE misljenje_id=%s ORDER BY id
            """, (o["id"],)).fetchall()

    tv = topic_view(t)
    return render_template("topic.html", topic=tv, opinions=opinions, legacy_args=args, replies=replies)

@app.get("/topic/<int:topic_id>/write")
def write(topic_id):
    with db() as conn:
        t = conn.execute("SELECT id,naziv,COALESCE(aktivna,TRUE) aktivna FROM teme WHERE id=%s", (topic_id,)).fetchone()
    if not t or not t["aktivna"]:
        abort(404)
    return render_template("write.html", topic=topic_view(t))

@app.post("/topic/<int:topic_id>/opinion")
def save_opinion(topic_id):
    if not validate_csrf():
        abort(400)

    user = current_user(create=True)
    fields = {
        k: request.form.get(k, "").strip()
        for k in ["claim", "argument", "evidence_text", "assumptions_text", "counterargument_text", "conclusion"]
    }
    combined = "\n\n".join(v for v in fields.values() if v)
    if len(combined) < 20:
        flash("Argument mora imati barem 20 znakova.", "error")
        return redirect(url_for("write", topic_id=topic_id))

    prediction = request.form.get("prediction_text", "").strip()
    target = request.form.get("target_date", "").strip()

    if prediction or target:
        if not prediction or not target:
            flash("Predviđanje i datum provjere moraju biti uneseni zajedno.", "error")
            return redirect(url_for("write", topic_id=topic_id))
        try:
            target_date = date.fromisoformat(target)
            if target_date <= date.today():
                flash("Datum provjere mora biti u budućnosti.", "error")
                return redirect(url_for("write", topic_id=topic_id))
        except ValueError:
            flash("Datum provjere nije valjan.", "error")
            return redirect(url_for("write", topic_id=topic_id))

    with db() as conn:
        t = conn.execute("SELECT * FROM teme WHERE id=%s AND COALESCE(aktivna,TRUE)=TRUE", (topic_id,)).fetchone()
        if not t:
            abort(404)
        tv = topic_view(t)
        scores = analyze(combined, tv)

        m = conn.execute("""
            INSERT INTO svjetionik_misljenja
            (korisnik_ip, korisnik_pseudonim, tema_id, tema_naziv,
             tvrdnja, argument, dokaz, pretpostavke, kontraargument,
             zakljucak, predvidjanje, datum_predvidjanja)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            user["ip_adresa"], user["pseudonim"], topic_id, t["naziv"],
            fields["claim"], fields["argument"], fields["evidence_text"],
            fields["assumptions_text"], fields["counterargument_text"],
            fields["conclusion"], prediction, target or None
        )).fetchone()

        conn.execute("""
            INSERT INTO svjetionik_verzije_misljenja
            (misljenje_id, verzija, content, razlog)
            VALUES (%s,1,%s,%s)
        """, (
            m["id"],
            Jsonb({
                "tvrdnja": fields["claim"],
                "argument": fields["argument"],
                "dokaz": fields["evidence_text"],
                "pretpostavke": fields["assumptions_text"],
                "kontraargument": fields["counterargument_text"],
                "zakljucak": fields["conclusion"],
                "predvidjanje": prediction,
                "datum_predvidjanja": target or None,
            }),
            "Početna verzija mišljenja"
        ))

        conn.execute("""
            INSERT INTO svjetionik_analize
            (misljenje_id, model, verzija, jasnoća, logika, dokazi,
             pretpostavke, kontraargumenti, provjerljivost, obrazlozenje, raw_result)
            VALUES (%s,'heuristika','v5.3',%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            m["id"], scores["jasnoća"], scores["logika"], scores["dokazi"],
            scores["pretpostavke"], scores["kontraargumenti"], scores["provjerljivost"],
            "Privremena heuristička analiza. Ne utvrđuje istinu; služi kao početna struktura prije pravog AI analizatora.",
            Jsonb(scores)
        ))

        conn.execute("""
            INSERT INTO svjetionik_ai_dogadaji (misljenje_id, model, vrsta, input, output)
            VALUES (%s,'heuristika','analiza',%s,%s)
        """, (
            m["id"],
            Jsonb({"vrsta": "početna", "tekst": combined}),
            Jsonb(scores)
        ))

        if prediction:
            conn.execute("""
                INSERT INTO svjetionik_predvidjanja
                (misljenje_id, predvidjanje, rok)
                VALUES (%s,%s,%s)
            """, (m["id"], prediction, target))

    flash("Mišljenje je spremljeno u arhivu.", "success")
    return redirect(url_for("topic", topic_id=topic_id))

@app.post("/opinion/<int:opinion_id>/reply")
def save_reply(opinion_id):
    if not validate_csrf():
        abort(400)
    text = request.form.get("text", "").strip()
    if len(text) < 5:
        flash("Protuargument/odgovor mora imati barem 5 znakova.", "error")
        return redirect(request.referrer or url_for("index"))

    user = current_user(create=True)
    with db() as conn:
        exists = conn.execute("SELECT id FROM svjetionik_misljenja WHERE id=%s", (opinion_id,)).fetchone()
        if not exists:
            abort(404)
        conn.execute("""
            INSERT INTO svjetionik_odgovori
            (misljenje_id, korisnik_ip, korisnik_pseudonim, tekst)
            VALUES (%s,%s,%s,%s)
        """, (opinion_id, user["ip_adresa"], user["pseudonim"], text))
    return redirect(request.referrer or url_for("index"))


@app.get("/opinion/<int:opinion_id>")
def opinion_detail(opinion_id):
    with db() as conn:
        m = conn.execute("SELECT * FROM svjetionik_misljenja WHERE id=%s", (opinion_id,)).fetchone()
        if not m:
            abort(404)
        analyses = conn.execute("""
            SELECT model, verzija, jasnoća, logika, dokazi, pretpostavke,
                   kontraargumenti, provjerljivost, obrazlozenje, stvoreno_at
            FROM svjetionik_analize WHERE misljenje_id=%s ORDER BY id DESC
        """, (opinion_id,)).fetchall()
        replies = conn.execute("""
            SELECT korisnik_pseudonim, tekst, stvoreno_at
            FROM svjetionik_odgovori WHERE misljenje_id=%s ORDER BY id
        """, (opinion_id,)).fetchall()
        predictions = conn.execute("""
            SELECT * FROM svjetionik_predvidjanja
            WHERE misljenje_id=%s ORDER BY id DESC
        """, (opinion_id,)).fetchall()
    return render_template("opinion.html", opinion=m, analyses=analyses,
                           replies=replies, predictions=predictions)

@app.get("/predictions")
def predictions():
    with db() as conn:
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
    return render_template("predictions.html", predictions=rows)

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
    if request.method == "POST":
        if not validate_csrf():
            abort(400)
        if ADMIN_PASSWORD and secrets.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session["admin_logged"] = True
            return redirect(url_for("admin"))
        flash("Pogrešna administratorska lozinka.", "error")
    return render_template("admin_login.html")

@app.post("/admin/logout")
def admin_logout():
    if not validate_csrf():
        abort(400)
    session["admin_logged"] = False
    return redirect(url_for("index"))

@app.get("/admin")
def admin():
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
