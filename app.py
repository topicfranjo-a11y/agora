import os
import secrets
from datetime import date
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, abort, flash, jsonify
import psycopg
from psycopg.rows import dict_row

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "promijenite-secret-key")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "promijenite-admin-password")


def db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL nije postavljen.")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def csrf_token():
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def check_csrf():
    if request.form.get("_csrf") != session.get("_csrf"):
        abort(400, description="Neispravan CSRF token.")


@app.context_processor
def inject_globals():
    pseudonim = session.get("pseudonim", "Gost")
    try:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM svjetionik_misljenja")
                broj_misljenja = cur.fetchone()["n"]
    except Exception:
        broj_misljenja = 0
    return {"csrf": csrf_token(), "pseudonim": pseudonim, "broj_misljenja": broj_misljenja}


def current_identity():
    pseudonim = session.get("pseudonim")
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "nepoznato")
    if "," in ip:
        ip = ip.split(",")[0].strip()
    if not pseudonim:
        pseudonim = "Mislioc-" + secrets.token_hex(3).upper()
        session["pseudonim"] = pseudonim
    return ip, pseudonim


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def init_db():
    # V5.1 koristi tablice koje su već stvorene u Neon bazi.
    required = [
        "svjetionik_misljenja",
        "svjetionik_odgovori",
        "svjetionik_analize",
        "svjetionik_predvidjanja",
        "svjetionik_verzije_misljenja",
        "svjetionik_ai_dogadaji",
    ]
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema='public'
                  AND table_name = ANY(%s)
            """, (required,))
            found = {r["table_name"] for r in cur.fetchall()}
    missing = [x for x in required if x not in found]
    if missing:
        raise RuntimeError("Nedostaju tablice: " + ", ".join(missing))


def get_topics():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, naziv, aktivna FROM teme ORDER BY id")
            return cur.fetchall()


def get_topic(topic_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, naziv, aktivna FROM teme WHERE id=%s", (topic_id,))
            return cur.fetchone()


def score_text(text):
    # Privremena analiza. Pravi AI analizator ide u sljedećem koraku.
    words = len((text or "").split())
    jasnoća = min(10, 4 + words / 35)
    logika = min(10, 4 + words / 45)
    dokazi = min(10, 3 + words / 60)
    pretpostavke = min(10, 4 + words / 50)
    kontra = min(10, 3 + words / 55)
    provjerljivost = min(10, 4 + words / 45)
    return {
        "jasnoca": round(jasnoća, 2),
        "logika": round(logika, 2),
        "dokazi": round(dokazi, 2),
        "pretpostavke": round(pretpostavke, 2),
        "kontraargumenti": round(kontra, 2),
        "provjerljivost": round(provjerljivost, 2),
    }


@app.get("/health")
def health():
    try:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                cur.fetchone()
        return jsonify(status="ok", database="connected")
    except Exception as exc:
        return jsonify(status="error", database="unavailable", detail=str(exc)), 503


@app.get("/")
def index():
    topics = get_topics()
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.*, 
                       COUNT(DISTINCT o.id) AS broj_odgovora
                FROM svjetionik_misljenja m
                LEFT JOIN svjetionik_odgovori o ON o.misljenje_id=m.id
                GROUP BY m.id
                ORDER BY m.stvoreno_at DESC
                LIMIT 20
            """)
            misljenja = cur.fetchall()
    return render_template("index.html", topics=topics, misljenja=misljenja)


@app.get("/tema/<int:topic_id>")
def topic(topic_id):
    tema = get_topic(topic_id)
    if not tema:
        abort(404)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.*,
                       COUNT(DISTINCT o.id) AS broj_odgovora,
                       AVG(a.jasnoca) AS avg_jasnoca,
                       AVG(a.logika) AS avg_logika,
                       AVG(a.dokazi) AS avg_dokazi,
                       AVG(a.pretpostavke) AS avg_pretpostavke,
                       AVG(a.kontraargumenti) AS avg_kontraargumenti,
                       AVG(a.provjerljivost) AS avg_provjerljivost
                FROM svjetionik_misljenja m
                LEFT JOIN svjetionik_odgovori o ON o.misljenje_id=m.id
                LEFT JOIN svjetionik_analize a ON a.misljenje_id=m.id
                WHERE m.tema_id=%s
                GROUP BY m.id
                ORDER BY m.stvoreno_at DESC
            """, (topic_id,))
            misljenja = cur.fetchall()
    return render_template("topic.html", tema=tema, misljenja=misljenja)


@app.route("/tema/<int:topic_id>/novo", methods=["GET", "POST"])
def novo_misljenje(topic_id):
    tema = get_topic(topic_id)
    if not tema:
        abort(404)
    if request.method == "POST":
        check_csrf()
        ip, pseudonim = current_identity()
        fields = {k: request.form.get(k, "").strip() for k in [
            "tvrdnja", "argument", "dokaz", "pretpostavke",
            "kontraargument", "zakljucak", "predvidjanje", "datum_predvidjanja"
        ]}
        if not fields["tvrdnja"]:
            flash("Tvrdnja je obavezna.", "error")
            return render_template("write.html", tema=tema)
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO svjetionik_misljenja
                    (korisnik_ip, korisnik_pseudonim, tema_id, tema_naziv,
                     tvrdnja, argument, dokaz, pretpostavke, kontraargument,
                     zakljucak, predvidjanje, datum_predvidjanja)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                """, (
                    ip, pseudonim, tema["id"], tema["naziv"],
                    fields["tvrdnja"], fields["argument"], fields["dokaz"],
                    fields["pretpostavke"], fields["kontraargument"],
                    fields["zakljucak"], fields["predvidjanje"],
                    fields["datum_predvidjanja"] or None
                ))
                mid = cur.fetchone()["id"]
                cur.execute("""
                    INSERT INTO svjetionik_verzije_misljenja
                    (misljenje_id, verzija, sadrzaj, razlog_promjene)
                    VALUES (%s,1,%s,%s)
                """, (mid, psycopg.types.json.Jsonb(fields), "Početna verzija"))
        flash("Mišljenje je spremljeno.", "ok")
        return redirect(url_for("misljenje", misljenje_id=mid))
    return render_template("write.html", tema=tema)


@app.get("/misljenje/<int:misljenje_id>")
def misljenje(misljenje_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM svjetionik_misljenja WHERE id=%s", (misljenje_id,))
            m = cur.fetchone()
            if not m:
                abort(404)
            cur.execute("""
                SELECT * FROM svjetionik_analize
                WHERE misljenje_id=%s ORDER BY stvoreno_at DESC
            """, (misljenje_id,))
            analize = cur.fetchall()
            cur.execute("""
                SELECT * FROM svjetionik_odgovori
                WHERE misljenje_id=%s ORDER BY stvoreno_at
            """, (misljenje_id,))
            odgovori = cur.fetchall()
            cur.execute("""
                SELECT * FROM svjetionik_predvidjanja
                WHERE misljenje_id=%s ORDER BY rok
            """, (misljenje_id,))
            predvidjanja = cur.fetchall()
    return render_template("opinion.html", m=m, analize=analize,
                           odgovori=odgovori, predvidjanja=predvidjanja)


@app.post("/misljenje/<int:misljenje_id>/odgovor")
def odgovor(misljenje_id):
    check_csrf()
    ip, pseudonim = current_identity()
    tekst = request.form.get("tekst", "").strip()
    if not tekst:
        flash("Odgovor ne može biti prazan.", "error")
    else:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO svjetionik_odgovori
                    (misljenje_id, korisnik_ip, korisnik_pseudonim, tekst)
                    VALUES (%s,%s,%s,%s)
                """, (misljenje_id, ip, pseudonim, tekst))
        flash("Odgovor je dodan.", "ok")
    return redirect(url_for("misljenje", misljenje_id=misljenje_id))


@app.post("/misljenje/<int:misljenje_id>/analiziraj")
def analiziraj(misljenje_id):
    check_csrf()
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM svjetionik_misljenja WHERE id=%s", (misljenje_id,))
            m = cur.fetchone()
            if not m:
                abort(404)
    tekst = " ".join(filter(None, [
        m["tvrdnja"], m["argument"], m["dokaz"], m["pretpostavke"],
        m["kontraargument"], m["zakljucak"]
    ]))
    s = score_text(tekst)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO svjetionik_analize
                (misljenje_id, model, verzija_modela, jasnoća, logika, dokazi,
                 pretpostavke, kontraargumenti, provjerljivost, obrazlozenje, sirovi_rezultat)
                VALUES (%s,'heuristika','v5.1',%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                misljenje_id, s["jasnoca"], s["logika"], s["dokazi"],
                s["pretpostavke"], s["kontraargumenti"], s["provjerljivost"],
                "Privremena heuristička analiza; nije procjena istinitosti.",
                psycopg.types.json.Jsonb(s)
            ))
    flash("Privremena analiza je izrađena. Pravi AI analizator slijedi.", "ok")
    return redirect(url_for("misljenje", misljenje_id=misljenje_id))


@app.get("/predvidjanja")
def predvidjanja():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.*, m.tvrdnja, m.korisnik_pseudonim, m.tema_naziv
                FROM svjetionik_predvidjanja p
                JOIN svjetionik_misljenja m ON m.id=p.misljenje_id
                ORDER BY p.rok, p.id
            """)
            rows = cur.fetchall()
    return render_template("predictions.html", predvidjanja=rows)


@app.route("/profil", methods=["GET", "POST"])
def profil():
    if request.method == "POST":
        check_csrf()
        p = request.form.get("pseudonim", "").strip()
        if p:
            session["pseudonim"] = p[:80]
            flash("Pseudonim je promijenjen.", "ok")
    ip, pseudonim = current_identity()
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) AS n
                FROM svjetionik_misljenja
                WHERE korisnik_pseudonim=%s
            """, (pseudonim,))
            n = cur.fetchone()["n"]
    return render_template("profile.html", pseudonim=pseudonim, broj=n)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        check_csrf()
        if secrets.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session["admin"] = True
            return redirect(url_for("admin"))
        flash("Pogrešna lozinka.", "error")
    return render_template("admin_login.html")


@app.post("/admin/logout")
def admin_logout():
    check_csrf()
    session.pop("admin", None)
    return redirect(url_for("index"))


@app.get("/admin")
@admin_required
def admin():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT t.*, COUNT(m.id) AS broj_misljenja
                FROM teme t
                LEFT JOIN svjetionik_misljenja m ON m.tema_id=t.id
                GROUP BY t.id
                ORDER BY t.id
            """)
            teme = cur.fetchall()
            cur.execute("""
                SELECT p.*, m.tvrdnja, m.tema_naziv
                FROM svjetionik_predvidjanja p
                JOIN svjetionik_misljenja m ON m.id=p.misljenje_id
                ORDER BY p.rok
            """)
            predvidjanja = cur.fetchall()
    return render_template("admin.html", teme=teme, predvidjanja=predvidjanja)


@app.post("/admin/predvidjanje/<int:pid>")
@admin_required
def admin_predvidjanje(pid):
    check_csrf()
    status = request.form.get("status", "otvoreno")
    ishod = request.form.get("ishod", "").strip()
    biljeska = request.form.get("biljeska", "").strip()
    allowed = {"otvoreno", "ostvareno", "nije_ostvareno", "djelomicno", "neprovjerljivo"}
    if status not in allowed:
        abort(400)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE svjetionik_predvidjanja
                SET status=%s, ishod=%s, biljeska=%s,
                    provjereno_at=CASE WHEN %s='otvoreno' THEN NULL ELSE NOW() END
                WHERE id=%s
            """, (status, ishod or None, biljeska or None, status, pid))
    return redirect(url_for("admin"))


@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", code=400, message=str(e)), 400


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Stranica nije pronađena."), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", code=500,
                           message="Interna greška. Provjerite terminal ili hosting log."), 500


if __name__ == "__main__":
    try:
        init_db()
        print("Neon/V5.1 provjera baze: OK")
    except Exception as exc:
        print("Upozorenje pri provjeri baze:", exc)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
