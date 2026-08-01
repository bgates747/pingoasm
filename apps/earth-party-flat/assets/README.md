# Earth Party real-star source data

`stars.tsv` is the small, offline catalogue snapshot consumed by
`build/scripts/generate_earth_party_starfield.py`. It contains 128 visible
stars selected from the Bright Star Catalogue:

1. every normal Johnson-V entry with `Vmag <= 2.00`; and
2. the principal Bayer vertices of 19 familiar Western constellation figures.

Close catalogue components within 0.01 degrees are merged into one visible
star by adding their V-band flux. This prevents Alpha Centauri and Acrux from
becoming overlapping five-pointed meshes.

The numerical source is:

- Hoffleit, D. and Warren, W. H. Jr. (1991), *Bright Star Catalogue,
  5th Revised Ed.*, CDS V/50;
- catalogue DOI: `10.26093/cds/vizier`;
- source archive:
  `https://cdsarc.cds.unistra.fr/ftp/V/50/catalog.gz`; and
- verified archive SHA-256:
  `3dc44b1e90be8fbe5bcc7656032560f51275f985c7e3f783c9028e1838ec7bed`.

The IAU defines constellations as bounded sky areas rather than prescribing
stick figures. The Bayer-vertex lists are therefore an editorial rendering
choice, recorded explicitly in the refresh script. Proper-name spellings
follow the IAU Working Group on Star Names.

Refresh the tracked subset explicitly:

```bash
.venv/bin/python build/scripts/update_earth_party_star_catalog.py
```

The ordinary application build is deliberately offline: it reads `stars.tsv`
and never downloads a catalogue. VizieR requires attribution to the original
catalogue and asks users to check source-specific terms for commercial reuse;
the complete upstream catalogue is not vendored here.
