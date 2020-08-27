"""Guess municipality name from user-provided location (in Dutch)"""

import re
from pathlib import Path
import requests
import pandas as pd
import cbsodata
from fuzzywuzzy import fuzz
from fuzzywuzzy import process
from bs4 import BeautifulSoup as bs


CBS_TABLE = '84734NED'

REMOVE = [
    'the netherlands', 'nederland', 'netherlands', 'holland', 'gemeente', ' nl',
    'europe', 'europa',
]
RECODE_GEM = {
    'den bosch': "'s-Hertogenbosch",
    'den haag': "'s-Gravenhage",
    'the hague': "'s-Gravenhage",
    '❌❌❌': "Amsterdam"
}
GRAVEN = 's[-| ]graven(.*?)$'
THRESHOLD = 85
DELIMITERS = ['|', '/', '&', '(', ')']
AREA_CD_URL = 'https://nl.wikipedia.org/wiki/Lijst_van_Nederlandse_netnummers'


class GuessMunicipality():
    """Contains config and function to guess municipality"""
    def __init__(
            self, dir_config=None, ignore=None, remove=None,
            recode_gem=None, replace=None, threshold=THRESHOLD,
            delimiters=DELIMITERS, area_codes_url=AREA_CD_URL,
            cbs_table=CBS_TABLE):
        """
        :param dir_config: directory where to store config, if None
            config will not be stored
        :param ignore: values that should be ignored
        :param remove: substrings that should be removed
        :param recode_gem: dict of alternative spellings of municipalities
        :param replace: dict of substrings that should be replaced with
            corresponding value
        :param threshold: minimum score for fuzzy matches
        :param delimiters: characters to split location by
        :param area_codes_url: url of Wikipedia page with area codes
        :param cbs_table: id of Statistics Netherlands table with place names

        """
        self.dir_config = dir_config
        if ignore:
            self.ignore = ignore
        else:
            self.ignore = []
        if remove:
            self.remove = remove
        else:
            self.remove = REMOVE
        if recode_gem:
            self.recode_gem = recode_gem
        else:
            self.recode_gem = RECODE_GEM
        if replace:
            self.replace = replace
        else:
            self.replace = {}
        self.threshold = threshold
        if delimiters:
            self.delimiters = delimiters
        else:
            self.delimiters = []
        self.area_codes_url = area_codes_url
        self.cbs_table = cbs_table
        self.config = self.get_config(self.dir_config)
        self.wp, self.gm, self.replace, self.remove = self.config


    def get_area_codes(self):
        """Get area codes from Wikipedia"""
        area_codes = pd.DataFrame(columns=['code', 'place'])
        response = requests.get(self.area_codes_url)
        if response.status_code != 200:
            print('Failed to download area codes')
            return None
        soup = bs(response.text, 'lxml')
        table = soup.find('table')
        rows = table.find_all('tr')
        for row in rows:
            cells = row.find_all('td')
            if cells:
                code, places = cells
                code = code.text.replace('\n', '')
                main_place = places.find('b')
                if not main_place:
                    continue
                main_place = main_place.text.split('(')[0].strip().lower()
                area_codes.loc[len(area_codes)] = [code, main_place]
        return area_codes


    def get_config(self, dir_config):
        """Get config"""
        if dir_config:
            if isinstance(dir_config, str):
                dir_config = Path(dir_config)
            dir_config.mkdir(exist_ok=True)
            path_area_codes = dir_config / 'area_codes.csv'
            path_cbs = dir_config / 'cbs.csv'
        try:
            area_codes = pd.read_csv(path_area_codes, dtype='object')
        except FileNotFoundError:
            area_codes = self.get_area_codes()
            if dir_config:
                area_codes.to_csv(path_area_codes, index=False)
        for code, place in zip(area_codes.code, area_codes.place):
            self.replace[code] = place
        try:
            cbs = pd.read_csv(path_cbs)
        except FileNotFoundError:
            cbs = pd.DataFrame(cbsodata.get_data(self.cbs_table))
            for c in cbs.columns:
                if cbs[c].dtype == 'int64':
                    continue
                cbs[c] = cbs[c].str.strip()
            if dir_config:
                cbs.to_csv(path_cbs, index=False)

        wp = {
            wp.lower():gm
            for wp, gm in zip(cbs.Woonplaatsen, cbs.Naam_2)
            if list(cbs.Woonplaatsen).count(wp) == 1
        }
        gm = {gm.lower():gm for gm in set(cbs.Naam_2)}
        for k, v in self.recode_gem.items():
            gm[k] = v
        remove = list(set(cbs.Naam_4.str.lower())) + self.remove
        remove = [s for s in remove if s not in ['utrecht', 'groningen']]
        return wp, gm, self.replace, remove


    def clean_substring(self, substring):
        """Strip and replace"""
        substring = substring.strip()
        if substring in self.replace:
            return self.replace[substring]
        return substring


    def guess(
            self, location, check_wp=True, check_gm_fuzzy=True,
            check_wp_fuzzy=True):
        """Guess corresponding municipality name"""
        if not isinstance(location, str):
            return
        location = location.lower().strip()
        if location.startswith('bergen '):
            for string in ['n.h.', '(nh', ' nh', 'noord-holland']:
                if string in location:
                    return 'Bergen (NH.)'
            for string in ['(l)', '(l.)', ' l ', 'limburg']:
                if string in location:
                    return 'Bergen (L.)'
        if location in self.ignore:
            return
        for string in self.remove:
            location = location.replace(string, '')
        location = location.strip()
        graven = re.findall(GRAVEN, location)
        if graven:
            location = f"'s-graven{graven[0]}"
        for dlm in self.delimiters:
            location = location.replace(dlm, ',')
        substrings = [self.clean_substring(sub) for sub in location.split(',')
                      if len(sub) > 1]
        for substring in substrings:
            if substring in self.gm:
                return self.gm[substring]
        if check_wp:
            for substring in substrings:
                if substring in self.wp:
                    return self.wp[substring]
        if check_gm_fuzzy:
            for substring in substrings:
                match, score = process.extractOne(substring, self.gm.keys(),
                                                  scorer=fuzz.token_sort_ratio)
                if score >= self.threshold:
                    return self.gm[match]
        if check_wp_fuzzy:
            for substring in substrings:
                match, score = process.extractOne(substring, self.wp.keys(),
                                                  scorer=fuzz.token_sort_ratio)
                if score >= self. threshold:
                    return self.wp[match]
