import argparse
import csv
import logging
import os

from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import MapBox
from placekey.api import PlacekeyAPI

ENV_VAR = "MAPBOX_API_TOKEN"

PLACEKEY_ENV_VAR = "PLACEKEY_API_KEY"

FORMAT = '%(asctime)-15s %(clientip)s %(user)-8s %(message)s'
logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.INFO)


def get_token():
    """
    get api token from enviornment
    :return: api token
    """
    api_key = os.environ.get(ENV_VAR)
    if not api_key:
        raise PermissionError(f"API key missing in environment variable {ENV_VAR}")
        return None
    return api_key


def get_placekey_token():
    """
    get api token from enviornment
    :return: api token
    """
    api_key = os.environ.get(PLACEKEY_ENV_VAR)
    if not api_key:
        raise PermissionError(f"API key missing in environment variable {PLACEKEY_ENV_VAR}")
        return None
    return api_key


class AddressNormalizer():
    def __init__(self, mapbox_api_token, placekey_api_token):
        self.geocoder = Geocoder(mapbox_api_token)
        self.pk_api = PlacekeyAPI(placekey_api_token)

    def encode_placekey(self, address, point_of_interest_name=None, prefer_my_name=False):
        """
        encode an address into a placekey.  Allow for
        :param prefer_my_name: If true, ignore point of interest name returned by geocoder if point_of_interest_name
                                parameter is not None.  If false, use the point of interest name returned by geocoder
                                even if point_of_interest_name parameter is not none.
        :param address: address to encode
        :param point_of_interest_name: name of point of interest at address (e.g. Walmart, Target, etc)
                                        This parameter can help get a more precise placekey in case geocoder does not
                                        return a POI result.
        :return: tuple of (clean address, placekey)
        """
        location = self.geocoder.geocode_address(address, one_result=True)
        d = self.result_to_dict(location)
        if point_of_interest_name:
            if not "location_name" in d:  # add point of interest name if doesn't exist
                d["location_name"] = point_of_interest_name
            else:
                if prefer_my_name:  # replace existing poi name if i prefer my own name
                    d["location_name"] = point_of_interest_name

        pk = self.pk_api.lookup_placekey(**d)

        return (location, pk["placekey"])  # placekey result has queryid and placekey properties

    def result_to_dict(self, result):
        """
        parse results from geocoder into a dictionary for use with placekey API
        :param result: geopy geocode result
        :return: dictionary of properties for placekey api
        """
        d = dict()

        # parse out country code, zip, state
        clean = result
        context = clean.raw["context"]
        result_text = clean.raw["text"]

        is_poi = len([y for y in clean.raw["place_type"] if y == "poi"]) > 0  # check if a poi result or address
        if is_poi:
            address = clean.raw["properties"]["address"]
        else:
            address = clean.raw["address"]
        city = next(iter([y["text"] for y in context if y["id"].startswith("place")]), None)
        region = next(iter([y["text"] for y in context if y["id"].startswith("region")]), None)
        postcode = next(iter([y["text"] for y in context if y["id"].startswith("postcode")]), None)
        country_code = next(iter([y["short_code"] for y in context if y["id"].startswith("country")]), None)

        # put restuls into a dictionary
        d["street_address"] = address if is_poi else f"{address} {result_text}"  # non-POI return street differently
        d["region"] = region
        d["postal_code"] = postcode
        d["iso_country_code"] = country_code
        d["city"] = city
        d["latitude"] = result.latitude
        d["longitude"] = result.longitude
        if is_poi:  # only POI result contain the place name
            d["location_name"] = result_text

        return d

    def encode_csv(self, csv_path, output_path, address_column, location_name_column):
        """
        parse addresses from csv file and output to csv file
        :param location_name_column: column name of CSV file with location name
        :param address_column: column name of CSV file with address
        :param csv_path:
        :param output_path:
        :return:
        """

        with open(csv_path, 'r') as f:
            with open(output_path, "w") as o:
                csv_dict_reader = csv.DictReader(f)
                csv_dict_writer = csv.DictWriter(o, fieldnames=[location_name_column, address_column, "placekey"])
                # iterate over each line as a ordered dictionary
                for row in csv_dict_reader:
                    # row variable is a dictionary that represents a row in csv
                    # logging.info(row)
                    address = row[address_column]  # get address
                    location = row[location_name_column]  # get place name
                    placekey = self.encode_placekey(address, location)  # get placekey and cleaned address
                    logging.info((address, location, placekey))

                    d = {x: row[x] for x in row}  # copy row dictionary
                    d["placekey"] = placekey[1]  # add placekey to dictionary
                    d[address_column] = placekey[0]  # overwrite address with normalized address

                    csv_dict_writer.writerow(d)  # write to file


class Geocoder():
    def __init__(self, mapbox_api_token):
        geolocator = MapBox(mapbox_api_token)
        geolocator.geocode = RateLimiter(geolocator.geocode, min_delay_seconds=0.2)
        self.geocode = geolocator.geocode

    def geocode_address(self, location, one_result=True):
        """
        geocode an address
        :param location: address to encode
        :param one_result: only return best fit or list
        :return: result
        """
        result = self.geocode(location, exactly_one=one_result)
        return result


class PlaceKeyFetcher():
    def __init__(self, api_key):
        token = get_placekey_token()
        self.pk_api = PlacekeyAPI(token)

    def dict_to_placekey(self, place):
        """
        Turn dictionary with address components into a placekey
        :param place:   a dictionary with some combination of valid attributes https://github.com/Placekey/placekey-py
                        e.g. location_name, street_address, city, region, postal_code, iso_country_code,
                        latitude, longitude
        :return: placekey
        """
        return self.pk_api.lookup_placekey(**place)


def get_arg_parser():
    parser = argparse.ArgumentParser(description='process CSV file of addresses')

    parser.add_argument('csv', help='input CSV file path')
    parser.add_argument('output', help='output CSV file path')
    parser.add_argument('address', help='address column name from input CSV')
    parser.add_argument('location', help='location column name from input CSV')
    return parser


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    parser = get_arg_parser()
    args = parser.parse_args()

    an = AddressNormalizer(get_token(), get_placekey_token())
    an.encode_csv(args.csv, args.output, args.address, args.location)
