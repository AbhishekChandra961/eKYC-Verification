# Demo-site fixtures (generated: do not edit)

Written by `scripts/export_demo_fixtures.py` from real runs of the eKYC pipeline (README: Live demo).

- `fixtures.gen.ts`: the customer status events of the six demo samples (recorded live, with their timing) and 15
  officer cases (queue row + case detail), exactly as the API returned them. Only the image links are replaced by the
  file names below.
- `images/*.jpg`: the uploaded images of those cases, named by content hash. They are resized for the web
  (documents 1024 px, selfies 360 px, JPEG quality 72, no metadata).

**Licence and source.** The documents are synthetic identity documents from SIDTD (Boned et al., *Synthetic dataset
of ID and Travel Documents*, Scientific Data 11, 2024, CVC-UAB; built on MIDV-2020). Their faces are generated: no real
people. The selfies are simulated photos of those generated portraits. These images are adaptations: resized and
recompressed; the demo samples' selfies are simulated and the blank image is black. They are shared under the same
licence, **CC BY-SA 4.0** (<https://creativecommons.org/licenses/by-sa/4.0/>).
