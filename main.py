"""
This program is intended to take a list of addresses for POI (points of interest), clean them up in mapbox,
then generate a placekey for that POI.

See for more info, placekey whitepaper here: https://docs.placekey.io/Placekey_Technical_White_Paper.pdf


TODO: remove mapbox dependency (make optional)

TODO: reduce number of calls to placekey api to streamline processing

TODO: multi-thread?
"""
import argparse
import csv
import logging
import os
from pathlib import Path

from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import MapBox
from placekey.api import PlacekeyAPI

ENV_VAR = "MAPBOX_API_TOKEN"  # environment variable with mapbox api key

PLACEKEY_ENV_VAR = "PLACEKEY_API_KEY"  # environment variable with placekey api key

logging.basicConfig(format='%(asctime)s;%(levelname)s;%(message)s', level=logging.INFO)  # logging config



class AddressNormalizer():
    """
    This class contains methods for encoding a placekey given an address.  Optional arguments include a point of
    interest name.

    POI names are required to get granular results from the placekey api.  For example, a placekey for
    a particular store at a particular address.  Otherwise the placekey will only include address information and h3
    hex.  In some cases address or latitude / longitude is enough but poi placekeys contain the most information.

    See this documentation on joining non-POI and POI placekeys.
    https://www.placekey.io/tutorials/joining-poi-and-non-poi-datasets-with-placekey

    """
    def __init__(self, mapbox_api_token, placekey_api_token):
        """
        initialize the mapbox and placekey api tokens
        :param mapbox_api_token: mapbox api token
        :param placekey_api_token: placekey api token
        """
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
        d=None
        try:
            d = self.result_to_dict(location)
        except KeyError as k:
            logging.error(f"Could not parse raw mapbox result. {location.raw} {k}")

        if point_of_interest_name:
            if not "location_name" in d:  # add point of interest name if doesn't exist
                d["location_name"] = point_of_interest_name
            else:
                if prefer_my_name:  # replace existing poi name if i prefer my own name
                    d["location_name"] = point_of_interest_name

        pk = self.pk_api.lookup_placekey(**d)

        # if we got an error from placekey, try again using a different parsing method
        if "error" in pk:
            logging.warning(f"Placekey not found for address {d} {pk} (1st attempt)")
            d = self.parse_address(location)
            pk = self.pk_api.lookup_placekey(**d)

        if "error" in pk:
            raise ValueError(f"Placekey not found for address {d} {pk} (2nd attempt)")

        return (location, pk["placekey"])  # placekey result has queryid and placekey properties

    def parse_address(self, location):
        """
        parse adress into placekey input parameters
         e.g. location_name, street_address, city, region, postal_code, iso_country_code, latitude, longitude
        :param location: Location object result from geopy
        :return: dictionary of placekey inputs
        """
        address= location.address
        parts = address.split(", ")
        parts = [x.upper().strip() for x in parts] # upper case and strip whitespace all parts
        country = parts.pop()
        region_zip = parts.pop()
        city = parts.pop()
        address = parts.pop()
        location_name = ", ".join(parts)


        # separate region from zip
        region_parts = region_zip.split()
        zipcode = region_parts.pop()
        region = " ".join(region_parts)

        #country code logic
        if country == "United States".upper():  # todo: add other countries later
            country_code = "us"
        else:
            raise ValueError("Could not map country code")


        d = {
            "street_address": address,
            "region": region,
            "postal_code": zipcode,
            "location_name": location_name,
            "city":city,
            "iso_country_code":country_code,
            "latitude": location.latitude,
            "longitude" : location.longitude
        }

        if len(location_name.strip())<1: # remove location name if it's empty
            d.pop("location_name",None)

        return d


    def result_to_dict(self, result):
        """
        parse results from geocoder into a dictionary for use with placekey API
        :param result: geopy geocode result
        :return: dictionary of properties for placekey api
        """
        d = dict()

        # parse out country code, zip, state
        clean = result
        # logging.info((clean.address,clean.raw))
        context = clean.raw["context"]
        result_text = clean.raw["text"]

        is_poi = len([y for y in clean.raw["place_type"] if y == "poi"]) > 0  # check if a poi result or address
        if is_poi:
            properties = clean.raw.get("properties")
            address = properties.get("address")
        else:
            address = clean.raw.get("address")
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
        try:

            with open(csv_path, 'r') as f:
                with open(output_path, "w") as o:
                    csv_dict_reader = csv.DictReader(f)
                    csv_dict_writer = csv.DictWriter(o, fieldnames=[location_name_column, address_column, "placekey"])
                    csv_dict_writer.writeheader()

                    # iterate over each line as a ordered dictionary
                    for row in csv_dict_reader:
                        # row variable is a dictionary that represents a row in csv
                        # logging.info(row)
                        address = row[address_column]  # get address
                        location = row[location_name_column]  # get place name
                        logging.info((address, location))
                        placekey=None
                        try:
                            placekey = self.encode_placekey(address, location)  # get placekey and cleaned address
                        except ValueError as v:
                            logging.error(f"Error occurred fetching placekey for {address} | {location} | {v}")

                        d = {x: row[x] for x in row}  # copy row dictionary
                        if placekey:
                            d["placekey"] = placekey[1]  # add placekey to dictionary
                            d[address_column] = placekey[0]  # overwrite address with normalized address

                        csv_dict_writer.writerow(d)  # write to file

        except Exception as e:
            logging.error(f"Error occurred writing to file {e}")
            raise e



class Geocoder():
    """
    this class encodes and normalizes an address using the mapbox geocoder api endpoint.

    See mapbox geocoding documentation here: https://docs.mapbox.com/api/search/geocoding/
    """
    def __init__(self, mapbox_api_token):
        """
        initialize the mapbox api token
        :param mapbox_api_token: mapbox api token
        """
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
    """
    this class conencts via the placekey api (only used for debugging)
    """
    def __init__(self, api_key):
        """
        initialize api key
        :param api_key:
        """
        self.pk_api = PlacekeyAPI(api_key)

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
    """
    initialize command line argument parser.
    :return:
    """
    parser = argparse.ArgumentParser(description='process CSV file of addresses')

    parser.add_argument('csv', help='input CSV file path')
    parser.add_argument('output', help='output CSV file path')
    parser.add_argument('address', help='address column name from input CSV')
    parser.add_argument('location', help='location column name from input CSV')
    return parser


def get_mapbox_token():
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


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    parser = get_arg_parser()
    args = parser.parse_args()

    an = AddressNormalizer(get_mapbox_token(), get_placekey_token())
    output_absoute = Path(args.output).resolve()
    input_path = Path(args.csv).resolve()
    logging.info(f"Writing to {output_absoute} from {input_path} address: {args.address} location: {args.location}")

    an.encode_csv(args.csv, args.output, args.address, args.location)
