"""Reservations integration (OpenTable), mock-first.

This is Switchboard's FIRST module, backing `POST /v1/reservations/{availability,
book,modify,cancel}`. It ships a MOCK backend now (fake-but-contract-shaped data)
so the full caller -> gateway -> result loop is testable and demoable BEFORE real
OpenTable partner approval lands. When approval lands, the real
`OpenTableReservationsBackend` is implemented and `RESERVATIONS_BACKEND` is flipped
to `opentable` — callers change NOTHING (same endpoints, same bodies, same
envelope; only `mock` flips to false).

Module layout (the shape every future integration copies):
  - models.py         typed request/result models (the data shapes)
  - interface.py      the typed `ReservationsBackend` Protocol every backend implements
  - backend_mock.py   `MockReservationsBackend` — fake data, the DEFAULT
  - backend_opentable.py  real client — clearly-marked SEAM, not implemented yet (Rule 2)
  - backends.py       backend selection from config (mock | opentable)
"""

from __future__ import annotations

# The envelope `source` label and the per-tenant credential namespace for this
# module. `SOURCE` names the module in the uniform envelope; `CREDENTIAL_NAMESPACE`
# is the vendor namespace used to resolve per-tenant secrets
# (SWITCHBOARD_OPENTABLE__<TENANT>__API_KEY) — the module is "reservations", the
# upstream vendor / credential namespace is OpenTable.
SOURCE: str = "reservations"
CREDENTIAL_NAMESPACE: str = "OPENTABLE"
