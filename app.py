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
    """Initial analytical profile of the claim.
    This is not a truth verdict and not a dialogue with AI.
    It is a starting measurement before human criticism begins.
    """
    lower = text.lower()
    words = len(text.split())
    evidence_terms = ["izvor", "podat", "studij", "istraživ", "dokaz", "statistik", "prema", "mjeren"]
    counter_terms = ["ali", "međutim", "s druge strane", "suprotno", "prigovor", "kritika", "ovisno"]
    logic_terms = ["jer", "zato", "stoga", "dakle", "ako", "onda", "uzrok", "posljedica", "zbog"]
    prediction_terms = ["predviđ", "očekujem", "do 20", "u budućnosti", "za godinu", "za 5 godina"]

    criteria = ((topic or {}).get("ai_criteria") or "").lower() if topic else ""
    clarity = min(10, max(2, 4 + words // 18 + int(any(ch in text for ch in ".,;:"))))
    logic = min(10, 4 + min(5, sum(x in lower for x in logic_terms)))
    evidence = min(10, 3 + 3 * int(any(x in lower for x in evidence_terms)) + int("http" in lower))
    assumptions = min(10, 4 + int("ako" in lower) + int("pretpostav" in lower) + int("vjerojat" in lower))
    counter = min(10, 3 + 4 * int(any(x in lower for x in counter_terms)))
    verifiability = min(10, 3 + 4 * int(any(x in lower for x in prediction_terms)) + int("datum" in lower or "%" in lower or any(ch.isdigit() for ch in text)))

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

def analysis_average(scores):
    vals = [scores[k] for k in ("jasnoća", "logika", "dokazi", "pretpostavke", "kontraargumenti", "provjerljivost")]
    return round(sum(vals) / len(vals), 1)

def add_analysis_view(row):
    if not row:
        return row
    d = dict(row)
    d["otpornost"] = d.get("kontraargumenti")
    d["pocetna_ocjena"] = round(sum(d.get(k, 0) for k in ("jasnoća", "logika", "dokazi", "pretpostavke", "kontraargumenti", "provjerljivost")) / 6, 1)
    return d

def admin_guard():
    if not session.get(ADMIN_SESSION_KEY):
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
        return {"status": "ok", "database": "connected", "schema": "v5.6.1"}
    except Exception as exc:
        app.logger.exception("Health check failed")
        return {"status": "error", "database": "unavailable", "detail": str(exc)}, 500

@app.get("/")
def index():
    with db() as conn:
        topics_raw = conn.execute("""
            SELECT t.id, t.naziv, COALESCE(t.aktivna, TRUE) AS aktivna,
                   (SELECT COUNT(*) FROM svjetionik_misljenja m WHERE m.tema_id=t.id) AS opinion_count
            FROM teme t
            WHERE COALESCE(t.aktivna, TRUE)=TRUE
            ORDER BY t.id
        """).fetchall()

        opinions = conn.execute("""
            SELECT m.id, m.tema_naziv, m.tvrdnja, m.korisnik_pseudonim, m.stvoreno_at,
                   (SELECT COUNT(*) FROM svjetionik_odgovori r WHERE r.misljenje_id=m.id) AS reply_count
            FROM svjetionik_misljenja m
            ORDER BY m.id DESC
            LIMIT 12
        """).fetchall()

    topics = []
    for x in topics_raw:
        tv = topic_view(x)
        tv["title"] = tv["naziv"]
        tv["participants"] = tv.get("opinion_count", 0)
        tv["avg_score"] = None
        topics.append(tv)
    return render_template("index.html", topics=topics, opinions=opinions)

@app.get("/topic/<int:topic_id>")
def topic(topic_id):
    with db() as conn:
        t = conn.execute("""
            SELECT id, naziv, COALESCE(aktivna, TRUE) AS aktivna
            FROM teme WHERE id=%s
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
                SELECT jasnoca, logika, dokazi, pretpostavke, kontraargumenti, provjerljivost, obrazlozenje
                FROM svjetionik_analize
                WHERE misljenje_id=%s ORDER BY id DESC LIMIT 1
            """, (o["id"],)).fetchone()
            o["analysis"] = add_analysis_view(a)
            replies[o["id"]] = conn.execute("""
                SELECT korisnik_pseudonim, tekst, stvoreno_at
                FROM svjetionik_odgovori
                WHERE misljenje_id=%s ORDER BY id
            """, (o["id"],)).fetchall()

    tv = topic_view(t)
    return render_template("topic.html", topic=tv, opinions=opinions, replies=replies)

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

    claim = request.form.get("claim", "").strip()
    if len(claim) < 20:
        flash("Tvrdnja mora imati barem 20 znakova.", "error")
        return redirect(url_for("write", topic_id=topic_id))

    user = current_user(create=True)
    with db() as conn:
        t = conn.execute("SELECT * FROM teme WHERE id=%s AND COALESCE(aktivna,TRUE)=TRUE", (topic_id,)).fetchone()
        if not t:
            abort(404)
        tv = topic_view(t)
        scores = analyze(claim, tv)

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
            "Početna analitička procjena tvrdnje. Ne utvrđuje istinu i ne sudjeluje u raspravi; služi kao početna mjerna točka prije ljudske kritike.",
            Jsonb(scores)
        ))

        conn.execute("""
            INSERT INTO svjetionik_ai_dogadaji (misljenje_id, model, vrsta, ulaz, izlaz)
            VALUES (%s,'heuristika','početna_analiza',%s,%s)
        """, (m["id"], Jsonb({"tema": t["naziv"], "tvrdnja": claim, "ai_criteria": tv.get("ai_criteria", "")}), Jsonb(scores)))

    flash("Stav je spremljen i otvoren ljudskoj kritici.", "success")
    return redirect(url_for("opinion_detail", opinion_id=m["id"]))

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
            SELECT model, verzija_modela, jasnoca, logika, dokazi, pretpostavke,
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
                "open_predictions": conn.execute(
                    "SELECT COUNT(*) AS n FROM svjetionik_predvidjanja WHERE status='otvoreno'"
                ).fetchone()["n"],
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

        # Postojeća Neon tablica 'teme' ima samo naziv/aktivna.
        # Bogati urednički sadržaj ostaje u TOPIC_CONTENT dok ne uvedemo
        # zasebnu trajnu tablicu.
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
                conn.commit()

            TOPIC_CONTENT[name] = {
                "intro": request.form.get("intro", "").strip(),
                "question": request.form.get("question", "").strip(),
                "goal": request.form.get("goal", "").strip(),
                "key_questions": request.form.get("key_questions", "").strip(),
                "rules": request.form.get("rules", "").strip(),
                "ai_criteria": request.form.get("ai_criteria", "").strip(),
                "sources": request.form.get("sources", "").strip(),
            }

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
                conn.commit()

                TOPIC_CONTENT[name] = {
                    "intro": request.form.get("intro", "").strip(),
                    "question": request.form.get("question", "").strip(),
                    "goal": request.form.get("goal", "").strip(),
                    "key_questions": request.form.get("key_questions", "").strip(),
                    "rules": request.form.get("rules", "").strip(),
                    "ai_criteria": request.form.get("ai_criteria", "").strip(),
                    "sources": request.form.get("sources", "").strip(),
                }

                if old_name != name:
                    TOPIC_CONTENT.pop(old_name, None)

                app.logger.info(
                    "Tema uređena: id=%s stari_naziv=%s novi_naziv=%s",
                    topic_id, old_name, name
                )
                flash("Tema je spremljena.", "success")
                return redirect(url_for("admin_v54"))

            topic = topic_view(topic)
            return render_template("admin_topic_v54.html", mode="edit", topic=topic)

    except Exception as exc:
        app.logger.exception("Uređivanje teme nije uspjelo: %s", exc)
        flash(f"Greška pri uređivanju teme: {exc}", "error")
        return redirect(url_for("admin_v54"))


@app.post("/admin/topic/<int:topic_id>/toggle")
def admin_topic_toggle_v54(topic_id):
    if not admin_required_v54():
        return admin_redirect_v54()
    try:
        with db() as conn:
            conn.execute("UPDATE teme SET aktivna=NOT COALESCE(aktivna,FALSE) WHERE id=%s", (topic_id,))
        flash("Status teme je promijenjen.", "success")
    except Exception as exc:
        flash(f"Greška: {exc}", "error")
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
        return render_template("admin_opinion_detail_v54.html", opinion=opinion, analyses=analyses,
                               replies=replies, predictions=predictions)
    except Exception as exc:
        flash(f"Greška: {exc}", "error")
        return redirect(url_for("admin_opinions_v54"))

@app.get("/admin/predictions")
def admin_predictions_v54():
    if not admin_required_v54():
        return admin_redirect_v54()
    try:
        with db() as conn:
            predictions = conn.execute("""SELECT p.*,m.tvrdnja,m.korisnik_pseudonim,t.naziv AS topic_title
                FROM svjetionik_predvidjanja p JOIN svjetionik_misljenja m ON m.id=p.misljenje_id
                LEFT JOIN teme t ON t.id=m.tema_id
                ORDER BY CASE WHEN p.status='otvoreno' THEN 0 ELSE 1 END,p.rok ASC NULLS LAST""").fetchall()
        return render_template("admin_predictions_v54.html", predictions=predictions)
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
