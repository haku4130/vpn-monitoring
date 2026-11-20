import unittest
from alerter import entry_label, parse_checker_errors, checker_problem

LABELS = {"node-e.example.net": "node-a", "203.0.113.10": "node-b"}

LOG = """\
2026/11/09 10:59:20 [ERROR] 🇬🇧 Великобритания | Get "https://archive.torproject.org/x.tar.xz": context deadline exceeded (Client.Timeout exceeded while awaiting headers)
2026/11/09 10:59:28 [ERROR] 🇫🇮 #1 Финляндия | Failed | Download error after 527522 bytes: context deadline exceeded (Client.Timeout or context cancellation while reading body) | Latency: 3.819969761s
2026/11/09 11:14:16 [ERROR] 🇷🇺 Россия | Get "https://archive.torproject.org/x.tar.xz": EOF
2026/11/09 11:14:10 [ERROR] 🇩🇪 Германия | Get "https://x": EOF
2026/11/09 11:14:20 🇩🇪 Германия | Success | Downloaded: 1055522 bytes (min: 1048576) | Latency: 484.28ms
2026/11/09 11:29:10 Starting proxy check iteration
2026/11/09 11:29:20 [ERROR] 🇬🇧 Великобритания | Get "https://archive.torproject.org/x.tar.xz": dial tcp 1.2.3.4:443: connect: connection refused
"""


class EntryLabel(unittest.TestCase):
    def test_known_host(self):
        self.assertEqual(entry_label("node-e.example.net:3442", LABELS), "node-a (node-e.example.net:3442)")

    def test_ip_host(self):
        self.assertEqual(entry_label("203.0.113.10:3459", LABELS), "node-b (203.0.113.10:3459)")

    def test_unknown_host_unchanged(self):
        self.assertEqual(entry_label("exit-1.example.net:443", LABELS), "exit-1.example.net:443")

    def test_no_labels(self):
        self.assertEqual(entry_label("node-e.example.net:3442", None), "node-e.example.net:3442")


class ParseErrors(unittest.TestCase):
    def test_last_error_per_location(self):
        errs = parse_checker_errors(LOG)
        self.assertIn("connection refused", errs["🇬🇧 Великобритания"])
        self.assertIn("Download error after 527522", errs["🇫🇮 #1 Финляндия"])
        self.assertNotIn("🇩🇪 Германия", errs)


class Problem(unittest.TestCase):
    def test_no_first_byte(self):
        line = 'Get "https://x": context deadline exceeded (Client.Timeout exceeded while awaiting headers)'
        self.assertEqual(checker_problem(line, 4, 1048576),
                         "не ответил за 4 с — нет даже первого байта (не полоса, а задержка или обрыв)")

    def test_partial_download_is_throttling(self):
        line = "Failed | Download error after 527522 bytes: context deadline exceeded"
        self.assertEqual(checker_problem(line, 4, 1048576),
                         "отдал 515 из 1024 КБ за 4 с — режут полосу")

    def test_eof(self):
        self.assertEqual(checker_problem('Get "https://x": EOF', 4, 1048576), "соединение оборвалось (EOF)")

    def test_refused(self):
        line = 'Get "https://x": dial tcp 1.2.3.4:443: connect: connection refused'
        self.assertEqual(checker_problem(line, 4, 1048576), "соединение отклонено (connection refused)")

    def test_unknown_error_is_shortened(self):
        line = 'Get "https://x": ' + "очень длинная ошибка " * 20
        p = checker_problem(line, 4, 1048576)
        self.assertTrue(p.startswith("ошибка: "))
        self.assertLessEqual(len(p), 130)

    def test_no_log_line_falls_back(self):
        self.assertEqual(checker_problem(None, 4, 1048576),
                         "не отдал 1024 КБ за 4 с (причина в логе чекера не найдена)")

    def test_ip_checker_no_size(self):
        line = 'Get "https://api.ipify.org": context deadline exceeded (Client.Timeout exceeded while awaiting headers)'
        self.assertEqual(checker_problem(line, None, None),
                         "не ответил за отведённое время — нет даже первого байта (не полоса, а задержка или обрыв)")


if __name__ == "__main__":
    unittest.main()
