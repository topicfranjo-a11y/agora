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
