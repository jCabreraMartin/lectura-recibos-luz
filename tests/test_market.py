import unittest

from invoice_reader.market import parse_endesa, parse_naturgy, parse_totalenergies


class MarketParserTests(unittest.TestCase):
    def test_endesa_public_prices(self):
        text = "T. de energia 0,1090 €/kWh T. potencia hora valle 2,849000 €/kW T. potencia hora punta-llano 2,849000 €/kW"
        offer = parse_endesa(text)[0]
        self.assertEqual(offer["energy"]["price_eur_kwh"], 0.109)
        self.assertAlmostEqual(offer["power"]["punta_eur_kw_day"], 2.849 * 12 / 365)

    def test_naturgy_fixed_and_periods(self):
        text = (
            "Tarifa Por Uso Luz Precio 0,112000 €/kWh "
            "Precios término potencia 0,123030 €/kW*día 0,156477 €/kW*día "
            "0,061562 €/kW*día 0,078299 €/kW*día Permanencia "
            "Valle: 0,073900 €/kWh Llano: 0,109200 €/kWh Punta: 0,182200 €/kWh"
        )
        offers = parse_naturgy(text)
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[1]["energy"]["valle_eur_kwh"], 0.0739)

    def test_totalenergies_tables(self):
        text = (
            "Precios Luz A Tu Aire Siempre sin impuestos Potencia <=10 kW 0.086274 0.086274 0.0999 "
            "Precios Luz A tu Aire Siempre con impuestos 0.109726 "
            "Precios Luz A Tu Aire Ahorro sin impuestos Potencia <=10 kW 0.086274 0.086274 0.163572 0.09393 0.066176 "
            "Precios Luz A tu Aire Ahorro con impuestos 0.109726"
        )
        offers = parse_totalenergies(text)
        self.assertEqual(offers[0]["energy"]["price_eur_kwh"], 0.0999)
        self.assertEqual(offers[1]["energy"]["punta_eur_kwh"], 0.163572)


if __name__ == "__main__":
    unittest.main()

