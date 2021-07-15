import logging
import os
import unittest

from main import AddressNormalizer, get_mapbox_token, get_placekey_token

logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.INFO)


class TestAddressEncoder(unittest.TestCase):
    def setUp(self):
        self.g = AddressNormalizer(get_mapbox_token(), get_placekey_token())

    def test_poi(self):
        raw_poi = "ShopRite of Stirling, 1153 Valley Rd, Long Hill, New Jersey 07980, United States"
        placekey = self.g.encode_placekey(raw_poi)
        self.assertEqual("zzw-223@628-hy8-4qf", placekey[1])

    def test_address(self):
        raw_place = "3 BEARS ALaska 10575 KENAI SPUR HWY, KENAI, AK"
        placekey = self.g.encode_placekey(raw_place, "3 Bear Alaska")
        self.assertEqual("222-225@3bh-zsy-9xq", placekey[1])

    def test_csv(self):
        self.g.encode_csv("test_cases.csv", "output.csv", "Address", "Name")
        self.assertTrue(os.path.isfile("output.csv"))
        os.remove("output.csv")
