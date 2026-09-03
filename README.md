# agora-baza — Civilizacijski svjetionik V5.1

Aplikacija koristi postojeću Neon PostgreSQL bazu projekta `agora-baza`.

Postojeće tablice ostaju netaknute:
- korisnici
- teme
- rasprave
- argumenti

V5.1 koristi nove tablice:
- svjetionik_misljenja
- svjetionik_odgovori
- svjetionik_analize
- svjetionik_predvidjanja
- svjetionik_verzije_misljenja
- svjetionik_ai_dogadaji

## Pokretanje

Postavi varijable:
DATABASE_URL
SECRET_KEY
ADMIN_PASSWORD
PORT (opcionalno, zadano 5000)

Zatim:
pip install -r requirements.txt
python app.py

Health:
GET /health

Napomena: analiza je zasad privremena heuristika. Pravi AI analizator treba spojiti u sljedećoj fazi.
