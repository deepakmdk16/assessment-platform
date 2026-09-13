"""P3b — the organisation's logo: uploading it, serving it, and deleting it.

The interesting half is what is *refused*. An upload is the one place a customer
hands this platform bytes, so every test that rejects something here is a test
that a candidate's browser never renders something a customer supplied.
"""

from __future__ import annotations

import io
import zlib

import pytest
from conftest import register_interviewer  # pytest adds tests/ to sys.path
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select
from test_organizations import auth, invite_colleague, question_payload

from assessment_platform import db as db_module
from assessment_platform.models import Assessment, OrgAsset


def png_bytes(size: tuple[int, int] = (64, 64), color: str = "red") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def jpeg_bytes(size: tuple[int, int] = (64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "blue").save(buf, format="JPEG")
    return buf.getvalue()


def upload(client: TestClient, data: bytes, *, name: str = "logo.png", type_: str = "image/png"):
    return client.put("/orgs/current/logo", files={"file": (name, data, type_)})


def assets() -> list[OrgAsset]:
    with Session(db_module.engine) as s:
        return list(s.exec(select(OrgAsset)).all())


# --------------------------------------------------------------------------- #
# The happy path                                                                #
# --------------------------------------------------------------------------- #


def test_upload_then_serve(client: TestClient) -> None:
    resp = upload(client, png_bytes())
    assert resp.status_code == 200, resp.text
    sha = resp.json()["logo_sha"]
    assert sha is not None and len(sha) == 64

    served = client.get(f"/logos/{sha}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    # Content-addressed, so the strong cache headers are honest.
    assert served.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert served.headers["etag"] == f'"{sha}"'
    assert served.headers["x-content-type-options"] == "nosniff"
    # What is served is what we encoded, and its address is its hash.
    import hashlib

    assert hashlib.sha256(served.content).hexdigest() == sha


def test_a_matching_etag_answers_304_without_the_body(client: TestClient) -> None:
    sha = upload(client, png_bytes()).json()["logo_sha"]
    again = client.get(f"/logos/{sha}", headers={"If-None-Match": f'"{sha}"'})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == f'"{sha}"'


def test_the_stored_image_is_ours_not_the_uploaders(client: TestClient) -> None:
    """The re-encode is the security boundary: EXIF goes, and so does anything
    hiding after the image data."""
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[0x010F] = "Camera Maker"  # Make
    Image.new("RGB", (64, 64), "green").save(buf, format="JPEG", exif=exif)
    # A polyglot: a valid JPEG with a payload appended. Passes a magic-byte
    # check; cannot survive being decoded and written out again.
    hostile = buf.getvalue() + b"<script>alert(1)</script>"

    sha = upload(client, hostile, name="x.jpg", type_="image/jpeg").json()["logo_sha"]
    served = client.get(f"/logos/{sha}")
    assert served.status_code == 200
    assert b"<script>" not in served.content
    with Image.open(io.BytesIO(served.content)) as img:
        assert not dict(img.getexif())


def test_a_large_image_is_scaled_down(client: TestClient) -> None:
    sha = upload(client, png_bytes((2000, 1000))).json()["logo_sha"]
    with Session(db_module.engine) as s:
        asset = s.exec(select(OrgAsset).where(OrgAsset.sha256 == sha)).one()
    # Longest edge capped, aspect ratio kept.
    assert (asset.width, asset.height) == (512, 256)


def test_a_jpeg_stays_a_jpeg_and_a_webp_becomes_a_png(client: TestClient) -> None:
    jpeg_sha = upload(client, jpeg_bytes(), name="l.jpg", type_="image/jpeg").json()["logo_sha"]
    assert client.get(f"/logos/{jpeg_sha}").headers["content-type"] == "image/jpeg"

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "purple").save(buf, format="WEBP")
    webp_sha = upload(client, buf.getvalue(), name="l.webp", type_="image/webp").json()["logo_sha"]
    assert client.get(f"/logos/{webp_sha}").headers["content-type"] == "image/png"


def test_re_uploading_the_same_file_reuses_the_row(client: TestClient) -> None:
    first = upload(client, png_bytes()).json()["logo_sha"]
    second = upload(client, png_bytes()).json()["logo_sha"]
    assert first == second
    assert len(assets()) == 1


# --------------------------------------------------------------------------- #
# What is refused                                                               #
# --------------------------------------------------------------------------- #


def test_an_oversized_upload_is_refused(client: TestClient) -> None:
    # Random-ish noise so PNG compression cannot shrink it under the cap.
    import os

    resp = upload(client, b"\x89PNG\r\n\x1a\n" + os.urandom(300 * 1024))
    assert resp.status_code == 422
    # The cap, and no claim about the file's own size: the handler stops reading
    # one byte past the limit, so it does not know what that size was.
    assert resp.json()["detail"] == "logos are limited to 256 KB."
    assert assets() == []


def test_a_lossy_source_is_not_stored_as_a_bigger_lossless_file(client: TestClient) -> None:
    """Re-encoding a noisy WebP as PNG tripled it — past the cap this module
    advertises, in a row, on every candidate page load."""
    import os

    buf = io.BytesIO()
    Image.frombytes("RGB", (900, 900), os.urandom(900 * 900 * 3)).save(
        buf, format="WEBP", quality=10
    )
    source = buf.getvalue()
    assert len(source) < 256 * 1024  # accepted on the way in

    sha = upload(client, source, name="noise.webp", type_="image/webp").json()["logo_sha"]
    served = client.get(f"/logos/{sha}")
    assert len(served.content) <= 256 * 1024
    assert served.headers["content-type"] == "image/webp"


def test_a_multi_picture_jpeg_is_accepted(client: TestClient) -> None:
    """Android burst and several cameras' HDR modes emit MPO: a plain JPEG SOI
    that Pillow reports as \"MPO\". Demanding format equality refused real
    photos."""
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "orange").save(
        buf, format="MPO", append_images=[Image.new("RGB", (64, 64), "blue")]
    )
    mpo = buf.getvalue()
    assert mpo.startswith(b"\xff\xd8\xff")  # sniffs as an ordinary JPEG
    assert Image.open(io.BytesIO(mpo)).format == "MPO"  # decodes as something else

    resp = upload(client, mpo, name="burst.jpg", type_="image/jpeg")
    assert resp.status_code == 200, resp.text
    served = client.get(f"/logos/{resp.json()['logo_sha']}")
    assert served.headers["content-type"] == "image/jpeg"


def test_svg_is_refused_outright(client: TestClient) -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    resp = upload(client, svg, name="logo.svg", type_="image/svg+xml")
    assert resp.status_code == 422
    assert "SVG" in resp.json()["detail"]


@pytest.mark.parametrize(
    "data, name, type_",
    [
        (b"%PDF-1.4\n%hello", "logo.pdf", "application/pdf"),
        (b"GIF89a" + b"\x00" * 32, "logo.gif", "image/gif"),
        (b"", "empty.png", "image/png"),
        # A PNG header on something that is not a PNG: the sniff passes, the
        # decode does not.
        (b"\x89PNG\r\n\x1a\nnot actually a png at all", "fake.png", "image/png"),
    ],
)
def test_non_images_are_refused(client: TestClient, data: bytes, name: str, type_: str) -> None:
    assert upload(client, data, name=name, type_=type_).status_code == 422
    assert assets() == []


def test_a_declared_content_type_is_not_believed(client: TestClient) -> None:
    """The client says PNG; the bytes say JPEG. The bytes win, and the row
    records what we actually encoded."""
    sha = upload(client, jpeg_bytes(), name="lying.png", type_="image/png").json()["logo_sha"]
    assert client.get(f"/logos/{sha}").headers["content-type"] == "image/jpeg"


def test_an_image_large_enough_to_exhaust_memory_is_refused(client: TestClient) -> None:
    """Under the size cap, over the pixel cap: 4500x4500 is a few KB of solid
    colour that becomes ~81 MB the moment it is converted to RGBA.

    Deliberately between MAX_PIXELS and Pillow's own hard limit (twice that), so
    this exercises our check rather than the library's — the gap is where a file
    small enough to upload could still exhaust a small container.
    """
    buf = io.BytesIO()
    Image.new("RGB", (4500, 4500), "white").save(buf, format="PNG")
    assert len(buf.getvalue()) < 256 * 1024

    resp = upload(client, buf.getvalue())
    assert resp.status_code == 422
    assert "4500" in resp.json()["detail"]
    assert assets() == []


def test_a_decompression_bomb_is_refused(client: TestClient) -> None:
    """A tiny PNG that claims to be 60000x60000. Decoding it honestly would
    allocate ~14 GB; Pillow's pixel guard refuses first."""
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            len(payload).to_bytes(4, "big")
            + kind
            + payload
            + zlib.crc32(kind + payload).to_bytes(4, "big")
        )

    header = (60000).to_bytes(4, "big") + (60000).to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    bomb = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"\x00" * 64))

    assert upload(client, bomb).status_code == 422
    assert assets() == []


def test_an_unknown_address_is_404(client: TestClient) -> None:
    assert client.get("/logos/" + "a" * 64).status_code == 404
    # Not a content address at all — refused without touching the database.
    assert client.get("/logos/../../etc/passwd").status_code == 404
    assert client.get("/logos/short").status_code == 404


# --------------------------------------------------------------------------- #
# Who may change it                                                             #
# --------------------------------------------------------------------------- #


def test_a_member_cannot_upload_or_delete(anon_client: TestClient) -> None:
    admin = register_interviewer(anon_client, "admin@acme.io")
    token = invite_colleague(anon_client, admin, "member@acme.io")
    member = register_interviewer(anon_client, "member@acme.io")
    assert anon_client.post(f"/org-invites/{token}/accept", headers=auth(member)).status_code == 200

    files = {"file": ("l.png", png_bytes(), "image/png")}
    assert anon_client.put("/orgs/current/logo", files=files, headers=auth(member)).status_code == 403
    assert anon_client.delete("/orgs/current/logo", headers=auth(member)).status_code == 403

    # The admin can, and then the member can see the result.
    assert anon_client.put("/orgs/current/logo", files=files, headers=auth(admin)).status_code == 200
    assert anon_client.get("/orgs/current", headers=auth(member)).json()["logo_sha"] is not None


def test_organisations_are_isolated(anon_client: TestClient) -> None:
    a = register_interviewer(anon_client, "a@one.io")
    b = register_interviewer(anon_client, "b@two.io")
    files = {"file": ("l.png", png_bytes(), "image/png")}
    sha = anon_client.put("/orgs/current/logo", files=files, headers=auth(a)).json()["logo_sha"]

    # B's organisation is untouched by A's upload…
    assert anon_client.get("/orgs/current", headers=auth(b)).json()["logo_sha"] is None
    # …and B uploading the same bytes gets a row of its own, so deleting one
    # cannot take the other's logo with it.
    b_sha = anon_client.put("/orgs/current/logo", files=files, headers=auth(b)).json()["logo_sha"]
    assert b_sha == sha  # same content, same address
    assert len(assets()) == 2

    anon_client.delete("/orgs/current/logo", headers=auth(b))
    assert anon_client.get(f"/logos/{sha}").status_code == 200
    assert len(assets()) == 1

    # And when the last holder lets go, the bytes actually go. A reference check
    # that asked "is anyone anywhere using this sha?" would have answered yes for
    # the *other* tenant's row and orphaned this one, still publicly served after
    # both organisations were told their logo was removed.
    anon_client.delete("/orgs/current/logo", headers=auth(a))
    assert assets() == []
    assert anon_client.get(f"/logos/{sha}").status_code == 404


def test_uploading_requires_auth(anon_client: TestClient) -> None:
    files = {"file": ("l.png", png_bytes(), "image/png")}
    assert anon_client.put("/orgs/current/logo", files=files).status_code == 401
    assert anon_client.delete("/orgs/current/logo").status_code == 401


# --------------------------------------------------------------------------- #
# Replacement, snapshots and deletion                                           #
# --------------------------------------------------------------------------- #


def test_replacing_the_logo_leaves_assessments_already_sent_alone(client: TestClient) -> None:
    """The reason the assessment holds a sha rather than reading the org's."""
    old = upload(client, png_bytes(color="red")).json()["logo_sha"]
    client.post("/questions", json=question_payload())
    created = client.post(
        "/assessments", json={"id": "a1", "title": "A", "question_ids": ["sum_n"]}
    ).json()
    assert created["logo_sha"] == old

    new = upload(client, png_bytes(color="blue")).json()["logo_sha"]
    assert new != old
    # The organisation moved on; the assessment did not, and its logo still serves.
    assert client.get("/assessments/a1").json()["logo_sha"] == old
    assert client.get(f"/logos/{old}").status_code == 200
    assert client.get(f"/logos/{new}").status_code == 200


def test_an_unreferenced_logo_is_cleaned_up_when_replaced(client: TestClient) -> None:
    old = upload(client, png_bytes(color="red")).json()["logo_sha"]
    upload(client, png_bytes(color="blue"))
    # Nothing pointed at the first one, so it did not survive the replacement.
    assert client.get(f"/logos/{old}").status_code == 404
    assert len(assets()) == 1


def test_deleting_the_logo_is_idempotent_and_keeps_snapshots(client: TestClient) -> None:
    sha = upload(client, png_bytes()).json()["logo_sha"]
    client.post("/questions", json=question_payload())
    client.post("/assessments", json={"id": "a1", "title": "A", "question_ids": ["sum_n"]})

    first = client.delete("/orgs/current/logo")
    assert first.status_code == 200 and first.json()["logo_sha"] is None
    # The assessment still references it, so the bytes stay.
    assert client.get(f"/logos/{sha}").status_code == 200
    assert client.delete("/orgs/current/logo").status_code == 200


def test_deleting_an_unreferenced_logo_removes_the_bytes(client: TestClient) -> None:
    sha = upload(client, png_bytes()).json()["logo_sha"]
    client.delete("/orgs/current/logo")
    assert client.get(f"/logos/{sha}").status_code == 404
    assert assets() == []


def test_deleting_the_account_takes_the_assets_with_it(client: TestClient) -> None:
    """`_purge_org` must reach every table with an org_id, or Postgres aborts
    the delete on the foreign key."""
    sha = upload(client, png_bytes()).json()["logo_sha"]
    client.post("/questions", json=question_payload())
    client.post("/assessments", json={"id": "a1", "title": "A", "question_ids": ["sum_n"]})

    resp = client.request("DELETE", "/auth/me", json={"password": "pw-long-enough-12"})
    assert resp.status_code == 204, resp.text
    assert assets() == []
    with Session(db_module.engine) as s:
        assert s.exec(select(Assessment)).all() == []
    assert client.get(f"/logos/{sha}").status_code == 404
