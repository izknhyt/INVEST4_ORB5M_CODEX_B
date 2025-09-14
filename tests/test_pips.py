import unittest

from core.pips import is_jpy_cross, pip_size, pips_to_price, price_to_pips, pip_value


class TestPips(unittest.TestCase):
    def test_jpy_cross_detection(self):
        self.assertTrue(is_jpy_cross('USDJPY'))
        self.assertFalse(is_jpy_cross('EURUSD'))

    def test_pip_size(self):
        self.assertEqual(pip_size('USDJPY'), 0.01)
        self.assertEqual(pip_size('EURUSD'), 0.0001)

    def test_pips_price_conversion(self):
        self.assertAlmostEqual(pips_to_price(5, 'USDJPY'), 0.05)
        self.assertAlmostEqual(pips_to_price(5, 'EURUSD'), 0.0005)
        self.assertAlmostEqual(price_to_pips(0.05, 'USDJPY'), 5)
        self.assertAlmostEqual(price_to_pips(0.0005, 'EURUSD'), 5)

    def test_pip_value(self):
        # Classic conventions for 100k base notional
        self.assertAlmostEqual(pip_value('EURUSD', 100_000), 10.0)
        self.assertAlmostEqual(pip_value('USDJPY', 100_000), 1000.0)


if __name__ == '__main__':
    unittest.main()

