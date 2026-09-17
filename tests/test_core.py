
from app.services.dedup import likely_same, fingerprint
from app.services.photo_validator import validate_candidate

def test_dedup():
    a={"name":"Мурка","species":"cat","shelter":"X"}
    b={"name":"мурка","species":"cat","shelter":"X"}
    assert likely_same(a,b)
    assert fingerprint(a)

def test_photo_same_origin():
    assert validate_candidate("https://example.com/a.jpg","https://example.com/pet/1")
    assert not validate_candidate("https://cdn.example.net/a.jpg","https://example.com/pet/1")
