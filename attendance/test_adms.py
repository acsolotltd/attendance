"""Django-free tests of the ADMS protocol helpers: python -m unittest attendance.test_adms"""
import datetime as dt
import unittest

from attendance import adms


class ParseAttlogTests(unittest.TestCase):
    def test_tab_separated_with_crlf_and_blank_lines(self):
        body = "101\t2026-10-01 08:01:12\t0\t1\t0\t0\t0\t0\r\n\r\n102\t2026-10-01 17:30:00\t1\t15\t0\r\n"
        recs, skipped = adms.parse_attlog(body)
        self.assertEqual(skipped, 0)
        self.assertEqual([r["user_id"] for r in recs], ["101", "102"])
        self.assertEqual(recs[0]["timestamp"], dt.datetime(2026, 10, 1, 8, 1, 12))
        self.assertEqual((recs[1]["punch_code"], recs[1]["verify_code"]), (1, 15))

    def test_key_value_and_space_variants(self):
        recs, skipped = adms.parse_attlog("PIN=7\tDateTime=2026-10-01 09:00:00\tVerified=1\tStatus=0\n"
                                          "8 2026-10-01 10:00:00 1 4 0\n")
        self.assertEqual(skipped, 0)
        self.assertEqual([(r["user_id"], r["punch_code"], r["verify_code"]) for r in recs], [(("7"), 0, 1), ("8", 1, 4)])

    def test_bad_lines_are_skipped_not_fatal(self):
        recs, skipped = adms.parse_attlog("garbage\n101\tnot-a-date\t0\t1\n102\t2026-10-01 08:00:00\t0\t1\n")
        self.assertEqual(len(recs), 1)
        self.assertEqual(skipped, 2)


class OtherParsingTests(unittest.TestCase):
    def test_parse_users_operlog_and_spaces(self):
        body = ("USER PIN=101\tName=Sade Williams\tPri=0\tPasswd=\tCard=\tGrp=1\n"
                "USER PIN=102 Name=Chidi Okafor Pri=0\n"
                "OPLOG 4\t0\t2026-10-01 08:00:00\t0\n"
                "FP PIN=101\tFID=1\tSize=500\n")
        self.assertEqual(adms.parse_users(body), [("101", "Sade Williams"), ("102", "Chidi Okafor")])

    def test_parse_kv(self):
        kv = adms.parse_kv("~DeviceName=MB360,FirmVer=Ver 6.60\nIPAddress=1.2.3.4")
        self.assertEqual(kv, {"DeviceName": "MB360", "FirmVer": "Ver 6.60", "IPAddress": "1.2.3.4"})

    def test_cmd_results_batched(self):
        res = adms.parse_cmd_results("ID=1&Return=0&CMD=INFO\nID=2&Return=-1002&CMD=DATA\nContent=hello\n")
        self.assertEqual(res, [{"id": 1, "ret": 0, "cmd": "INFO"}, {"id": 2, "ret": -1002, "cmd": "DATA"}])

    def test_format_commands(self):
        self.assertEqual(adms.format_commands([]), "OK")
        self.assertEqual(adms.format_commands([(1, "INFO"), (2, "CHECK")]), "C:1:INFO\nC:2:CHECK\n")

    def test_handshake_and_serial(self):
        text = adms.handshake_response("SN12345", att_stamp="999")
        self.assertTrue(text.startswith("GET OPTION FROM: SN12345\n"))
        self.assertIn("ATTLOGStamp=999", text)
        self.assertIn("TransFlag=TransData AttLog", text)
        self.assertTrue(adms.valid_serial("CJDN-2024.001"))
        self.assertFalse(adms.valid_serial("../etc"))
        self.assertFalse(adms.valid_serial(""))


class CompatTests(unittest.TestCase):
    def test_upload_profiles(self):
        self.assertIn("AttPhoto", adms.trans_flag_for("standard"))
        self.assertNotIn("EnrollFP", adms.trans_flag_for("minimal"))
        self.assertTrue(adms.trans_flag_for("minimal").startswith("TransData AttLog"))
        self.assertEqual(adms.trans_flag_for("numeric"), "1111000000")
        self.assertEqual(adms.trans_flag_for("minimal", override="X"), "X")
        self.assertIn("AttLog", adms.trans_flag_for("unknown-profile"))

    def test_decode_body_handles_chinese_and_garbage(self):
        self.assertEqual(adms.decode_body("USER PIN=1\tName=Zoë".encode("utf-8")), "USER PIN=1\tName=Zoë")
        self.assertEqual(adms.decode_body("张伟".encode("gb18030")), "张伟")
        self.assertIsInstance(adms.decode_body(b"\xff\xfe\x00bad"), str)

    def test_push3_transactions_and_users(self):
        recs, skipped = adms.parse_transactions(
            "transaction cardno=0,pin=101,verified=15,doorid=1,inoutstate=1,time=2026-10-01 08:01:02\nnonsense\n")
        self.assertEqual((len(recs), skipped), (1, 1))
        self.assertEqual((recs[0]["user_id"], recs[0]["verify_code"], recs[0]["punch_code"]), ("101", 15, 1))
        self.assertEqual(recs[0]["timestamp"], dt.datetime(2026, 10, 1, 8, 1, 2))
        self.assertEqual(adms.parse_users_v3("user pin=7,name=Bob,pri=0\nuser pin=8,pri=0"), [("7", "Bob")])

    def test_registry_and_push_config(self):
        self.assertEqual(adms.registry_response("abc"), "RegistryCode=abc\n")
        cfg = adms.push_config_response("SESS1", delay=45)
        self.assertIn("SessionID=SESS1", cfg)
        self.assertIn("RequestDelay=45", cfg)
        self.assertIn("Realtime=1", cfg)


if __name__ == "__main__":
    unittest.main()
