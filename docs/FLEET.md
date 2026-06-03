# Unos prave flote i paketi cijena

## Model cijena: paketi

Svaka jedinica (brod / jet ski) ima vlastite **pakete**: naziv + trajanje + cijena.
Primjeri:
- Brod: "4h" (240 min), "8h" (480 min), "Sunset 2h" (120 min)
- Jet ski: "30 min", "1h", "2h", "Safari 90min" (s vodičem), "Safari 120min"

Depozit je **postotak** (deposit_percent), npr. 30%. Ostatak se plaća na licu mjesta.

## Učitavanje stvarne flote

Nakon migracija pokreni:

```bash
python -m scripts.seed_fleet            # doda flotu ako je baza prazna
python -m scripts.seed_fleet --reset    # obriše assete+pakete i učita ispočetka
```

Skripta učita 6 brodova + 6 jet skija s točnim cijenama i paketima.
Auti (E-klase) i kombiji (Vito) NISU u floti jer služe samo za transfer — to je
zaseban sloj koji se dodaje kasnije.

## Uređivanje flote i paketa

Sve se može mijenjati u admin sučelju (stranica **Assets**, gumb Edit):
- osnovni podaci (ime, kapacitet, depozit %, kalendar, lokacija)
- paketi: dodavanje (naziv/trajanje/cijena), brisanje

Ili kroz API: `POST /api/packages`, `PATCH /api/packages/{id}`,
`DELETE /api/packages/{id}`, `GET /api/packages/by-asset/{asset_id}`.

## Napomena o dozvoli za jet ski

Jet skiji su interno označeni da po zakonu trebaju dozvolu
(`requires_license=true`), ali `show_license_to_customer=false`, pa AI i javne
površine NIKAD ne spominju dozvolu kupcima.
