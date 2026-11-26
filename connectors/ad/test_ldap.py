"""Unit tests for the minimal LDAP client's BER + filter encoding. Run: python3 -m unittest discover -s connectors/ad"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ldap  # noqa: E402


class BerTest(unittest.TestCase):
    def test_integer(self):
        for n, raw in ((0, "020100"), (127, "02017f"), (128, "02020080"), (-1, "0201ff"), (-128, "020180"),
                       (256, "02020100"), (-129, "0202ff7f")):
            self.assertEqual(ldap.integer(n).hex(), raw, n)
            self.assertEqual(ldap.to_int(ldap.read_tlv(ldap.integer(n))[1]), n)

    def test_lengths(self):
        for size in (0, 1, 127, 128, 255, 256, 70000):
            enc = ldap.octets(b"x" * size)
            tag, content, end = ldap.read_tlv(enc)
            self.assertEqual((tag, len(content), end), (4, size, len(enc)))
        self.assertEqual(ldap.octets(b"x" * 200)[:3].hex(), "0481c8")

    def test_truncated(self):
        with self.assertRaises(ValueError):
            ldap.read_tlv(ldap.octets(b"abc")[:-1])

    def test_bind_request_bytes(self):
        # known-good encoding of BindRequest(v3, "cn=a", simple "b") inside messageID 1
        msg = ldap.seq(ldap.integer(1), ldap.seq(ldap.integer(3), ldap.octets("cn=a"), ldap.octets("b", 0x80), tag=0x60))
        self.assertEqual(msg.hex(), "3011020101600c0201030404636e3d61800162")


class FilterTest(unittest.TestCase):
    def test_equality(self):
        self.assertEqual(ldap.parse_filter("(cn=a)").hex(), "a3070402636e040161")

    def test_present(self):
        self.assertEqual(ldap.parse_filter("(objectClass=*)"), ldap.octets("objectClass", 0x87))

    def test_nested(self):
        enc = ldap.parse_filter("(&(objectCategory=person)(|(cn=a)(!(cn=b))))")
        tag, content, _ = ldap.read_tlv(enc)
        self.assertEqual(tag, 0xA0)
        kids = ldap.children(content)
        self.assertEqual([t for t, _ in kids], [0xA3, 0xA1])
        self.assertEqual([t for t, _ in ldap.children(kids[1][1])], [0xA3, 0xA2])

    def test_ge_le_approx(self):
        self.assertEqual(ldap.read_tlv(ldap.parse_filter("(pwdLastSet>=5)"))[0], 0xA5)
        self.assertEqual(ldap.read_tlv(ldap.parse_filter("(pwdLastSet<=5)"))[0], 0xA6)
        self.assertEqual(ldap.read_tlv(ldap.parse_filter("(cn~=x)"))[0], 0xA8)
        _, c, _ = ldap.read_tlv(ldap.parse_filter("(description=a>=b)"))
        self.assertEqual(ldap.children(c)[1][1], b"a>=b")

    def test_substrings(self):
        _, c, _ = ldap.read_tlv(ldap.parse_filter("(cn=ab*c*d)"))
        attr, subs = ldap.children(c)
        self.assertEqual(attr[1], b"cn")
        self.assertEqual(ldap.children(subs[1]), [(0x80, b"ab"), (0x81, b"c"), (0x82, b"d")])

    def test_extensible(self):
        tag, c, _ = ldap.read_tlv(ldap.parse_filter("(userAccountControl:1.2.840.113556.1.4.803:=2)"))
        self.assertEqual(tag, 0xA9)
        self.assertEqual(ldap.children(c), [(0x81, b"1.2.840.113556.1.4.803"), (0x82, b"userAccountControl"), (0x83, b"2")])

    def test_escape_roundtrip(self):
        nasty = "a*b(c)d\\e"
        enc = ldap.parse_filter(f"(cn={ldap.escape_filter(nasty)})")
        _, c, _ = ldap.read_tlv(enc)
        self.assertEqual(ldap.children(c)[1][1], nasty.encode())
        self.assertEqual(ldap.read_tlv(enc)[0], 0xA3)  # escaped * is not a substring filter

    def test_bad_filters(self):
        for bad in ("cn=a", "(cn=a", "(&)", "(=a)", "(cn=a)(cn=b)"):
            with self.assertRaises((ValueError, IndexError), msg=bad):
                ldap.parse_filter(bad)

    def test_escape_dn(self):
        self.assertEqual(ldap.escape_dn("Doe, John"), "Doe\\, John")
        self.assertEqual(ldap.escape_dn(" #x "), "\\ #x\\ ")
        self.assertEqual(ldap.escape_dn("#a=b+c"), "\\#a\\=b\\+c")

    def test_ad_password(self):
        self.assertEqual(ldap.ad_password("Ab1!"), '"Ab1!"'.encode("utf-16-le"))


if __name__ == "__main__":
    unittest.main()
