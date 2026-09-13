"""Where an organisation's uploaded binaries live (P3b).

One implementation, behind a named seam. The seam exists because the storage
*will* move — candidate uploads are coming, and nobody wants a 20 MB recording
in a database row — and the cost of naming it now is a protocol with four
methods. It is deliberately not more than that: no streaming, no signed URLs, no
content negotiation. Those are the object store's problems when there is one,
and inventing them for a 40 KB logo would be designing for a system that does
not exist yet.

The point of the seam is a single rule: **nothing outside this module reads
`OrgAsset.data`.** That is why `read` hands back bytes rather than a row, and
why `head` exists at all — answering a 304 must not drag a blob out of the
database only to throw it away.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlmodel import Session, select

from .images import NormalizedImage
from .models import OrgAsset


@dataclass(frozen=True)
class Served:
    """An asset, ready to put on the wire."""

    data: bytes
    content_type: str
    sha256: str


class BlobStore(Protocol):
    """Put bytes in, get them back by content address, delete them."""

    def put(self, session: Session, *, org_id: int, kind: str, image: NormalizedImage) -> str:
        """Store `image` for this organisation and return its content address.

        Content-addressed, so storing the same bytes twice for the same
        organisation is the same asset and the existing row is left untouched.
        """

    def read(self, session: Session, sha256: str) -> Served | None:
        """The asset at this address, whoever it belongs to.

        Deliberately not scoped to an organisation: the public route serving a
        logo has no caller to scope by. A sha256 is a 256-bit unguessable name,
        which is the whole access control — and a logo is shown to every
        candidate anyway.
        """

    def head(self, session: Session, sha256: str) -> str | None:
        """The content type at this address, without loading the bytes. `None`
        when there is nothing there."""

    def delete(self, session: Session, *, org_id: int, sha256: str) -> None:
        """Remove one organisation's copy of an address. A no-op when it has
        none. The caller is responsible for having checked that nothing of
        theirs still references it."""


class SqlBlobStore:
    """The bytes live in the row: `bytea` on Postgres, `BLOB` on SQLite.

    Which means a logo survives a redeploy, is visible to every worker, and is
    carried by the same backup as everything else — none of which is true of a
    file written to local disk.

    Two organisations that upload identical bytes get **two rows**, one each, so
    that neither tenant's delete can take the other's logo. `read` and `head`
    are addressed by sha alone and `delete` by (org, sha): serving is public and
    has no caller to scope by, while removing is always somebody's.
    """

    def put(self, session: Session, *, org_id: int, kind: str, image: NormalizedImage) -> str:
        existing = session.exec(
            select(OrgAsset.id).where(
                OrgAsset.org_id == org_id, OrgAsset.sha256 == image.sha256
            )
        ).first()
        if existing is None:
            session.add(
                OrgAsset(
                    org_id=org_id,
                    kind=kind,
                    content_type=image.content_type,
                    sha256=image.sha256,
                    data=image.data,
                    width=image.width,
                    height=image.height,
                )
            )
            session.flush()
        return image.sha256

    def read(self, session: Session, sha256: str) -> Served | None:
        row = session.exec(
            select(OrgAsset.data, OrgAsset.content_type).where(OrgAsset.sha256 == sha256)
        ).first()
        if row is None:
            return None
        data, content_type = row
        return Served(data=data, content_type=content_type, sha256=sha256)

    def head(self, session: Session, sha256: str) -> str | None:
        return session.exec(
            select(OrgAsset.content_type).where(OrgAsset.sha256 == sha256)
        ).first()

    def delete(self, session: Session, *, org_id: int, sha256: str) -> None:
        asset = session.exec(
            select(OrgAsset).where(OrgAsset.org_id == org_id, OrgAsset.sha256 == sha256)
        ).first()
        if asset is not None:
            session.delete(asset)


store: BlobStore = SqlBlobStore()
