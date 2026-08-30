"""Tests des validateurs déterministes stdlib pure (detect/validators.py).

Chaque validateur est testé avec au moins 3 cas vrais et 3 cas faux, comme
demandé par le cahier des charges : un validateur qui accepte tout est aussi
dangereux qu'un validateur qui rejette tout.
"""

from __future__ import annotations

from anonymisation.detect import validators as v


class TestLuhn:
    def test_valid(self) -> None:
        assert v.luhn("4539578763621486")
        assert v.luhn("4111111111111111")
        assert v.luhn("79927398713")

    def test_invalid(self) -> None:
        assert not v.luhn("1234567812345678")
        assert not v.luhn("0000000000000001")
        assert not v.luhn("")


class TestIban:
    def test_valid(self) -> None:
        assert v.validate_iban("FR1420041010050500013M02606")
        assert v.validate_iban("DE89370400440532013000")
        assert v.validate_iban("BE68539007547034")

    def test_invalid(self) -> None:
        assert not v.validate_iban("FR1420041010050500013M02607")  # clé fausse
        assert not v.validate_iban("FR14200410100505000")  # trop court pour FR
        assert not v.validate_iban("pas un iban")


class TestBic:
    def test_valid(self) -> None:
        assert v.validate_bic("BNPAFRPPXXX")
        assert v.validate_bic("BNPAFRPP")
        assert v.validate_bic("DEUTDEFF500")

    def test_invalid(self) -> None:
        assert not v.validate_bic("TROPCOURT")
        assert not v.validate_bic("1234FRPP")
        assert not v.validate_bic("")


class TestNir:
    def test_valid(self) -> None:
        assert v.validate_nir("1 84 03 78 006 084 11")
        assert v.validate_nir("184037800608411")
        # Corse (2A)
        assert v.validate_nir(_corse_example())

    def test_invalid(self) -> None:
        assert not v.validate_nir("1 84 03 78 006 084 12")
        assert not v.validate_nir("pas un nir")
        assert not v.validate_nir("184037800608")  # trop court


def _corse_example() -> str:
    number_part = "184032A006084"
    n = int(number_part.replace("2A", "19"))
    key = 97 - (n % 97)
    return f"{number_part}{key:02d}"


class TestSiren:
    def test_valid(self) -> None:
        assert v.validate_siren("732829320")
        assert v.validate_siren("552081317")
        assert v.validate_siren("343262622")

    def test_invalid(self) -> None:
        assert not v.validate_siren("732829321")
        assert not v.validate_siren("12345678")  # trop court
        assert not v.validate_siren("pas un siren")


class TestSiret:
    def test_valid(self) -> None:
        assert v.validate_siret("73282932000074")
        assert v.validate_siret("55208131700000")

    def test_invalid(self) -> None:
        assert not v.validate_siret("73282932000075")
        assert not v.validate_siret("7328293200007")  # 13 chiffres
        assert not v.validate_siret("pas un siret")


class TestEmail:
    def test_valid(self) -> None:
        assert v.validate_email("jean.dupont@example.fr")
        assert v.validate_email("a@b.co")
        assert v.validate_email("prenom.nom+tag@sous-domaine.example.com")

    def test_invalid(self) -> None:
        assert not v.validate_email("pas-un-email")
        assert not v.validate_email("a@@b.com")
        assert not v.validate_email("a..b@example.com")


class TestPhoneFr:
    def test_valid(self) -> None:
        assert v.validate_phone_fr("06 12 34 56 78")
        assert v.validate_phone_fr("0123456789")
        assert v.validate_phone_fr("+33612345678")

    def test_invalid(self) -> None:
        assert not v.validate_phone_fr("01 23")
        assert not v.validate_phone_fr("123456789")  # ne commence pas par 0
        assert not v.validate_phone_fr("pas un numero")


class TestPhoneGeneric:
    def test_valid(self) -> None:
        assert v.validate_phone_generic("+1 415 555 2671")
        assert v.validate_phone_generic("0123456")
        assert v.validate_phone_generic("+44 20 7946 0958")

    def test_invalid(self) -> None:
        assert not v.validate_phone_generic("123")
        assert not v.validate_phone_generic("1" * 20)
        assert not v.validate_phone_generic("")


class TestIpv4:
    def test_valid(self) -> None:
        assert v.validate_ipv4("192.168.0.1")
        assert v.validate_ipv4("0.0.0.0")
        assert v.validate_ipv4("255.255.255.255")

    def test_invalid(self) -> None:
        assert not v.validate_ipv4("999.1.1.1")
        assert not v.validate_ipv4("1.2.3")
        assert not v.validate_ipv4("01.2.3.4")  # zéro non significatif


class TestIpv6:
    def test_valid(self) -> None:
        assert v.validate_ipv6("2001:db8::1")
        assert v.validate_ipv6("::1")
        assert v.validate_ipv6("fe80::1ff:fe23:4567:890a")

    def test_invalid(self) -> None:
        assert not v.validate_ipv6("pas-une-ip")
        assert not v.validate_ipv6("192.168.0.1")
        assert not v.validate_ipv6("")


class TestMac:
    def test_valid(self) -> None:
        assert v.validate_mac("00:1A:2B:3C:4D:5E")
        assert v.validate_mac("00-1A-2B-3C-4D-5E")
        assert v.validate_mac("ff:ff:ff:ff:ff:ff")

    def test_invalid(self) -> None:
        assert not v.validate_mac("00:1A:2B")
        assert not v.validate_mac("gg:1A:2B:3C:4D:5E")
        assert not v.validate_mac("")


class TestUuid:
    def test_valid(self) -> None:
        assert v.validate_uuid("550e8400-e29b-41d4-a716-446655440000")
        assert v.validate_uuid("00000000-0000-0000-0000-000000000000")
        assert v.validate_uuid("F47AC10B-58CC-4372-A567-0E02B2C3D479")

    def test_invalid(self) -> None:
        assert not v.validate_uuid("pas-un-uuid")
        assert not v.validate_uuid("550e8400-e29b-41d4-a716")
        assert not v.validate_uuid("")


class TestValidateDate:
    def test_valid(self) -> None:
        assert v.validate_date("28/02/2024", "fr") == {"iso": "2024-02-28"}
        assert v.validate_date("March 3, 2024", "en") == {"iso": "2024-03-03"}
        assert v.validate_date("3 mars 2024", "fr") == {"iso": "2024-03-03"}

    def test_invalid(self) -> None:
        assert v.validate_date("n'importe quoi", "fr") is None
        assert v.validate_date("32/13/2024", "fr") is None
        assert v.validate_date("", "fr") is None


class TestValidatorsRegistry:
    def test_all_registered_names_are_callable(self) -> None:
        for name, fn in v.VALIDATORS.items():
            assert callable(fn), name
