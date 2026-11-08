import unittest
from dataclasses import replace

from experiment import Config, analyze, simulate


class ConfigTests(unittest.TestCase):
    def test_units(self):
        c = Config.parse({"frequency": "100 Hz", "sample_rate": "100 kS/s", "samples": 20000})
        self.assertEqual((c.frequency, c.sample_rate, c.samples), (100, 100000, 20000))

    def test_invalid_and_conflicting_parameters(self):
        for args in ({"frequency": "nan"}, {"frequency": "100 kHz"},
                     {"sample_rate": "100 Hz"}, {"samples": True},
                     {"samples": 20001.5}, {"samples": 200001},
                     {"voltage": 5}, {"outputs": [0, 2]},
                     {"input": 0}, {"script": "anything"},
                     {"sample_rate": 1000, "samples": 20000}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                Config.parse(args)

    def test_defaults_are_target_recipe(self):
        c = Config.parse({})
        self.assertEqual((c.outputs, c.input, c.voltage), ((0, 1), 2, 3.3))


class AnalysisTests(unittest.TestCase):
    def test_full_simulation_pass_and_source(self):
        data = simulate(Config(), seed=17)
        result = analyze(data)
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["source"], "simulated")
        self.assertEqual(result["coverage"], 4)
        self.assertEqual(result["samples"], 20000)

    def test_stuck_low_and_nand_fail(self):
        for fault in ("stuck_low", "nand"):
            self.assertEqual(analyze(simulate(Config(), fault=fault))["verdict"], "FAIL")

    def test_missing_input_combinations_never_pass(self):
        data = simulate(replace(Config(), samples=20))
        self.assertEqual(analyze(data)["verdict"], "INCOMPLETE")

    def test_invalid_raw_data_rejected(self):
        data = simulate(Config())
        data.y[10] = 2
        with self.assertRaises(ValueError):
            analyze(data)

    def test_cancelled_simulation(self):
        with self.assertRaises(InterruptedError):
            simulate(Config(), cancelled=lambda: True)

    def test_transition_guard_excludes_delayed_edges(self):
        data = simulate(Config())
        for i in range(1, len(data.a)):
            if data.a[i] != data.a[i-1] or data.b[i] != data.b[i-1]:
                data.y[i] = data.y[i-1]
        r = analyze(data)
        self.assertEqual(r["verdict"], "PASS")
        self.assertGreater(r["excluded_edges"], 0)


if __name__ == "__main__":
    unittest.main()
