# Civilizacijski svjetionik V5.3

V5.3 je integracija V4.1.1 funkcionalnosti s postojećom Neon bazom `agora-baza`.

## Glavno
- postojeće Agora teme, argumenti i korisnici ostaju netaknuti
- V4.1.1 urednički sadržaj tema je sačuvan u aplikaciji
- nova mišljenja koriste `svjetionik_*` tablice
- predviđanja se zapisuju i kasnije provjeravaju
- početna heuristička analiza jasno je označena kao privremena
- nema SQLite baze

## Render
Build: `pip install -r requirements.txt`
Start: `gunicorn app:app`
Health: `/health`

Potrebne varijable:
- `DATABASE_URL`
- `SECRET_KEY`
- `ADMIN_PASSWORD`


## V5.3.2
Popravljen globalni korisnički kontekst koji je mogao rušiti `/` dok `/health` radi; usklađeni su V5 nazivi polja u topic/predictions predlošcima; `/health` označava schema v5.3.2.
