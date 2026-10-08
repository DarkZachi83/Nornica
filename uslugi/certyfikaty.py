# SPDX-License-Identifier: GPL-3.0-or-later
"""Certyfikaty HTTPS dla serwera skanera w sieci domowej.

Przeglądarka pozwala stronie używać kamery na żywo tylko przez HTTPS. Program
tworzy WŁASNY mały urząd certyfikacji (jak narzędzie mkcert) i nim podpisuje
certyfikat serwera z adresami komputera w sieci:

  * urząd (ca.crt) instaluje się na telefonie RAZ — potem połączenie jest
    w pełni zaufane, bez ostrzeżeń, z kamerą na żywo,
  * bez instalacji urzędu przeglądarka pokaże ostrzeżenie; po akceptacji
    działa przynajmniej tryb zdjęcia.

Wymagania Apple dla certyfikatów TLS (inaczej iOS odrzuci certyfikat nawet po
zaufaniu urzędowi): klucz RSA ≥ 2048 bitów, SHA-256, ważność certyfikatu
serwera ≤ 825 dni, rozszerzenia SubjectAltName i ExtendedKeyUsage=serverAuth.

Klucz prywatny urzędu nie opuszcza komputera; pliki mają prawa 0600.
Certyfikat serwera jest odnawiany, gdy zmieni się adres komputera w sieci
albo zbliża się koniec ważności — urząd zostaje ten sam, więc telefon nie
wymaga ponownej instalacji.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import os
from pathlib import Path

from wyjatki import BladNornicy

WAZNOSC_URZEDU_DNI = 3650
WAZNOSC_SERWERA_DNI = 820            # < 825 dni (limit Apple)
ODNOW_PRZED_KONCEM_DNI = 30


def dostepne() -> bool:
    import importlib.util
    return importlib.util.find_spec("cryptography") is not None


def koniec_waznosci(cert) -> dt.datetime:
    """not_valid_after_utc jest dopiero od cryptography 42; wcześniej not_valid_after (bez strefy, w UTC).
    W requirements.txt deklarujemy zgodność od wersji 41."""
    if hasattr(cert, "not_valid_after_utc"):
        return cert.not_valid_after_utc
    return cert.not_valid_after.replace(tzinfo=dt.timezone.utc)


def poczatek_waznosci(cert) -> dt.datetime:
    if hasattr(cert, "not_valid_before_utc"):
        return cert.not_valid_before_utc
    return cert.not_valid_before.replace(tzinfo=dt.timezone.utc)


def _zapisz_prywatny(sciezka: Path, dane: bytes) -> None:
    sciezka.write_bytes(dane)
    try:
        os.chmod(sciezka, 0o600)
    except OSError:
        pass                          # Windows: prawa dostępu działają inaczej


def _urzad(katalog: Path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    plik_cert, plik_klucz = katalog / "ca.crt", katalog / "ca.key"
    if plik_cert.exists() and plik_klucz.exists():
        return (x509.load_pem_x509_certificate(plik_cert.read_bytes()),
                serialization.load_pem_private_key(plik_klucz.read_bytes(), password=None))
    klucz = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nazwa = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "NORNICA / VOLE — urząd lokalny"),
                       x509.NameAttribute(NameOID.ORGANIZATION_NAME, "NORNICA / VOLE")])
    teraz = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(nazwa).issuer_name(nazwa).public_key(klucz.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(teraz - dt.timedelta(days=1))
            .not_valid_after(teraz + dt.timedelta(days=WAZNOSC_URZEDU_DNI))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(klucz.public_key()), critical=False)
            .sign(klucz, hashes.SHA256()))
    katalog.mkdir(parents=True, exist_ok=True)
    plik_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _zapisz_prywatny(plik_klucz, klucz.private_bytes(serialization.Encoding.PEM,
                                                     serialization.PrivateFormat.PKCS8,
                                                     serialization.NoEncryption()))
    return cert, klucz


def _wymaga_odnowienia(plik: Path, adresy: list[str]) -> bool:
    from cryptography import x509
    if not plik.exists():
        return True
    cert = x509.load_pem_x509_certificate(plik.read_bytes())
    koniec = koniec_waznosci(cert)
    if koniec - dt.datetime.now(dt.timezone.utc) < dt.timedelta(days=ODNOW_PRZED_KONCEM_DNI):
        return True
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return True
    w_certyfikacie = {str(a) for a in san.get_values_for_type(x509.IPAddress)}
    return not set(adresy) <= w_certyfikacie


def przygotuj(katalog: Path, adresy: list[str]) -> dict[str, Path]:
    """Zapewnia urząd i aktualny certyfikat serwera dla podanych adresów IP.
    Zwraca ścieżki: ca (do instalacji na telefonie), cert i klucz serwera."""
    if not dostepne():
        raise BladNornicy("blad.brak_cryptography")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    katalog = Path(katalog)
    cert_urzedu, klucz_urzedu = _urzad(katalog)
    plik_cert, plik_klucz = katalog / "serwer.crt", katalog / "serwer.key"
    adresy = sorted({*adresy, "127.0.0.1"})
    if _wymaga_odnowienia(plik_cert, adresy) or not plik_klucz.exists():
        klucz = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        teraz = dt.datetime.now(dt.timezone.utc)
        san = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(a)) for a in adresy]
        cert = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "NORNICA / VOLE")]))
                .issuer_name(cert_urzedu.subject).public_key(klucz.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(teraz - dt.timedelta(days=1))
                .not_valid_after(teraz + dt.timedelta(days=WAZNOSC_SERWERA_DNI))
                .add_extension(x509.SubjectAlternativeName(san), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True,
                                             content_commitment=False, data_encipherment=False,
                                             key_agreement=False, key_cert_sign=False, crl_sign=False,
                                             encipher_only=False, decipher_only=False), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(klucz_urzedu.public_key()),
                               critical=False)
                .sign(klucz_urzedu, hashes.SHA256()))
        plik_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        _zapisz_prywatny(plik_klucz, klucz.private_bytes(serialization.Encoding.PEM,
                                                         serialization.PrivateFormat.PKCS8,
                                                         serialization.NoEncryption()))
    return {"ca": katalog / "ca.crt", "cert": plik_cert, "klucz": plik_klucz}
