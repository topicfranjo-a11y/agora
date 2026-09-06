-- Civilizacijski svjetionik V5.7
-- Nadogradnja postojeće Neon baze.
-- NE briše postojeće tablice i NE mijenja postojeće Agora tablice.

BEGIN;

CREATE TABLE IF NOT EXISTS svjetionik_kritike (
    id BIGSERIAL PRIMARY KEY,
    misljenje_id BIGINT NOT NULL REFERENCES svjetionik_misljenja(id) ON DELETE CASCADE,
    korisnik_ip TEXT,
    korisnik_pseudonim TEXT,
    vrsta TEXT NOT NULL DEFAULT 'kontraargument'
        CHECK (vrsta IN ('kontraargument', 'odgovor_autora')),
    tekst TEXT NOT NULL,
    status_analize TEXT NOT NULL DEFAULT 'ceka_analizu'
        CHECK (status_analize IN ('ceka_analizu', 'relevantno', 'nedovoljno_oblikovano', 'greska')),
    stvoreno_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_svjetionik_kritike_misljenje
    ON svjetionik_kritike(misljenje_id);

CREATE INDEX IF NOT EXISTS idx_svjetionik_kritike_vrsta
    ON svjetionik_kritike(vrsta);

CREATE TABLE IF NOT EXISTS svjetionik_analize_kritika (
    id BIGSERIAL PRIMARY KEY,
    kritika_id BIGINT NOT NULL REFERENCES svjetionik_kritike(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    verzija_modela TEXT,
    jasnoca NUMERIC(5,2),
    logika NUMERIC(5,2),
    utemeljenost NUMERIC(5,2),
    pretpostavke NUMERIC(5,2),
    provjerljivost NUMERIC(5,2),
    ukupna_ocjena NUMERIC(5,2),
    prag_relevantnosti BOOLEAN NOT NULL DEFAULT FALSE,
    obrazlozenje TEXT,
    sirovi_rezultat JSONB,
    stvoreno_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_svjetionik_analize_kritika_kritika
    ON svjetionik_analize_kritika(kritika_id);

-- Omogućuje kasnije agregiranje rezultata na razini teme.
-- Pogled je namjerno read-only i ne mijenja podatke.
CREATE OR REPLACE VIEW svjetionik_baza_rasprave AS
SELECT
    m.id AS misljenje_id,
    m.tema_id,
    m.tema_naziv,
    m.korisnik_pseudonim AS autor_pseudonim,
    m.tvrdnja,
    m.stvoreno_at AS tvrdnja_stvorena_at,
    k.id AS kritika_id,
    k.vrsta,
    k.korisnik_pseudonim AS kriticar_pseudonim,
    k.tekst AS kritika,
    k.status_analize,
    a.jasnoca,
    a.logika,
    a.utemeljenost,
    a.pretpostavke,
    a.provjerljivost,
    a.ukupna_ocjena,
    a.prag_relevantnosti,
    k.stvoreno_at AS kritika_stvorena_at
FROM svjetionik_misljenja m
LEFT JOIN svjetionik_kritike k ON k.misljenje_id = m.id
LEFT JOIN LATERAL (
    SELECT *
    FROM svjetionik_analize_kritika ak
    WHERE ak.kritika_id = k.id
    ORDER BY ak.id DESC
    LIMIT 1
) a ON TRUE;

COMMIT;
