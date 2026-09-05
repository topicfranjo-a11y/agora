# Civilizacijski svjetionik — V5.6.10

Javna eksperimentalna verzija.

## Važna izmjena

Popratni tekstovi tema koje administrator unese sada se trajno spremaju u postojeću Neon tablicu `rasprave`, u stupac `provokacija`, kao JSON tekst.

Spremanje koristi `UPDATE` pa `INSERT`, a nakon zapisa aplikacija odmah provjerava sadržaj u bazi prije `COMMIT`-a. Nema promjene Neon sheme.

## Render

- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app`
- Health: `/health`
- Environment: `DATABASE_URL`, `SECRET_KEY`, `ADMIN_PASSWORD`
