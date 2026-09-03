import os
from datetime import datetime
from functools import wraps

from flask import Flask, abort, flash, redirect, render_template_string, request, session, url_for
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")

DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

def db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL nije postavljen.")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapper

BASE = """
<!doctype html>
<html lang="hr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title or "Civilizacijski svjetionik" }}</title>
<style>
:root{--bg:#071018;--panel:#0d1b26;--line:#244052;--text:#eaf4f8;--muted:#9bb0bc;--accent:#00d9ff}
*{box-sizing:border-box} body{margin:0;background:radial-gradient(circle at top,#102431 0,#071018 45%,#04090d 100%);color:var(--text);font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}
a{color:#7deaff;text-decoration:none} a:hover{text-decoration:underline}
header{padding:22px max(20px,calc((100% - 1180px)/2));border-bottom:1px solid var(--line);background:#071018ee;position:sticky;top:0;z-index:3}
nav{display:flex;gap:18px;align-items:center;flex-wrap:wrap}.brand{font-weight:800;font-size:20px;margin-right:auto}
main{max-width:1180px;margin:30px auto;padding:0 20px}.hero{padding:28px;border:1px solid var(--line);border-radius:18px;background:#0b1822cc;box-shadow:0 0 40px #0008}
h1,h2,h3{line-height:1.2} .muted{color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:16px}
.card{padding:20px;border:1px solid var(--line);border-radius:15px;background:var(--panel)}
.badge{display:inline-block;padding:4px 9px;border-radius:999px;background:#123140;color:#9cefff;font-size:12px}
.score{font-size:28px;font-weight:800;color:#7deaff}.scores{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
label{display:block;margin:12px 0 5px;font-weight:650}input,textarea,select{width:100%;padding:11px;border:1px solid #355467;border-radius:9px;background:#07131b;color:var(--text);font:inherit}textarea{min-height:110px}
button,.btn{display:inline-block;padding:10px 15px;border:0;border-radius:9px;background:#0fb8d8;color:#031016;font-weight:750;cursor:pointer}.btn.secondary{background:#17313e;color:#dff8ff}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}
.flash{padding:12px 15px;border:1px solid #39606f;border-radius:10px;margin-bottom:15px;background:#102733}
.beam{width:54px;height:54px;border-radius:50%;border:2px solid var(--accent);display:inline-flex;align-items:center;justify-content:center;box-shadow:0 0 22px var(--accent);margin-right:10px}
@media(max-width:650px){.scores{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<header><nav>
<a class="brand" href="{{ url_for('index') }}"><span class="beam">✦</span> CIVILIZACIJSKI SVJETIONIK</a>
<a href="{{ url_for('index') }}">Početna</a>
<a href="{{ url_for('predvidjanja') }}">Predviđanja</a>
<a href="{{ url_for('profil') }}">Profil</a>
{% if session.get("admin") %}<a href="{{ url_for('admin') }}">Admin</a><a href="{{ url_for('admin_logout') }}">Odjava</a>{% endif %}
</nav></header>
<main>
{% with messages=get_flashed_messages() %}{% for m in messages %}<div class="flash">{{m}}</div>{% endfor %}{% endwith %}
{{ body|safe }}
</main>
</body></html>
"""

def page(title, body):
    return render_template_string(BASE, title=title, body=body)

@app.get("/health")
def health():
    try:
        with db() as conn:
            conn.execute("SELECT 1")
        return {"status":"ok","database":"connected"}
    except Exception as e:
        return {"status":"error","database":"unavailable","detail":str(e)}, 500

@app.get("/")
def index():
    with db() as conn:
        topics = conn.execute("""
            SELECT id, naziv, aktivna
            FROM teme ORDER BY id
        """).fetchall()
        args = conn.execute("""
            SELECT id, korisnik, tema, tekst, datum, ton,
                   ocjena_analitika, ocjena_empatija, ocjena_sinteza, ocjena_suglasje
            FROM argumenti ORDER BY id DESC LIMIT 20
        """).fetchall()
        opinions = conn.execute("""
            SELECT id, korisnik_pseudonim, tema_naziv, tvrdnja, stvoreno_at
            FROM svjetionik_misljenja ORDER BY id DESC LIMIT 12
        """).fetchall()

    body = render_template_string("""
    <section class="hero">
      <h1>Čim si se rodio, postao si prošlost.</h1>
      <p>Ovaj trenutak je tvoj prezent. Iskoristi ga da humano oblikuješ budućnost.</p>
      <p class="muted">Nova verzija prvo povezuje postojeću Agora bazu, a zatim gradi strukturirani sloj Svjetionika mišljenja.</p>
    </section>

    <h2>Postojeće teme Agora</h2>
    <div class="grid">
    {% for t in topics %}
      <div class="card"><span class="badge">{{"AKTIVNA" if t.aktivna else "NEAKTIVNA"}}</span><h3>{{t.naziv}}</h3>
      <a class="btn" href="{{url_for('topic', topic_id=t.id)}}">Otvori temu</a></div>
    {% else %}<p class="muted">Nema tema.</p>{% endfor %}
    </div>

    <h2>Postojeći Agora argumenti</h2>
    <div class="grid">
    {% for a in args %}
      <article class="card">
        <span class="badge">{{a.tema}}</span>
        <h3>{{a.korisnik}}</h3>
        <p>{{a.tekst}}</p>
        <p class="muted">{{a.datum}}</p>
        <a class="btn secondary" href="{{url_for('argument', argument_id=a.id)}}">Detalji</a>
      </article>
    {% else %}<p class="muted">Nema argumenata.</p>{% endfor %}
    </div>

    <h2>Najnovija mišljenja Svjetionika</h2>
    <div class="grid">
    {% for m in opinions %}
      <article class="card">
        <span class="badge">{{m.tema_naziv}}</span>
        <h3>{{m.tvrdnja}}</h3>
        <p class="muted">{{m.korisnik_pseudonim}} · {{m.stvoreno_at}}</p>
        <a class="btn secondary" href="{{url_for('opinion', opinion_id=m.id)}}">Otvori</a>
      </article>
    {% else %}<p class="muted">Još nema novih mišljenja.</p>{% endfor %}
    </div>
    """, topics=topics, args=args, opinions=opinions)
    return page("Početna", body)

@app.get("/tema/<int:topic_id>")
def topic(topic_id):
    with db() as conn:
        t = conn.execute("SELECT * FROM teme WHERE id=%s", (topic_id,)).fetchone()
        if not t: abort(404)
        args = conn.execute("""
            SELECT id, korisnik, tema, tekst, datum, ton
            FROM argumenti WHERE tema=%s ORDER BY id DESC
        """, (t["naziv"],)).fetchall()
    body = render_template_string("""
    <div class="hero"><span class="badge">TEMA</span><h1>{{t.naziv}}</h1>
    <div class="actions"><a class="btn" href="{{url_for('new_opinion', topic_id=t.id)}}">Iznesi mišljenje</a></div></div>
    <h2>Argumenti</h2><div class="grid">
    {% for a in args %}<article class="card"><h3>{{a.korisnik}}</h3><p>{{a.tekst}}</p><p class="muted">{{a.datum}}</p>
    <a class="btn secondary" href="{{url_for('argument',argument_id=a.id)}}">Detalji</a></article>
    {% else %}<p class="muted">Za ovu temu još nema argumenata.</p>{% endfor %}
    </div>
    """,t=t,args=args)
    return page(t["naziv"],body)

@app.get("/argument/<int:argument_id>")
def argument(argument_id):
    with db() as conn:
        a=conn.execute("SELECT * FROM argumenti WHERE id=%s",(argument_id,)).fetchone()
    if not a: abort(404)
    body=render_template_string("""
    <div class="hero"><span class="badge">{{a.tema}}</span><h1>Argument #{{a.id}}</h1>
    <h2>{{a.korisnik}}</h2><p>{{a.tekst}}</p><p class="muted">{{a.datum}}</p></div>
    <h2>Postojeće metrike</h2>
    <div class="scores">
      <div class="card">Analitika<div class="score">{{a.ocjena_analitika if a.ocjena_analitika is not none else "—"}}</div></div>
      <div class="card">Empatija<div class="score">{{a.ocjena_empatija if a.ocjena_empatija is not none else "—"}}</div></div>
      <div class="card">Sinteza<div class="score">{{a.ocjena_sinteza if a.ocjena_sinteza is not none else "—"}}</div></div>
      <div class="card">Suglasje<div class="score">{{a.ocjena_suglasje if a.ocjena_suglasje is not none else "—"}}</div></div>
    </div>
    """,a=a)
    return page("Argument",body)

@app.route("/misljenje/novo/<int:topic_id>", methods=["GET","POST"])
def new_opinion(topic_id):
    with db() as conn:
        t=conn.execute("SELECT * FROM teme WHERE id=%s",(topic_id,)).fetchone()
    if not t: abort(404)
    if request.method=="POST":
        pseudo=(request.form.get("pseudonim") or "Gost").strip()
        ip=request.headers.get("X-Forwarded-For",request.remote_addr or "").split(",")[0].strip()
        fields={k:(request.form.get(k) or "").strip() for k in
                ["tvrdnja","argument","dokaz","pretpostavke","kontraargument","zakljucak","predvidjanje","datum_predvidjanja"]}
        if not fields["tvrdnja"] or not fields["zakljucak"]:
            flash("Tvrdnja i zaključak su obavezni.")
            return redirect(request.url)
        with db() as conn:
            m=conn.execute("""
              INSERT INTO svjetionik_misljenja
              (korisnik_ip,korisnik_pseudonim,tema_id,tema_naziv,tvrdnja,argument,dokaz,
               pretpostavke,kontraargument,zakljucak,predvidjanje,datum_predvidjanja)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
              RETURNING id
            """,(ip,pseudo,t["id"],t["naziv"],fields["tvrdnja"],fields["argument"],fields["dokaz"],
                 fields["pretpostavke"],fields["kontraargument"],fields["zakljucak"],
                 fields["predvidjanje"],fields["datum_predvidjanja"] or None)).fetchone()
            if fields["predvidjanje"] and fields["datum_predvidjanja"]:
                conn.execute("""
                  INSERT INTO svjetionik_predvidjanja (misljenje_id,predvidjanje,rok)
                  VALUES(%s,%s,%s)
                """,(m["id"],fields["predvidjanje"],fields["datum_predvidjanja"]))
        return redirect(url_for("opinion",opinion_id=m["id"]))
    body=render_template_string("""
    <div class="hero"><span class="badge">{{t.naziv}}</span><h1>Iznesi mišljenje</h1>
    <p class="muted">Struktura: tvrdnja → argument → dokaz → pretpostavke → kontraargument → zaključak → predviđanje.</p></div>
    <form method="post" class="card">
    <label>Pseudonim</label><input name="pseudonim" placeholder="Kako želiš biti prikazan?">
    {% for k,label in fields %}<label>{{label}}</label><textarea name="{{k}}" {% if k in ["tvrdnja","zakljucak"] %}required{% endif %}></textarea>{% endfor %}
    <label>Rok predviđanja</label><input type="date" name="datum_predvidjanja">
    <div class="actions"><button>Objavi mišljenje</button><a class="btn secondary" href="{{url_for('topic',topic_id=t.id)}}">Odustani</a></div>
    </form>
    """,t=t,fields=[("tvrdnja","Tvrdnja"),("argument","Argument"),("dokaz","Dokaz"),("pretpostavke","Pretpostavke"),("kontraargument","Kontraargument"),("zakljucak","Zaključak"),("predvidjanje","Predviđanje")])
    return page("Novo mišljenje",body)

@app.get("/misljenje/<int:opinion_id>")
def opinion(opinion_id):
    with db() as conn:
        m=conn.execute("SELECT * FROM svjetionik_misljenja WHERE id=%s",(opinion_id,)).fetchone()
        if not m: abort(404)
        analyses=conn.execute("""
          SELECT model, verzija, jasnoća, logika, dokazi, pretpostavke, kontraargumenti,
                 provjerljivost, obrazlozenje, stvoreno_at
          FROM svjetionik_analize WHERE misljenje_id=%s ORDER BY id DESC
        """,(opinion_id,)).fetchall()
        replies=conn.execute("""
          SELECT korisnik_pseudonim, tekst, stvoreno_at
          FROM svjetionik_odgovori WHERE misljenje_id=%s ORDER BY id
        """,(opinion_id,)).fetchall()
        preds=conn.execute("""
          SELECT * FROM svjetionik_predvidjanja WHERE misljenje_id=%s ORDER BY id DESC
        """,(opinion_id,)).fetchall()
    body=render_template_string("""
    <div class="hero"><span class="badge">{{m.tema_naziv}}</span><h1>{{m.tvrdnja}}</h1>
    <p class="muted">{{m.korisnik_pseudonim}} · {{m.stvoreno_at}}</p></div>
    <div class="grid">
    {% for key,label in [("argument","Argument"),("dokaz","Dokaz"),("pretpostavke","Pretpostavke"),("kontraargument","Kontraargument"),("zakljucak","Zaključak"),("predvidjanje","Predviđanje")] %}
      <section class="card"><h3>{{label}}</h3><p>{{m[key] or "—"}}</p></section>
    {% endfor %}
    </div>
    {% for an in analyses %}
      <h2>AI analiza · {{an.model}}</h2><div class="card"><div class="scores">
      {% for key,label in [("jasnoća","Jasnoća"),("logika","Logika"),("dokazi","Dokazi"),("pretpostavke","Pretpostavke"),("kontraargumenti","Kontraargumenti"),("provjerljivost","Provjerljivost")] %}
        <div><span class="muted">{{label}}</span><div class="score">{{an[key]}}</div></div>
      {% endfor %}</div><p>{{an.obrazlozenje}}</p></div>
    {% endfor %}
    {% if preds %}<h2>Predviđanja</h2>{% for p in preds %}<div class="card"><b>{{p.predvidjanje}}</b><p>Rok: {{p.rok}} · Status: {{p.status}}</p>{% if p.ishod %}<p>{{p.ishod}}</p>{% endif %}</div>{% endfor %}{% endif %}
    <h2>Protuargumenti i odgovori</h2>
    <div class="grid">{% for r in replies %}<div class="card"><b>{{r.korisnik_pseudonim}}</b><p>{{r.tekst}}</p><span class="muted">{{r.stvoreno_at}}</span></div>{% else %}<p class="muted">Još nema odgovora.</p>{% endfor %}</div>
    <form method="post" action="{{url_for('reply',opinion_id=m.id)}}" class="card">
      <label>Pseudonim</label><input name="pseudonim">
      <label>Odgovor</label><textarea name="tekst" required></textarea>
      <div class="actions"><button>Objavi odgovor</button><a class="btn secondary" href="{{url_for('analyze',opinion_id=m.id)}}">Pokreni privremenu analizu</a></div>
    </form>
    """,m=m,analyses=analyses,replies=replies,preds=preds)
    return page("Mišljenje",body)

@app.post("/misljenje/<int:opinion_id>/odgovor")
def reply(opinion_id):
    text=(request.form.get("tekst") or "").strip()
    if not text: return redirect(url_for("opinion",opinion_id=opinion_id))
    pseudo=(request.form.get("pseudonim") or "Gost").strip()
    with db() as conn:
        conn.execute("""
          INSERT INTO svjetionik_odgovori (misljenje_id,korisnik_ip,korisnik_pseudonim,tekst)
          VALUES(%s,%s,%s,%s)
        """,(opinion_id,request.remote_addr or "",pseudo,text))
    return redirect(url_for("opinion",opinion_id=opinion_id))

@app.get("/misljenje/<int:opinion_id>/analiziraj")
def analyze(opinion_id):
    with db() as conn:
        m=conn.execute("SELECT * FROM svjetionik_misljenja WHERE id=%s",(opinion_id,)).fetchone()
        if not m: abort(404)
        text=" ".join((m.get(k) or "") for k in ["tvrdnja","argument","dokaz","pretpostavke","kontraargument","zakljucak"])
        # Privremena heuristika: nije AI i ne predstavlja procjenu istine.
        scores={
          "jasnoća": min(10, max(0, 4 + len(m["tvrdnja"])//80)),
          "logika": min(10, max(0, 4 + (1 if m["argument"] else 0) + (1 if m["zakljucak"] else 0))),
          "dokazi": min(10, max(0, 3 + (3 if m["dokaz"] else 0))),
          "pretpostavke": min(10, max(0, 3 + (3 if m["pretpostavke"] else 0))),
          "kontraargumenti": min(10, max(0, 3 + (3 if m["kontraargument"] else 0))),
          "provjerljivost": min(10, max(0, 3 + (3 if m["predvidjanje"] else 0))),
        }
        explanation="Privremena heuristička analiza. Ne utvrđuje istinu i ne zamjenjuje budući AI analizator."
        conn.execute("""
          INSERT INTO svjetionik_analize
          (misljenje_id,model,verzija,jasnoća,logika,dokazi,pretpostavke,kontraargumenti,provjerljivost,obrazlozenje,raw_result)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,(opinion_id,"heuristika","v5.2",scores["jasnoća"],scores["logika"],scores["dokazi"],
             scores["pretpostavke"],scores["kontraargumenti"],scores["provjerljivost"],explanation,Jsonb(scores)))
    return redirect(url_for("opinion",opinion_id=opinion_id))

@app.get("/predvidjanja")
def predvidjanja():
    with db() as conn:
        rows=conn.execute("""
          SELECT p.*,m.tvrdnja,m.tema_naziv,m.korisnik_pseudonim
          FROM svjetionik_predvidjanja p JOIN svjetionik_misljenja m ON m.id=p.misljenje_id
          ORDER BY p.rok NULLS LAST,p.id DESC
        """).fetchall()
    body=render_template_string("""
    <div class="hero"><h1>Registar predviđanja</h1><p>Predviđanje se zapisuje prije nego što vrijeme pokaže ishod.</p></div>
    <div class="grid">{% for p in rows %}<article class="card"><span class="badge">{{p.tema_naziv}}</span>
      <h3>{{p.predvidjanje}}</h3><p>{{p.tvrdnja}}</p><p class="muted">Autor: {{p.korisnik_pseudonim}} · Rok: {{p.rok}} · {{p.status}}</p>
      <a class="btn secondary" href="{{url_for('opinion',opinion_id=p.misljenje_id)}}">Mišljenje</a></article>
    {% else %}<p class="muted">Nema predviđanja.</p>{% endfor %}</div>
    """,rows=rows)
    return page("Predviđanja",body)

@app.get("/profil")
def profil():
    ip=request.headers.get("X-Forwarded-For",request.remote_addr or "").split(",")[0].strip()
    with db() as conn:
        rows=conn.execute("""
          SELECT id,tema_naziv,tvrdnja,stvoreno_at
          FROM svjetionik_misljenja WHERE korisnik_ip=%s ORDER BY id DESC
        """,(ip,)).fetchall()
    body=render_template_string("""
    <div class="hero"><h1>Moj profil mišljenja</h1><p class="muted">Profil prati tvoju povijest argumenata i predviđanja, a ne daje ti jednu “ocjenu osobe”.</p></div>
    <div class="grid">{% for m in rows %}<article class="card"><span class="badge">{{m.tema_naziv}}</span><h3>{{m.tvrdnja}}</h3><p class="muted">{{m.stvoreno_at}}</p>
    <a class="btn secondary" href="{{url_for('opinion',opinion_id=m.id)}}">Otvori</a></article>{% else %}<p class="muted">Za ovu sesiju nema zapisanih mišljenja.</p>{% endfor %}</div>
    """,rows=rows)
    return page("Profil",body)

@app.route("/admin/login",methods=["GET","POST"])
def admin_login():
    if request.method=="POST":
        if request.form.get("password")==ADMIN_PASSWORD and ADMIN_PASSWORD:
            session["admin"]=True
            return redirect(url_for("admin"))
        flash("Neispravna lozinka.")
    body="""<div class="hero"><h1>Admin prijava</h1><form method="post" class="card"><label>Lozinka</label><input type="password" name="password" required><div class="actions"><button>Prijava</button></div></form></div>"""
    return page("Admin prijava",body)

@app.get("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("index"))

@app.get("/admin")
@admin_required
def admin():
    with db() as conn:
        counts={}
        for table in ["teme","argumenti","korisnici","svjetionik_misljenja","svjetionik_odgovori","svjetionik_analize","svjetionik_predvidjanja"]:
            counts[table]=conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
    body=render_template_string("""
    <div class="hero"><h1>Administracija</h1><p>V5.2 pregled baze.</p></div>
    <div class="grid">{% for k,v in counts.items() %}<div class="card"><span class="muted">{{k}}</span><div class="score">{{v}}</div></div>{% endfor %}</div>
    """,counts=counts)
    return page("Admin",body)

if __name__ == "__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)))
